from __future__ import annotations

import os
import time
from dataclasses import replace
from typing import Any

import highspy
import numpy as np

from .checker import _check_physical
from .deadline import RunDeadline, RunDeadlineExceeded
from .highs import (
    PrimaryResult,
    StageSummary,
    _configure,
    _highs_model,
    _pass_model,
    _require_solution,
    _stage_summary,
    solve_primary_milp,
)
from .model import CanonicalModel, build_extensive_model
from .results import physical_arrays
from .source import CaseData


def factors(config: dict[str, Any]) -> dict[str, bool]:
    settings = config.get("ablation", {})
    return {
        "decomposition": bool(settings.get("decomposition", False)),
        "internal_incumbent": bool(settings.get("internal_incumbent", False)),
        "strong_valid_cuts": bool(settings.get("strong_valid_cuts", False)),
        "solver_tuning": bool(settings.get("solver_tuning", False)),
    }


def validate_cell(config: dict[str, Any], *, check_environment: bool = False) -> None:
    settings = config.get("ablation")
    if settings is None:
        return
    cell = str(settings["cell"])
    expected = "".join("1" if enabled else "0" for enabled in factors(config).values())
    if cell != expected:
        raise ValueError(f"Ablation cell {cell} does not match enabled factors {expected}")
    if bool(settings.get("solver_tuning", False)):
        expected_options = {
            "parallel": "on",
            "simplex_strategy": 3,
            "simplex_max_concurrency": 8,
        }
        actual = config["solver"].get("advanced_options", {})
        if actual != expected_options or int(config["solver"].get("threads", 0)) != 24:
            raise ValueError("Solver-tuning cells must use the frozen PAMI/24-thread profile")
        if settings.get("linear_algebra_threads") != 1:
            raise ValueError("Solver-tuning cells must register one BLAS/OpenMP thread")
        if check_environment:
            for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
                if os.environ.get(name) != "1":
                    raise ValueError(f"Solver-tuning cell requires {name}=1 before Python starts")
    else:
        if settings.get("linear_algebra_threads") is not None:
            raise ValueError("Non-tuning cells must not register a BLAS/OpenMP override")
        if config["solver"].get("advanced_options") or int(
            config["solver"].get("threads", 0)
        ) != 0:
            raise ValueError("Non-tuning cells must retain the default HiGHS thread/options profile")


def _subset_case(case: CaseData, contingency_indices: tuple[int, ...]) -> CaseData:
    return replace(
        case,
        contingencies=tuple(case.contingencies[index] for index in contingency_indices),
    )


def _project_full_start(
    full_model: CanonicalModel,
    subset_model: CanonicalModel,
    contingency_indices: tuple[int, ...],
    full_values: np.ndarray,
) -> np.ndarray:
    projected = np.zeros(subset_model.layout.num_columns, dtype=np.float64)
    full_base = full_model.layout.states[0]
    subset_base = subset_model.layout.states[0]
    projected[subset_base.offset : subset_base.stop] = full_values[
        full_base.offset : full_base.stop
    ]
    for subset_state_index, original_index in enumerate(contingency_indices, start=1):
        subset_state = subset_model.layout.states[subset_state_index]
        full_state = full_model.layout.states[original_index + 1]
        projected[subset_state.offset : subset_state.stop] = full_values[
            full_state.offset : full_state.stop
        ]
    for subset_columns, full_columns in zip(
        subset_model.layout.generator_segment_columns,
        full_model.layout.generator_segment_columns,
        strict=True,
    ):
        projected[np.asarray(subset_columns, dtype=np.int64)] = full_values[
            np.asarray(full_columns, dtype=np.int64)
        ]
    for subset_columns, full_columns in zip(
        subset_model.layout.load_segment_columns,
        full_model.layout.load_segment_columns,
        strict=True,
    ):
        projected[np.asarray(subset_columns, dtype=np.int64)] = full_values[
            np.asarray(full_columns, dtype=np.int64)
        ]
    return projected


