from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import highspy
import numpy as np
import psutil

from .highs import PricingResult, PrimaryResult, StageSummary
from .model import CanonicalModel
from .paths import require_local_path, sha256_file, write_json


def _identity(key: tuple[int, str]) -> dict[str, int | str]:
    return {"bus": key[0], "id": key[1]}


def _branch_identity(branch: Any) -> dict[str, int | str]:
    return {
        "from_bus": branch.key[0],
        "to_bus": branch.key[1],
        "circuit": branch.key[2],
        "kind": branch.kind,
        "source_reactance_pu": branch.reactance_pu,
        "impedance_correction_factor": branch.impedance_correction_factor,
        "dc_reactance_pu": branch.dc_reactance_pu,
        "tap_magnitude": branch.tap_magnitude,
        "phase_shift_rad": branch.phase_shift_rad,
    }


def physical_arrays(model: CanonicalModel, values: np.ndarray) -> dict[str, np.ndarray]:
    ns = len(model.layout.states)
    nb = len(model.case.buses)
    ng = len(model.case.generators)
    nl = len(model.case.loads)
    ne = len(model.case.branches)
    arrays = {
        "theta_rad": np.empty((ns, nb), dtype=np.float64),
        "generation_pu": np.empty((ns, ng), dtype=np.float64),
        "load_pu": np.empty((ns, nl), dtype=np.float64),
        "flow_pu": np.empty((ns, ne), dtype=np.float64),
        "commitment": np.empty((ns, ng), dtype=np.float64),
        "startup": np.empty((ns, ng), dtype=np.float64),
        "shutdown": np.empty((ns, ng), dtype=np.float64),
    }
    for state in model.layout.states:
        k = state.state_index
        arrays["theta_rad"][k] = values[state.theta_start : state.pg_start]
        arrays["generation_pu"][k] = values[state.pg_start : state.load_start]
        arrays["load_pu"][k] = values[state.load_start : state.flow_start]
        arrays["flow_pu"][k] = values[state.flow_start : state.u_start]
        arrays["commitment"][k] = values[state.u_start : state.startup_start]
        arrays["startup"][k] = values[state.startup_start : state.shutdown_start]
        arrays["shutdown"][k] = values[state.shutdown_start : state.stop]
    return arrays


def base_prices_from_duals(
    base_balance_duals: np.ndarray, base_mva: float, interval_hours: float
) -> np.ndarray:
    """Convert HiGHS equality-row duals to $/MWh for +generation nodal balances."""
    return np.asarray(base_balance_duals, dtype=np.float64) / (base_mva * interval_hours)


def pricing_arrays(model: CanonicalModel, pricing: PricingResult) -> dict[str, np.ndarray]:
    arrays = physical_arrays(model, pricing.column_values)
    arrays["base_balance_duals"] = np.asarray(pricing.base_balance_duals, dtype=np.float64)
    return arrays


def write_npz(path: Path, arrays: dict[str, np.ndarray]) -> str:
    path = require_local_path(path, "result array")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = require_local_path(path.with_suffix(path.suffix + ".tmp"), "temporary result array")
    with temporary.open("wb") as handle:
        np.savez_compressed(handle, **arrays)
    temporary.replace(path)
    return sha256_file(path)


def read_npz(path: Path) -> dict[str, np.ndarray]:
    path = require_local_path(path, "result array")
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def primary_result_from_checkpoint(
    model: CanonicalModel,
    checkpoint: dict[str, Any],
    arrays: dict[str, np.ndarray],
) -> PrimaryResult:
    """Rebuild state columns from a saved primal without reconstructing cost-segment columns."""
    values = np.zeros(model.layout.num_columns, dtype=np.float64)
    for state in model.layout.states:
        k = state.state_index
        values[state.theta_start : state.pg_start] = arrays["theta_rad"][k]
        values[state.pg_start : state.load_start] = arrays["generation_pu"][k]
        values[state.load_start : state.flow_start] = arrays["load_pu"][k]
        values[state.flow_start : state.u_start] = arrays["flow_pu"][k]
        values[state.u_start : state.startup_start] = arrays["commitment"][k]
        values[state.startup_start : state.shutdown_start] = arrays["startup"][k]
        values[state.shutdown_start : state.stop] = arrays["shutdown"][k]
    stage = StageSummary(**checkpoint["solver"]["primary"])
    return PrimaryResult(stage, float(checkpoint["objectives"]["primary_usd"]), values)


