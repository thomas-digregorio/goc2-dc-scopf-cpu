from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

import highspy
import numpy as np

from .model import CanonicalModel


@dataclass(frozen=True)
class StageSummary:
    name: str
    model_status: str
    status_code: str
    wall_seconds: float
    objective: float | None
    dual_bound: float | None
    mip_gap: float | None
    node_count: int
    simplex_iterations: int
    ipm_iterations: int
    max_primal_infeasibility: float | None
    max_integrality_violation: float | None


@dataclass
class PrimaryResult:
    primary: StageSummary
    objective: float
    column_values: np.ndarray
    resident_highs: highspy.Highs | None = None
    resident_basis: highspy.HighsBasis | None = None


@dataclass(frozen=True)
class PricingHotStartSummary:
    required: bool
    resident_model_reused: bool
    fixed_column_count: int
    fixed_bounds_status: str
    relaxed_integer_column_count: int
    relaxed_integrality_status: str
    primary_basis_available: bool
    basis_attempted: bool
    basis_status: str | None
    basis_accepted: bool
    primal_start_attempted: bool
    primal_start_column_count: int
    primal_start_status: str | None
    primal_start_accepted: bool
    selected_method: str
    pricing_solver: str
    solution_value_valid_before_run: bool
    basis_valid_before_run: bool
    basis_valid_after_run: bool


@dataclass
class PricingResult:
    summary: StageSummary
    objective: float
    column_values: np.ndarray
    base_balance_duals: np.ndarray
    hot_start: PricingHotStartSummary


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _stage_summary(
    name: str, highs: highspy.Highs, status: highspy.HighsStatus, wall: float
) -> StageSummary:
    info = highs.getInfo()
    model_status = highs.getModelStatus()
    return StageSummary(
        name=name,
        model_status=highs.modelStatusToString(model_status),
        status_code=str(status),
        wall_seconds=wall,
        objective=_finite(info.objective_function_value),
        dual_bound=_finite(info.mip_dual_bound),
        mip_gap=_finite(info.mip_gap),
        node_count=int(info.mip_node_count),
        simplex_iterations=int(info.simplex_iteration_count),
        ipm_iterations=int(info.ipm_iteration_count),
        max_primal_infeasibility=_finite(info.max_primal_infeasibility),
        max_integrality_violation=_finite(info.max_integrality_violation),
    )


def _set_option(highs: highspy.Highs, name: str, value: object) -> None:
    status = highs.setOptionValue(name, value)
    if status != highspy.HighsStatus.kOk:
        raise RuntimeError(f"HiGHS rejected option {name}={value!r}: {status}")


def _configure(highs: highspy.Highs, solver_config: dict, *, mip: bool) -> None:
    console = bool(solver_config.get("console_logging", True))
    _set_option(highs, "output_flag", console)
    _set_option(highs, "log_to_console", console)
    _set_option(highs, "presolve", str(solver_config.get("presolve", "on")))
    _set_option(highs, "random_seed", int(solver_config.get("random_seed", 0)))
    _set_option(
        highs,
        "primal_feasibility_tolerance",
        float(solver_config.get("primal_feasibility_tolerance", 1e-7)),
    )
    _set_option(
        highs,
        "dual_feasibility_tolerance",
        float(solver_config.get("dual_feasibility_tolerance", 1e-7)),
    )
    if mip:
        _set_option(
            highs,
            "mip_feasibility_tolerance",
            float(solver_config.get("mip_feasibility_tolerance", 1e-6)),
        )
    threads = int(solver_config.get("threads", 0))
    _set_option(highs, "threads", threads)
    time_limit = solver_config.get("time_limit_seconds")
    if time_limit is not None:
        _set_option(highs, "time_limit", float(time_limit))
    if mip:
        _set_option(highs, "mip_rel_gap", float(solver_config["mip_relative_gap"]))
        _set_option(highs, "mip_abs_gap", float(solver_config.get("mip_absolute_gap", 0.0)))
        if "mip_lp_solver" in solver_config:
            _set_option(highs, "mip_lp_solver", str(solver_config["mip_lp_solver"]))
    elif "pricing_lp_solver" in solver_config:
        _set_option(highs, "solver", str(solver_config["pricing_lp_solver"]))