def _assemble_full_values(
    full_model: CanonicalModel,
    master_model: CanonicalModel,
    master_values: np.ndarray,
    contingency_blocks: dict[int, np.ndarray],
) -> np.ndarray:
    values = np.zeros(full_model.layout.num_columns, dtype=np.float64)
    full_base = full_model.layout.states[0]
    master_base = master_model.layout.states[0]
    values[full_base.offset : full_base.stop] = master_values[
        master_base.offset : master_base.stop
    ]
    for contingency_index, block in contingency_blocks.items():
        state = full_model.layout.states[contingency_index + 1]
        if block.shape != (state.stop - state.offset,):
            raise ValueError("Contingency block has the wrong canonical width")
        values[state.offset : state.stop] = block
    for full_columns, master_columns in zip(
        full_model.layout.generator_segment_columns,
        master_model.layout.generator_segment_columns,
        strict=True,
    ):
        values[np.asarray(full_columns, dtype=np.int64)] = master_values[
            np.asarray(master_columns, dtype=np.int64)
        ]
    for full_columns, master_columns in zip(
        full_model.layout.load_segment_columns,
        master_model.layout.load_segment_columns,
        strict=True,
    ):
        values[np.asarray(full_columns, dtype=np.int64)] = master_values[
            np.asarray(master_columns, dtype=np.int64)
        ]
    return values


def _screen_contingency(
    case: CaseData,
    contingency_index: int,
    base_values: np.ndarray,
    config: dict[str, Any],
    *,
    time_limit_seconds: float,
) -> tuple[str, np.ndarray | None, StageSummary]:
    subcase = _subset_case(case, (contingency_index,))
    model = build_extensive_model(subcase, config)
    base = model.layout.states[0]
    if base_values.shape != (base.stop - base.offset,):
        raise ValueError("Screening base block has the wrong canonical width")
    column_lower = model.column_lower.copy()
    column_upper = model.column_upper.copy()
    column_lower[base.offset : base.stop] = base_values
    column_upper[base.offset : base.stop] = base_values
    zero_cost = np.zeros(model.layout.num_columns, dtype=np.float64)
    screen_solver = dict(config["solver"])
    screen_solver["console_logging"] = False
    screen_solver["mip_relative_gap"] = 0.0
    screen_solver["mip_absolute_gap"] = 0.0
    highs = highspy.Highs()
    _configure(
        highs,
        screen_solver,
        mip=True,
        time_limit_override_seconds=time_limit_seconds,
    )
    _pass_model(
        highs,
        _highs_model(
            model,
            zero_cost,
            relax_integrality=False,
            column_lower=column_lower,
            column_upper=column_upper,
        ),
    )
    started = time.perf_counter()
    status = highs.run()
    summary = _stage_summary(
        f"contingency_{contingency_index}_feasibility",
        highs,
        status,
        time.perf_counter() - started,
    )
    model_status = highs.getModelStatus()
    if model_status == highspy.HighsModelStatus.kTimeLimit:
        raise RunDeadlineExceeded(
            f"Contingency {contingency_index} reached its registered screen limit"
        )
    if model_status == highspy.HighsModelStatus.kInfeasible:
        return "infeasible", None, summary
    if model_status != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(
            f"Contingency {contingency_index} screen was not certified: {summary.model_status}"
        )
    values = _require_solution(summary, highs)
    state = model.layout.states[1]
    return "feasible", values[state.offset : state.stop].copy(), summary


def _screen_all(
    case: CaseData,
    base_values: np.ndarray,
    config: dict[str, Any],
    deadline: RunDeadline,
    *,
    reserve_seconds: float,
    local_deadline: RunDeadline | None = None,
) -> tuple[list[int], dict[int, np.ndarray], dict[str, float | int]]:
    infeasible: list[int] = []
    blocks: dict[int, np.ndarray] = {}
    wall_sum = 0.0
    node_sum = 0
    iteration_sum = 0
    for contingency_index in range(len(case.contingencies)):
        global_limit = deadline.solver_limit(
            f"contingency screen {contingency_index}", reserve_seconds=reserve_seconds
        )
        assert global_limit is not None
        limit = global_limit
        if local_deadline is not None:
            local_remaining = local_deadline.remaining_seconds()
            if local_remaining <= 0.0:
                raise RunDeadlineExceeded("Internal incumbent construction budget exhausted")
            limit = min(limit, local_remaining)
        status, block, summary = _screen_contingency(
            case,
            contingency_index,
            base_values,
            config,
            time_limit_seconds=limit,
        )
        wall_sum += summary.wall_seconds
        node_sum += max(0, summary.node_count)
        iteration_sum += max(0, summary.simplex_iterations)
        if status == "infeasible":
            infeasible.append(contingency_index)
        else:
            assert block is not None
            blocks[contingency_index] = block
    return infeasible, blocks, {
        "screen_wall_seconds_sum": wall_sum,
        "screen_nodes_sum": node_sum,
        "screen_simplex_iterations_sum": iteration_sum,
        "screens": len(case.contingencies),
    }