def git_commit(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def git_is_clean(root: Path) -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    )
    return not completed.stdout.strip()


def build_primary_checkpoint(
    model: CanonicalModel,
    config: dict,
    config_sha256: str,
    commit: str,
    primary: PrimaryResult,
    primary_artifact: dict[str, Any],
    timings: dict[str, float],
    peak_rss_bytes: int,
) -> dict[str, Any]:
    case = model.case
    return {
        "checkpoint_version": 1,
        "status": "primary_solved",
        "profile": case.profile,
        "qualification": (
            "Derived lossless-DC benchmark; not an official GO score or PJM/CAISO market "
            "or reliability result."
        ),
        "source": {
            "scenario": case.scenario,
            "directory": case.source_directory,
            "hashes": case.source_hashes,
            "parser_commit": case.parser_commit,
            "untranslated": list(case.untranslated),
        },
        "reproducibility": {"git_commit": commit, "config_sha256": config_sha256},
        "run": {"cold_start": True, "initial_solution": "none"},
        "solver": {
            "name": "HiGHS",
            "version": highspy.Highs().version(),
            "configuration": config["solver"],
            "primary": asdict(primary.primary),
        },
        "objectives": {
            "primary_usd": primary.objective,
            "primary_dual_bound_usd": primary.primary.dual_bound,
            "primary_mip_gap": primary.primary.mip_gap,
        },
        "timings_seconds": dict(timings),
        "peak_rss_bytes": int(peak_rss_bytes),
        "model": model.statistics(),
        "artifact": primary_artifact,
        "checker": {"status": "pending"},
    }