def _highs_model(
    model: CanonicalModel,
    cost: np.ndarray,
    *,
    relax_integrality: bool,
    column_lower: np.ndarray | None = None,
    column_upper: np.ndarray | None = None,
) -> highspy.HighsLp:
    starts, indices, values, row_lower, row_upper = model.rows.numpy_buffers()
    lp = highspy.HighsLp()
    lp.num_col_ = model.layout.num_columns
    lp.num_row_ = model.rows.num_rows
    lp.col_cost_ = np.asarray(cost, dtype=np.float64)
    lp.col_lower_ = model.column_lower if column_lower is None else column_lower
    lp.col_upper_ = model.column_upper if column_upper is None else column_upper
    lp.row_lower_ = row_lower
    lp.row_upper_ = row_upper
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.num_col_ = lp.num_col_
    lp.a_matrix_.num_row_ = lp.num_row_
    lp.a_matrix_.start_ = starts
    lp.a_matrix_.index_ = indices
    lp.a_matrix_.value_ = values
    if not relax_integrality:
        integrality = [highspy.HighsVarType.kContinuous] * lp.num_col_
        for column in model.integer_columns:
            integrality[int(column)] = highspy.HighsVarType.kInteger
        lp.integrality_ = integrality
    return lp


def _pass_model(highs: highspy.Highs, lp: highspy.HighsLp) -> None:
    status = highs.passModel(lp)
    if status != highspy.HighsStatus.kOk:
        raise RuntimeError(f"HiGHS passModel failed: {status}")


def _require_ok(operation: str, status: highspy.HighsStatus) -> str:
    status_text = str(status)
    if status != highspy.HighsStatus.kOk:
        raise RuntimeError(f"HiGHS {operation} failed: {status_text}")
    return status_text


def validate_model_translation(model: CanonicalModel) -> dict[str, int]:
    """Pass the matrix to HiGHS without presolving or optimizing it."""
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    _pass_model(highs, _highs_model(model, model.primary_cost, relax_integrality=False))
    translated = highs.getLp()
    if (
        translated.num_col_ != model.layout.num_columns
        or translated.num_row_ != model.rows.num_rows
    ):
        raise RuntimeError("HiGHS translated model dimensions do not match the canonical model")
    return {"columns": translated.num_col_, "rows": translated.num_row_}


def _require_solution(stage: StageSummary, highs: highspy.Highs) -> np.ndarray:
    solution = highs.getSolution()
    if not solution.value_valid:
        raise RuntimeError(f"{stage.name} has no valid incumbent: {stage.model_status}")
    values = np.asarray(solution.col_value, dtype=np.float64)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise RuntimeError(f"{stage.name} has no finite incumbent: {stage.model_status}")
    return values


def solve_primary_milp(model: CanonicalModel, config: dict) -> PrimaryResult:
    solver_config = config["solver"]
    highs = highspy.Highs()
    _configure(highs, solver_config, mip=True)
    _pass_model(highs, _highs_model(model, model.primary_cost, relax_integrality=False))

    start = time.perf_counter()
    status = highs.run()
    primary_stage = _stage_summary("primary_milp", highs, status, time.perf_counter() - start)
    primary_values = _require_solution(primary_stage, highs)
    primary_objective = float(np.dot(model.primary_cost, primary_values))
    target_gap = float(solver_config["mip_relative_gap"])
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(
            f"Primary MILP is not optimal at the requested tolerance: {primary_stage.model_status}"
        )
    if primary_stage.mip_gap is None or primary_stage.mip_gap > target_gap + 1e-12:
        raise RuntimeError(
            f"Primary MILP did not certify requested gap {target_gap}: {primary_stage.mip_gap}"
        )
    basis = highs.getBasis()
    return PrimaryResult(primary_stage, primary_objective, primary_values, highs, basis)


