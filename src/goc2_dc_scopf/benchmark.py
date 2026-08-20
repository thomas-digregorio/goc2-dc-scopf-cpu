from __future__ import annotations

import datetime as dt
import traceback
from pathlib import Path
from typing import Any

from .checker import verify_result
from .highs import solve_lexicographic, solve_pricing_lp
from .model import build_extensive_model
from .monitor import PeakMemoryMonitor, monotonic_seconds
from .paths import require_local_path, resolve_from, sha256_file, write_json
from .results import (
    build_result_payload,
    git_commit,
    git_is_clean,
    load_result,
    physical_arrays,
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
    total_start = monotonic_seconds()
    timings: dict[str, float] = {}
    try:
        step = monotonic_seconds()
        case = read_case(root, config)
        timings["source_ingest"] = monotonic_seconds() - step

        step = monotonic_seconds()
        model = build_extensive_model(case, config)
        timings["model_build"] = monotonic_seconds() - step

        step = monotonic_seconds()
        milp = solve_lexicographic(model, config)
        timings["milp_total"] = monotonic_seconds() - step
        timings["primary_milp"] = milp.primary.wall_seconds
        timings["secondary_milp"] = milp.secondary.wall_seconds

        step = monotonic_seconds()
        pricing = solve_pricing_lp(model, config, milp.column_values)
        timings["pricing_lp"] = monotonic_seconds() - step

        step = monotonic_seconds()
        milp_path = require_local_path(result_directory / "milp-primal.npz", "MILP primal")
        pricing_path = require_local_path(result_directory / "pricing-primal.npz", "pricing primal")
        milp_hash = write_npz(milp_path, physical_arrays(model, milp.column_values))
        pricing_hash = write_npz(pricing_path, physical_arrays(model, pricing.column_values))
        result_path = require_local_path(result_directory / "result.json", "official result")
        preliminary_peak = monitor.peak_rss_bytes
        payload = build_result_payload(
            model,
            config,
            config_hash,
            commit,
            milp,
            pricing,
            _artifact(root, milp_path, milp_hash),
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
        if checker["status"] != "pass":
            raise RuntimeError(f"Official run failed independent acceptance: {checker}")
        return payload
    except BaseException as exc:
        peak = monitor.stop()
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
        write_json(lock_path, lock)
        raise