def _solve_scenario_master(
    case: CaseData,
    full_model: CanonicalModel,
    config: dict[str, Any],
    deadline: RunDeadline,
    *,
    reserve_seconds: float,
    active: tuple[int, ...],
    full_start: np.ndarray | None,
    fixed_prior_commitment: bool,
    local_deadline: RunDeadline | None,
) -> tuple[CanonicalModel, PrimaryResult]:
    master_case = _subset_case(case, active)
    master = build_extensive_model(master_case, config)
    if fixed_prior_commitment:
        base = master.layout.states[0]
        prior = np.asarray([g.prior_on for g in case.generators], dtype=np.float64)
        master.column_lower[base.u_start : base.startup_start] = prior
        master.column_upper[base.u_start : base.startup_start] = prior
    limit = deadline.solver_limit("scenario master", reserve_seconds=reserve_seconds)
    assert limit is not None
    if local_deadline is not None:
        local_remaining = local_deadline.remaining_seconds()
        if local_remaining <= 0.0:
            raise RunDeadlineExceeded("Internal incumbent construction budget exhausted")
        limit = min(limit, local_remaining)
    projected = (
        None
        if full_start is None
        else _project_full_start(full_model, master, active, full_start)
    )
    result = solve_primary_milp(
        master,
        config,
        time_limit_seconds=limit,
        initial_solution=projected,
    )
    return master, result


def _scenario_generation(
    case: CaseData,
    full_model: CanonicalModel,
    config: dict[str, Any],
    deadline: RunDeadline,
    *,
    reserve_seconds: float,
    initial_full_start: np.ndarray | None,
    fixed_prior_commitment: bool,
    local_deadline: RunDeadline | None = None,
) -> tuple[np.ndarray, StageSummary, dict[str, object]]:
    active: tuple[int, ...] = ()
    rounds: list[dict[str, object]] = []
    master_wall = 0.0
    screen_wall = 0.0
    total_nodes = 0
    total_iterations = 0
    settings = config.get("ablation", {})
    max_rounds = int(settings.get("max_decomposition_rounds", 32))

    for round_index in range(1, max_rounds + 1):
        master, master_result = _solve_scenario_master(
            case,
            full_model,
            config,
            deadline,
            reserve_seconds=reserve_seconds,
            active=active,
            full_start=initial_full_start,
            fixed_prior_commitment=fixed_prior_commitment,
            local_deadline=local_deadline,
        )
        master_wall += master_result.primary.wall_seconds
        total_nodes += max(0, master_result.primary.node_count)
        total_iterations += max(0, master_result.primary.simplex_iterations)
        base = master.layout.states[0]
        base_values = master_result.column_values[base.offset : base.stop].copy()
        infeasible, blocks, screen = _screen_all(
            case,
            base_values,
            config,
            deadline,
            reserve_seconds=reserve_seconds,
            local_deadline=local_deadline,
        )
        screen_wall += float(screen["screen_wall_seconds_sum"])
        total_nodes += int(screen["screen_nodes_sum"])
        total_iterations += int(screen["screen_simplex_iterations_sum"])
        newly_added = tuple(index for index in infeasible if index not in active)
        rounds.append(
            {
                "round": round_index,
                "active_contingencies": len(active),
                "master_objective": master_result.objective,
                "master_dual_bound": master_result.primary.dual_bound,
                "master_gap": master_result.primary.mip_gap,
                "infeasible_contingencies": len(infeasible),
                "added_contingency_indices": list(newly_added),
                **screen,
            }
        )
        if not infeasible:
            values = _assemble_full_values(
                full_model,
                master,
                master_result.column_values,
                blocks,
            )
            objective = float(np.dot(full_model.primary_cost, values))
            dual_bound = master_result.primary.dual_bound
            if dual_bound is None:
                raise RuntimeError("Scenario master returned no valid lower bound")
            gap = abs(objective - dual_bound) / max(abs(objective), 1e-12)
            stage = StageSummary(
                name="primary_scenario_generation",
                model_status="Optimal",
                status_code="HighsStatus.kOk",
                wall_seconds=master_wall + screen_wall,
                objective=objective,
                dual_bound=dual_bound,
                mip_gap=gap,
                node_count=total_nodes,
                simplex_iterations=total_iterations,
                ipm_iterations=0,
                max_primal_infeasibility=master_result.primary.max_primal_infeasibility,
                max_integrality_violation=master_result.primary.max_integrality_violation,
            )
            diagnostics: dict[str, object] = {
                "method": "exact_scenario_generation",
                "fixed_prior_commitment": fixed_prior_commitment,
                "round_count": len(rounds),
                "final_active_contingencies": len(active),
                "final_exhaustive_screens": len(case.contingencies),
                "rounds": rounds,
                "master_wall_seconds_sum": master_wall,
                "screen_wall_seconds_sum": screen_wall,
            }
            return values, stage, diagnostics
        if not newly_added:
            raise RuntimeError("An active contingency remained infeasible in an independent screen")
        active = tuple(sorted((*active, *newly_added)))
    raise RuntimeError(f"Scenario generation exceeded {max_rounds} registered rounds")