def solve_pricing_lp(model: CanonicalModel, config: dict, primary: PrimaryResult) -> PricingResult:
    solver_config = config["solver"]
    hot_start_required = bool(solver_config.get("pricing_hot_start_required", False))
    milp_values = primary.column_values
    fixed_columns: list[int] = []
    for state in model.layout.states:
        fixed_columns.extend(range(state.u_start, state.stop))
    fixed = np.asarray(fixed_columns, dtype=np.int32)
    fixed_values = np.asarray(milp_values[fixed], dtype=np.float64)
    integer_columns = np.asarray(model.integer_columns, dtype=np.int32)
    continuous_types = np.full(
        integer_columns.size, highspy.HighsVarType.kContinuous, dtype=np.uint8
    )
    pricing_solver = str(solver_config.get("pricing_lp_solver", "choose"))

    resident_model_reused = primary.resident_highs is not None
    if hot_start_required and not resident_model_reused:
        raise RuntimeError(
            "Pricing hot start requires the resident verified primary HiGHS model; "
            "checkpoint-only reconstruction is not sufficient"
        )

    if resident_model_reused:
        highs = primary.resident_highs
        assert highs is not None
        translated = highs.getLp()
        if (
            translated.num_col_ != model.layout.num_columns
            or translated.num_row_ != model.rows.num_rows
        ):
            raise RuntimeError("Resident HiGHS model dimensions changed after the primary solve")
        _configure(highs, solver_config, mip=False)
        fixed_status = _require_ok(
            "fixed-commitment bound update",
            highs.changeColsBounds(fixed.size, fixed, fixed_values, fixed_values),
        )
        integrality_status = _require_ok(
            "integrality relaxation",
            highs.changeColsIntegrality(integer_columns.size, integer_columns, continuous_types),
        )

        primary_basis = primary.resident_basis
        primary_basis_available = bool(primary_basis is not None and primary_basis.valid)
        basis_attempted = primary_basis_available
        basis_status: str | None = None
        basis_accepted = False
        if primary_basis_available:
            assert primary_basis is not None
            raw_basis_status = highs.setBasis(primary_basis)
            basis_status = str(raw_basis_status)
            basis_accepted = bool(
                raw_basis_status == highspy.HighsStatus.kOk and highs.getBasis().valid
            )

        primal_start_attempted = not basis_accepted
        primal_start_status: str | None = None
        primal_start_accepted = False
        if primal_start_attempted:
            all_columns = np.arange(model.layout.num_columns, dtype=np.int32)
            raw_start_status = highs.setSolution(
                all_columns.size, all_columns, np.asarray(milp_values, dtype=np.float64)
            )
            primal_start_status = str(raw_start_status)
            primal_start_accepted = bool(
                raw_start_status == highspy.HighsStatus.kOk and highs.getSolution().value_valid
            )
        if not basis_accepted and not primal_start_accepted:
            raise RuntimeError(
                "HiGHS accepted neither the resident primary basis nor the complete "
                "verified-primary primal start for pricing"
            )
        selected_method = "resident_basis" if basis_accepted else "complete_primary_primal"
        solution_value_valid_before_run = bool(highs.getSolution().value_valid)
        basis_valid_before_run = bool(highs.getBasis().valid)
    else:
        column_lower = model.column_lower.copy()
        column_upper = model.column_upper.copy()
        column_lower[fixed] = fixed_values
        column_upper[fixed] = fixed_values
        lp = _highs_model(
            model,
            model.primary_cost,
            relax_integrality=True,
            column_lower=column_lower,
            column_upper=column_upper,
        )
        highs = highspy.Highs()
        _configure(highs, solver_config, mip=False)
        _pass_model(highs, lp)
        fixed_status = "applied_while_building_fresh_lp"
        integrality_status = "applied_while_building_fresh_lp"
        primary_basis_available = False
        basis_attempted = False
        basis_status = None
        basis_accepted = False
        primal_start_attempted = False
        primal_start_status = None
        primal_start_accepted = False
        selected_method = "none_checkpoint_resume"
        solution_value_valid_before_run = bool(highs.getSolution().value_valid)
        basis_valid_before_run = bool(highs.getBasis().valid)

    if bool(solver_config.get("console_logging", True)):
        acceptance_log = {
            "basis_accepted": basis_accepted,
            "basis_attempted": basis_attempted,
            "basis_status": basis_status,
            "primal_start_accepted": primal_start_accepted,
            "primal_start_attempted": primal_start_attempted,
            "primal_start_status": primal_start_status,
            "resident_model_reused": resident_model_reused,
            "selected_method": selected_method,
        }
        print(
            f"Pricing hot-start pre-run acceptance: {json.dumps(acceptance_log, sort_keys=True)}",
            flush=True,
        )

    start = time.perf_counter()
    status = highs.run()
    stage = _stage_summary(
        "fixed_commitment_pricing_lp", highs, status, time.perf_counter() - start
    )
    values = _require_solution(stage, highs)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Pricing LP is not optimal: {stage.model_status}")
    row_duals = np.asarray(highs.getSolution().row_dual, dtype=np.float64)
    base_duals = row_duals[np.asarray(model.metadata.base_balance_rows, dtype=np.int64)]
    hot_start = PricingHotStartSummary(
        required=hot_start_required,
        resident_model_reused=resident_model_reused,
        fixed_column_count=int(fixed.size),
        fixed_bounds_status=fixed_status,
        relaxed_integer_column_count=int(integer_columns.size),
        relaxed_integrality_status=integrality_status,
        primary_basis_available=primary_basis_available,
        basis_attempted=basis_attempted,
        basis_status=basis_status,
        basis_accepted=basis_accepted,
        primal_start_attempted=primal_start_attempted,
        primal_start_column_count=(model.layout.num_columns if primal_start_attempted else 0),
        primal_start_status=primal_start_status,
        primal_start_accepted=primal_start_accepted,
        selected_method=selected_method,
        pricing_solver=pricing_solver,
        solution_value_valid_before_run=solution_value_valid_before_run,
        basis_valid_before_run=basis_valid_before_run,
        basis_valid_after_run=bool(highs.getBasis().valid),
    )
    if bool(solver_config.get("console_logging", True)):
        print(f"Pricing hot-start acceptance: {json.dumps(hot_start.__dict__, sort_keys=True)}")
    return PricingResult(
        stage,
        float(np.dot(model.primary_cost, values)),
        values,
        base_duals,
        hot_start,
    )