def build_result_payload(
    model: CanonicalModel,
    config: dict,
    config_sha256: str,
    commit: str,
    primary: PrimaryResult,
    pricing: PricingResult,
    primary_artifact: dict[str, Any],
    primary_checkpoint_artifact: dict[str, Any],
    pricing_artifact: dict[str, Any],
    timings: dict[str, float],
    peak_rss_bytes: int,
    postprocess_commit: str | None = None,
) -> dict[str, Any]:
    case = model.case
    primal = physical_arrays(model, primary.column_values)
    base_mva = case.base_mva
    commitment = np.rint(primal["commitment"]).astype(np.int8)
    dispatch_mw = primal["generation_pu"] * base_mva
    load_mw = primal["load_pu"] * base_mva
    base_u = commitment[0]
    prior_u = np.asarray([g.prior_on for g in case.generators], dtype=np.int8)
    generator_order = [_identity(g.key) for g in case.generators]
    branch_order = [_branch_identity(b) for b in case.branches]
    bus_order = [b.number for b in case.buses]

    contingencies: list[dict[str, Any]] = []
    fast_starts: list[dict[str, Any]] = []
    for c_index, contingency in enumerate(case.contingencies):
        state = c_index + 1
        current_u = commitment[state]
        changes = []
        for g in np.flatnonzero(current_u != base_u):
            if contingency.generator_index == int(g):
                change = "forced_outage"
            else:
                change = "start" if current_u[g] > base_u[g] else "shutdown"
            record = {**_identity(case.generators[int(g)].key), "change": change}
            changes.append(record)
            if change == "start":
                fast_starts.append({"contingency": contingency.label, **record})
        contingencies.append(
            {
                "source_index": contingency.source_index,
                "label": contingency.label,
                "kind": contingency.kind,
                "outaged_branch_index": contingency.branch_index,
                "outaged_generator_index": contingency.generator_index,
                "commitment": current_u.tolist(),
                "dispatch_mw": dispatch_mw[state].tolist(),
                "load_mw": load_mw[state].tolist(),
                "commitment_changes": changes,
            }
        )

    binding_base: list[dict[str, Any]] = []
    binding_contingency: list[dict[str, Any]] = []
    binding_tolerance = float(config["numerics"]["security_violation_tolerance_pu"])
    for branch_index, branch in enumerate(case.branches):
        flow = primal["flow_pu"][0, branch_index]
        if branch.normal_limit_pu - abs(flow) <= binding_tolerance:
            binding_base.append(
                {
                    "type": "thermal",
                    "branch_index": branch_index,
                    "side": "upper" if flow >= 0 else "lower",
                    "flow_mw": float(flow * base_mva),
                    "limit_mw": float(branch.normal_limit_pu * base_mva),
                }
            )
    for c_index, contingency in enumerate(case.contingencies):
        state = c_index + 1
        for branch_index, branch in enumerate(case.branches):
            if contingency.branch_index == branch_index:
                continue
            flow = primal["flow_pu"][state, branch_index]
            if branch.emergency_limit_pu - abs(flow) <= binding_tolerance:
                binding_contingency.append(
                    {
                        "type": "thermal",
                        "contingency": contingency.label,
                        "branch_index": branch_index,
                        "side": "upper" if flow >= 0 else "lower",
                        "flow_mw": float(flow * base_mva),
                        "limit_mw": float(branch.emergency_limit_pu * base_mva),
                    }
                )

    prices = base_prices_from_duals(pricing.base_balance_duals, base_mva, case.delta_hours)
    return {
        "result_version": 2,
        "profile": case.profile,
        "security_claim": "Secure in the modeled GO-style corrective state after the supplied contingency-response interval.",
        "qualification": "Derived lossless-DC benchmark; not an official GO score or PJM/CAISO market or reliability result.",
        "source": {
            "scenario": case.scenario,
            "directory": case.source_directory,
            "hashes": case.source_hashes,
            "parser_commit": case.parser_commit,
            "untranslated": list(case.untranslated),
        },
        "reproducibility": {
            "git_commit": commit,
            "postprocess_git_commit": postprocess_commit or commit,
            "config_sha256": config_sha256,
        },
        "solver": {
            "name": "HiGHS",
            "version": highspy.Highs().version(),
            "configuration": config["solver"],
            "primary": asdict(primary.primary),
            "pricing": asdict(pricing.summary),
        },
        "objectives": {
            "primary_usd": primary.objective,
            "primary_dual_bound_usd": primary.primary.dual_bound,
            "primary_mip_gap": primary.primary.mip_gap,
            "fixed_commitment_pricing_lp_usd": pricing.objective,
        },
        "timings_seconds": timings,
        "peak_rss_bytes": int(peak_rss_bytes),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "total_memory_bytes": psutil.virtual_memory().total,
        },
        "model": model.statistics(),
        "orders": {
            "bus": bus_order,
            "generator": generator_order,
            "branch": branch_order,
        },
        "prior": {
            "commitment": prior_u.tolist(),
            "dispatch_mw": [g.prior_p_pu * base_mva for g in case.generators],
        },
        "base": {
            "commitment": base_u.tolist(),
            "dispatch_mw": dispatch_mw[0].tolist(),
            "load_mw": load_mw[0].tolist(),
        },
        "contingencies": contingencies,
        "contingency_fast_starts": fast_starts,
        "pricing": {
            "description": "Fixed-commitment, lossless-DC, security-constrained nodal prices.",
            "dual_sign_convention": (
                "HiGHS base nodal-balance row_dual divided by baseMVA and interval hours; "
                "generation has coefficient +1."
            ),
            "base_usd_per_mwh": [
                {"bus": bus.number, "price": float(prices[i])} for i, bus in enumerate(case.buses)
            ],
            "contingency_prices_retained": False,
        },
        "binding_constraints": {
            "base": binding_base,
            "contingency": binding_contingency,
        },
        "artifacts": {
            "primary_primal": primary_artifact,
            "primary_checkpoint": primary_checkpoint_artifact,
            "pricing_primal": pricing_artifact,
        },
        "checker": {"status": "pending"},
    }


def load_result(path: Path) -> dict[str, Any]:
    path = require_local_path(path, "result JSON")
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError("Result JSON must contain an object")
    return value


def save_result(path: Path, payload: dict[str, Any]) -> None:
    write_json(path, payload)