def generate_internal_incumbent(
    case: CaseData,
    full_model: CanonicalModel,
    config: dict[str, Any],
    deadline: RunDeadline,
    *,
    reserve_seconds: float,
) -> tuple[np.ndarray | None, dict[str, object]]:
    budget = float(config.get("ablation", {}).get("incumbent_budget_seconds", 120.0))
    local_deadline = RunDeadline.start(min(budget, deadline.remaining_seconds()))
    started = time.perf_counter()
    try:
        values, stage, diagnostics = _scenario_generation(
            case,
            full_model,
            config,
            deadline,
            reserve_seconds=reserve_seconds,
            initial_full_start=None,
            fixed_prior_commitment=True,
            local_deadline=local_deadline,
        )
        arrays = physical_arrays(full_model, values)
        residual, security = _check_physical(case, arrays, fixed_commitment=None)
        residual_limit = float(config["numerics"]["model_residual_tolerance_pu"])
        security_limit = float(config["numerics"]["security_violation_tolerance_pu"])
        if residual.maximum > residual_limit or security.maximum > security_limit:
            raise RuntimeError("Internally generated incumbent failed the independent physical gate")
        return values, {
            "status": "generated",
            "wall_seconds": time.perf_counter() - started,
            "objective": float(np.dot(full_model.primary_cost, values)),
            "certificate_stage": stage.__dict__,
            "maximum_model_residual_pu": residual.maximum,
            "maximum_security_violation_pu": security.maximum,
            "details": diagnostics,
        }
    except (RunDeadlineExceeded, RuntimeError) as exc:
        return None, {
            "status": "not_generated",
            "wall_seconds": time.perf_counter() - started,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def solve_decomposed_primary(
    case: CaseData,
    full_model: CanonicalModel,
    config: dict[str, Any],
    deadline: RunDeadline,
    *,
    reserve_seconds: float,
    initial_full_start: np.ndarray | None,
    incumbent_diagnostics: dict[str, object] | None,
) -> PrimaryResult:
    started = time.perf_counter()
    values, stage, diagnostics = _scenario_generation(
        case,
        full_model,
        config,
        deadline,
        reserve_seconds=reserve_seconds,
        initial_full_start=initial_full_start,
        fixed_prior_commitment=False,
    )
    target_gap = float(config["solver"]["mip_relative_gap"])
    if stage.mip_gap is None or stage.mip_gap > target_gap + 1e-12:
        raise RuntimeError(
            f"Scenario generation did not certify requested gap {target_gap}: {stage.mip_gap}"
        )
    acceleration: dict[str, object] = {
        "decomposition": diagnostics,
        "mip_start": {
            "attempted": initial_full_start is not None,
            "accepted": initial_full_start is not None,
            "column_count": (
                int(full_model.layout.num_columns) if initial_full_start is not None else 0
            ),
            "status": "projected_into_each_master" if initial_full_start is not None else None,
        },
        "primary_total_wall_seconds": time.perf_counter() - started,
    }
    if incumbent_diagnostics is not None:
        acceleration["internal_incumbent"] = incumbent_diagnostics
    return PrimaryResult(stage, float(np.dot(full_model.primary_cost, values)), values, None, None, acceleration)
