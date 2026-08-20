from __future__ import annotations

import datetime as dt
import shutil
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from .ablation import (
    factors,
    generate_internal_incumbent,
    solve_decomposed_primary,
    validate_cell,
)
from .checker import verify_primary_checkpoint, verify_result
from .deadline import RunDeadline, RunDeadlineExceeded
from .highs import solve_pricing_lp, solve_primary_milp
from .model import build_extensive_model
from .monitor import PeakMemoryMonitor, monotonic_seconds
from .paths import require_local_path, resolve_from, sha256_file, write_json
from .results import (
    build_primary_checkpoint,
    build_result_payload,
    git_commit,
    git_is_clean,
    load_result,
    physical_arrays,
    pricing_arrays,
    primary_result_from_checkpoint,
    read_npz,
    save_result,
    write_npz,
)
from .source import read_case


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _artifact(root: Path, path: Path, sha256: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256,
        "bytes": path.stat().st_size,
    }


def run_official_benchmark(root: Path, config_path: Path, config: dict) -> dict[str, Any]:
    root = require_local_path(root, "repository")
    config_path = require_local_path(config_path, "configuration")
    result_directory = resolve_from(root, config["result_directory"], "result directory")
    lock_path = resolve_from(root, config["run_lock"], "official-run lock")
    if lock_path.exists():
        raise RuntimeError(
            f"Official run lock already exists at {lock_path}; automatic replacement is forbidden"
        )
    if not git_is_clean(root):
        raise RuntimeError("Official benchmark requires a clean, frozen Git worktree")
    validate_cell(config, check_environment=True)
    commit = git_commit(root)
    config_hash = sha256_file(config_path)
    result_directory.mkdir(parents=True, exist_ok=True)
    lock = {
        "status": "started",
        "started_utc": _utc_now(),
        "git_commit": commit,
        "config_sha256": config_hash,
        "profile": config["profile"],
    }
    write_json(lock_path, lock)

    monitor = PeakMemoryMonitor()
    monitor.start()
    run_budget = config.get("run_budget", {})
    run_limit = run_budget.get("end_to_end_limit_seconds")
    deadline = RunDeadline.start(None if run_limit is None else float(run_limit))
    total_start = deadline.started
    timings: dict[str, float] = {}
    result_path: Path | None = None
    try:
        step = monotonic_seconds()
        case = read_case(root, config)
        timings["source_ingest"] = monotonic_seconds() - step
        deadline.check("model build")

        step = monotonic_seconds()
        model = build_extensive_model(case, config)
        timings["model_build"] = monotonic_seconds() - step
        deadline.check("primary solve")

        step = monotonic_seconds()
        post_primary_reserve = float(run_budget.get("post_primary_reserve_seconds", 0.0))
        enabled = factors(config)
        initial_solution = None
        incumbent_diagnostics = None
        if enabled["internal_incumbent"]:
            incumbent_step = monotonic_seconds()
            initial_solution, incumbent_diagnostics = generate_internal_incumbent(
                case,
                model,
                config,
                deadline,
                reserve_seconds=post_primary_reserve,
            )
            timings["internal_incumbent"] = monotonic_seconds() - incumbent_step
        if enabled["decomposition"]:
            primary = solve_decomposed_primary(
                case,
                model,
                config,
                deadline,
                reserve_seconds=post_primary_reserve,
                initial_full_start=initial_solution,
                incumbent_diagnostics=incumbent_diagnostics,
            )
        else:
            primary = solve_primary_milp(
                model,
                config,
                time_limit_seconds=deadline.solver_limit(
                    "primary solve",
                    reserve_seconds=post_primary_reserve,
                ),
                initial_solution=initial_solution,
            )
            if incumbent_diagnostics is not None:
                primary.acceleration["internal_incumbent"] = incumbent_diagnostics
        timings["primary_milp_total"] = monotonic_seconds() - step
        timings["primary_milp"] = primary.primary.wall_seconds
        deadline.check(
            "primary checkpoint",
            reserve_seconds=float(run_budget.get("post_primary_reserve_seconds", 0.0)),
        )

        step = monotonic_seconds()
        primary_path = require_local_path(result_directory / "primary-primal.npz", "primary primal")
        primary_hash = write_npz(primary_path, physical_arrays(model, primary.column_values))
        checkpoint_path = require_local_path(
            result_directory / "primary-checkpoint.json", "primary checkpoint"
        )
        checkpoint = build_primary_checkpoint(
            model,
            config,
            config_hash,
            commit,
            primary,
            _artifact(root, primary_path, primary_hash),
            timings,
            monitor.peak_rss_bytes,
        )
        save_result(checkpoint_path, checkpoint)
        timings["primary_checkpoint_serialization"] = monotonic_seconds() - step
        checkpoint["timings_seconds"] = dict(timings)
        checkpoint["peak_rss_bytes"] = monitor.peak_rss_bytes
        save_result(checkpoint_path, checkpoint)
        lock.update(
            {
                "status": "primary_saved",
                "primary_checkpoint": checkpoint_path.relative_to(root).as_posix(),
                "primary_primal": primary_path.relative_to(root).as_posix(),
                "primary_objective_usd": primary.objective,
                "primary_dual_bound_usd": primary.primary.dual_bound,
                "primary_mip_gap": primary.primary.mip_gap,
            }
        )
        write_json(lock_path, lock)

        step = monotonic_seconds()
        primary_checker = verify_primary_checkpoint(root, config, checkpoint_path, config_path)
        timings["independent_primary_verification"] = monotonic_seconds() - step
        checkpoint = load_result(checkpoint_path)
        checkpoint["timings_seconds"] = dict(timings)
        checkpoint["peak_rss_bytes"] = monitor.peak_rss_bytes
        save_result(checkpoint_path, checkpoint)
        lock["primary_checker"] = primary_checker["status"]
        if primary_checker["status"] != "pass":
            lock["status"] = "failed_acceptance"
            write_json(lock_path, lock)
            raise RuntimeError(f"Primary solution failed independent acceptance: {primary_checker}")
        lock["status"] = "primary_verified"
        write_json(lock_path, lock)
        deadline.check(
            "pricing solve",
            reserve_seconds=float(run_budget.get("post_pricing_reserve_seconds", 0.0)),
        )

        step = monotonic_seconds()
        pricing = solve_pricing_lp(
            model,
            config,
            primary,
            time_limit_seconds=deadline.solver_limit(
                "pricing solve",
                reserve_seconds=float(run_budget.get("post_pricing_reserve_seconds", 0.0)),
            ),
        )
        timings["pricing_lp"] = monotonic_seconds() - step
        deadline.check("result serialization")

        step = monotonic_seconds()
        pricing_path = require_local_path(result_directory / "pricing-primal.npz", "pricing primal")
        pricing_hash = write_npz(pricing_path, pricing_arrays(model, pricing))
        result_path = require_local_path(result_directory / "result.json", "official result")
        preliminary_peak = monitor.peak_rss_bytes
        checkpoint_hash = sha256_file(checkpoint_path)
        payload = build_result_payload(
            model,
            config,
            config_hash,
            commit,
            primary,
            pricing,
            _artifact(root, primary_path, primary_hash),
            _artifact(root, checkpoint_path, checkpoint_hash),
            _artifact(root, pricing_path, pricing_hash),
            timings,
            preliminary_peak,
        )
        save_result(result_path, payload)
        timings["initial_serialization"] = monotonic_seconds() - step

        step = monotonic_seconds()
        checker = verify_result(root, config, result_path, config_path)
        timings["independent_verification"] = monotonic_seconds() - step
        timings["end_to_end"] = monotonic_seconds() - total_start
        deadline.check("final result serialization")
        peak = monitor.stop()
        payload = load_result(result_path)
        payload["timings_seconds"] = timings
        payload["peak_rss_bytes"] = peak
        payload["official_run"] = {
            "status": "success" if checker["status"] == "pass" else "failed_acceptance",
            "started_utc": lock["started_utc"],
            "completed_utc": _utc_now(),
            "cold_start": True,
            "repeat_count": 1,
        }
        save_result(result_path, payload)
        lock.update(
            {
                "status": payload["official_run"]["status"],
                "completed_utc": payload["official_run"]["completed_utc"],
                "result": result_path.relative_to(root).as_posix(),
                "checker": checker["status"],
            }
        )
        write_json(lock_path, lock)
        deadline.check("completed run")
        if checker["status"] != "pass":
            raise RuntimeError(f"Official run failed independent acceptance: {checker}")
        return payload
    except BaseException as exc:
        peak = monitor.stop()
        if isinstance(exc, RunDeadlineExceeded):
            failure_status = "timed_out"
        else:
            failure_status = (
                lock["status"] if lock.get("status") == "failed_acceptance" else "failed"
            )
        lock.update(
            {
                "status": failure_status,
                "completed_utc": _utc_now(),
                "peak_rss_bytes": peak,
                "elapsed_seconds": monotonic_seconds() - total_start,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        if isinstance(exc, RunDeadlineExceeded):
            lock["deadline_details"] = exc.details
            if result_path is not None and result_path.exists():
                partial = load_result(result_path)
                if "official_run" in partial:
                    partial["official_run"]["status"] = "timed_out"
                    partial["official_run"]["completed_utc"] = lock["completed_utc"]
                    save_result(result_path, partial)
        write_json(lock_path, lock)
        raise


def resume_saved_primary(root: Path, config_path: Path, config: dict) -> dict[str, Any]:
    """Resume verification and pricing after a retained primary; never rerun the MILP."""
    root = require_local_path(root, "repository")
    config_path = require_local_path(config_path, "configuration")
    result_directory = resolve_from(root, config["result_directory"], "result directory")
    lock_path = resolve_from(root, config["run_lock"], "official-run lock")
    checkpoint_path = require_local_path(
        result_directory / "primary-checkpoint.json", "primary checkpoint"
    )
    result_path = require_local_path(result_directory / "result.json", "official result")
    if not lock_path.exists() or not checkpoint_path.exists():
        raise RuntimeError("A failed run lock and saved primary checkpoint are required to resume")
    if result_path.exists():
        raise RuntimeError(f"Refusing to replace existing official result at {result_path}")
    if not git_is_clean(root):
        raise RuntimeError("Post-processing resume requires a clean, frozen Git worktree")

    lock = load_result(lock_path)
    checkpoint = load_result(checkpoint_path)
    if lock.get("status") not in {"failed", "failed_acceptance"}:
        raise RuntimeError(f"Run lock status is not resumable: {lock.get('status')}")
    config_hash = sha256_file(config_path)
    if checkpoint["reproducibility"]["config_sha256"] != config_hash:
        raise RuntimeError("Saved primary configuration hash does not match the registered file")
    if checkpoint["reproducibility"]["git_commit"] != lock.get("git_commit"):
        raise RuntimeError("Saved primary solve commit does not match the run lock")

    postprocess_commit = git_commit(root)
    original_elapsed = float(lock.get("elapsed_seconds", 0.0))
    timings = dict(checkpoint["timings_seconds"])
    monitor = PeakMemoryMonitor()
    monitor.start()
    resume_start = monotonic_seconds()
    lock.update(
        {
            "status": "resuming_postprocess",
            "postprocess_git_commit": postprocess_commit,
            "resume_started_utc": _utc_now(),
            "primary_rerun": False,
        }
    )
    write_json(lock_path, lock)
    try:
        step = monotonic_seconds()
        case = read_case(root, config)
        timings["resume_source_ingest"] = monotonic_seconds() - step

        step = monotonic_seconds()
        model = build_extensive_model(case, config)
        timings["resume_model_build"] = monotonic_seconds() - step

        step = monotonic_seconds()
        primary_checker = verify_primary_checkpoint(root, config, checkpoint_path, config_path)
        timings["independent_primary_verification"] = monotonic_seconds() - step
        if primary_checker["status"] != "pass":
            lock["status"] = "failed_acceptance"
            lock["primary_checker"] = primary_checker["status"]
            write_json(lock_path, lock)
            raise RuntimeError(f"Primary solution failed independent acceptance: {primary_checker}")

        checkpoint = load_result(checkpoint_path)
        checkpoint["timings_seconds"] = dict(timings)
        checkpoint["peak_rss_bytes"] = max(
            int(checkpoint.get("peak_rss_bytes", 0)), monitor.peak_rss_bytes
        )
        save_result(checkpoint_path, checkpoint)
        primary_path = require_local_path(root / checkpoint["artifact"]["path"], "primary primal")
        primary_arrays = read_npz(primary_path)
        primary = primary_result_from_checkpoint(model, checkpoint, primary_arrays)
        lock.update({"status": "primary_verified", "primary_checker": "pass"})
        write_json(lock_path, lock)

        step = monotonic_seconds()
        pricing = solve_pricing_lp(model, config, primary)
        timings["pricing_lp"] = monotonic_seconds() - step

        step = monotonic_seconds()
        pricing_path = require_local_path(result_directory / "pricing-primal.npz", "pricing primal")
        pricing_hash = write_npz(pricing_path, pricing_arrays(model, pricing))
        checkpoint_hash = sha256_file(checkpoint_path)
        payload = build_result_payload(
            model,
            config,
            config_hash,
            str(checkpoint["reproducibility"]["git_commit"]),
            primary,
            pricing,
            _artifact(root, primary_path, str(checkpoint["artifact"]["sha256"])),
            _artifact(root, checkpoint_path, checkpoint_hash),
            _artifact(root, pricing_path, pricing_hash),
            timings,
            max(int(checkpoint.get("peak_rss_bytes", 0)), monitor.peak_rss_bytes),
            postprocess_commit=postprocess_commit,
        )
        save_result(result_path, payload)
        timings["resume_serialization"] = monotonic_seconds() - step

        step = monotonic_seconds()
        checker = verify_result(root, config, result_path, config_path)
        timings["independent_verification"] = monotonic_seconds() - step
        resume_elapsed = monotonic_seconds() - resume_start
        timings["resume_active"] = resume_elapsed
        timings["end_to_end_active"] = original_elapsed + resume_elapsed
        peak = max(int(checkpoint.get("peak_rss_bytes", 0)), monitor.stop())
        payload = load_result(result_path)
        payload["timings_seconds"] = timings
        payload["peak_rss_bytes"] = peak
        payload["official_run"] = {
            "status": "success" if checker["status"] == "pass" else "failed_acceptance",
            "started_utc": lock["started_utc"],
            "completed_utc": _utc_now(),
            "cold_start": True,
            "repeat_count": 1,
            "resumed_from_saved_primary": True,
            "primary_rerun": False,
        }
        save_result(result_path, payload)
        lock.update(
            {
                "status": payload["official_run"]["status"],
                "completed_utc": payload["official_run"]["completed_utc"],
                "result": result_path.relative_to(root).as_posix(),
                "checker": checker["status"],
                "elapsed_seconds": timings["end_to_end_active"],
            }
        )
        write_json(lock_path, lock)
        if checker["status"] != "pass":
            raise RuntimeError(f"Official run failed independent acceptance: {checker}")
        return payload
    except BaseException as exc:
        peak = max(int(checkpoint.get("peak_rss_bytes", 0)), monitor.stop())
        failure_status = lock["status"] if lock.get("status") == "failed_acceptance" else "failed"
        lock.update(
            {
                "status": failure_status,
                "completed_utc": _utc_now(),
                "peak_rss_bytes": peak,
                "elapsed_seconds": original_elapsed + monotonic_seconds() - resume_start,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        write_json(lock_path, lock)
        raise


def repair_inverted_price_sign(root: Path, config_path: Path, config: dict) -> dict[str, Any]:
    """Repair the one known v2 sign-reporting defect without invoking an optimizer."""
    root = require_local_path(root, "repository")
    config_path = require_local_path(config_path, "configuration")
    result_directory = resolve_from(root, config["result_directory"], "result directory")
    lock_path = resolve_from(root, config["run_lock"], "official-run lock")
    result_path = require_local_path(result_directory / "result.json", "official result")
    if not result_path.exists() or not lock_path.exists():
        raise RuntimeError("An existing official result and run lock are required")
    if not git_is_clean(root):
        raise RuntimeError("Price-reporting repair requires a clean, frozen Git worktree")

    payload = load_result(result_path)
    lock = load_result(lock_path)
    legacy_postprocess_commit = "b80148fa028b88e4f372f76e42efd88e659fdee6"
    if (
        payload.get("reproducibility", {}).get("postprocess_git_commit")
        != legacy_postprocess_commit
    ):
        raise RuntimeError(
            "Result was not produced by the one known sign-inverted reporting commit"
        )
    if "dual_sign_convention" in payload.get("pricing", {}):
        raise RuntimeError(
            "Price dual sign convention is already present; refusing a second repair"
        )
    if sha256_file(config_path) != payload["reproducibility"]["config_sha256"]:
        raise RuntimeError("Result configuration hash does not match the registered file")

    case = read_case(root, config)
    prices = payload["pricing"]["base_usd_per_mwh"]
    if len(prices) != len(case.buses):
        raise RuntimeError("Saved price count does not match the registered buses")
    corrected_prices = -np.asarray([float(record["price"]) for record in prices])

    pricing_record = payload["artifacts"]["pricing_primal"]
    pricing_path = require_local_path(root / pricing_record["path"], "pricing primal")
    if sha256_file(pricing_path).casefold() != str(pricing_record["sha256"]).casefold():
        raise RuntimeError("Pricing artifact hash does not match the accepted result")
    arrays = read_npz(pricing_path)
    if "base_balance_duals" in arrays:
        raise RuntimeError(
            "Pricing artifact already contains duals; refusing legacy reconstruction"
        )
    legacy_directory = require_local_path(
        result_directory / "legacy-sign-inverted", "legacy price-reporting evidence"
    )
    if legacy_directory.exists():
        raise RuntimeError(
            "Legacy price-reporting evidence already exists; refusing a second repair"
        )
    legacy_directory.mkdir(parents=True)
    legacy_result_path = require_local_path(
        legacy_directory / "result.json", "legacy result evidence"
    )
    legacy_pricing_path = require_local_path(
        legacy_directory / "pricing-primal.npz", "legacy pricing evidence"
    )
    shutil.copy2(result_path, legacy_result_path)
    shutil.copy2(pricing_path, legacy_pricing_path)
    arrays["base_balance_duals"] = corrected_prices * case.base_mva * case.delta_hours
    pricing_hash = write_npz(pricing_path, arrays)

    for record, price in zip(prices, corrected_prices, strict=True):
        record["price"] = float(price)
    payload["pricing"]["dual_sign_convention"] = (
        "HiGHS base nodal-balance row_dual divided by baseMVA and interval hours; "
        "generation has coefficient +1."
    )
    payload["pricing"]["dual_provenance"] = (
        "Reconstructed exactly from the legacy sign-inverted reported values; no LP rerun."
    )
    payload["artifacts"]["pricing_primal"] = _artifact(root, pricing_path, pricing_hash)
    payload["legacy_price_reporting_artifacts"] = {
        "result": _artifact(root, legacy_result_path, sha256_file(legacy_result_path)),
        "pricing_primal": _artifact(root, legacy_pricing_path, sha256_file(legacy_pricing_path)),
    }
    repair_commit = git_commit(root)
    payload["reproducibility"]["price_reporting_git_commit"] = repair_commit
    payload["official_run"]["price_reporting_corrected_without_resolve"] = True
    save_result(result_path, payload)

    checker = verify_result(root, config, result_path, config_path)
    if checker["status"] != "pass":
        lock.update(
            {
                "status": "failed_acceptance",
                "checker": checker["status"],
                "price_reporting_git_commit": repair_commit,
            }
        )
        write_json(lock_path, lock)
        raise RuntimeError(f"Price-reporting repair failed independent acceptance: {checker}")
    lock.update(
        {
            "status": "success",
            "checker": "pass",
            "price_reporting_git_commit": repair_commit,
            "price_reporting_corrected_without_resolve": True,
        }
    )
    write_json(lock_path, lock)
    return load_result(result_path)
