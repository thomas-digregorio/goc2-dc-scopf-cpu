from __future__ import annotations

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
class MilpResult:
    primary: StageSummary
    secondary: StageSummary
    primary_incumbent_objective: float
    final_primary_objective: float
    final_secondary_objective: float
    column_values: np.ndarray


@dataclass
class PricingResult:
    summary: StageSummary
    objective: float
    column_values: np.ndarray
    base_balance_duals: np.ndarray


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _stage_summary(name: str, highs: highspy.Highs, status: highspy.HighsStatus, wall: float) -> StageSummary:
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
    threads = int(solver_config.get("threads", 0))
    _set_option(highs, "threads", threads)
    time_limit = solver_config.get("time_limit_seconds")
    if time_limit is not None:
        _set_option(highs, "time_limit", float(time_limit))
    if mip:
        _set_option(highs, "mip_rel_gap", float(solver_config["mip_relative_gap"]))
        _set_option(highs, "mip_abs_gap", float(solver_config.get("mip_absolute_gap", 0.0)))


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


def validate_model_translation(model: CanonicalModel) -> dict[str, int]:
    """Pass the matrix to HiGHS without presolving or optimizing it."""
    highs = highspy.Highs()
    highs.setOptionValue("output_flag", False)
    _pass_model(highs, _highs_model(model, model.primary_cost, relax_integrality=False))
    translated = highs.getLp()
    if translated.num_col_ != model.layout.num_columns or translated.num_row_ != model.rows.num_rows:
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


def solve_lexicographic(model: CanonicalModel, config: dict) -> MilpResult:
    solver_config = config["solver"]
    highs = highspy.Highs()
    _configure(highs, solver_config, mip=True)
    _pass_model(highs, _highs_model(model, model.primary_cost, relax_integrality=False))

    start = time.perf_counter()
    status = highs.run()
    primary_stage = _stage_summary("primary_milp", highs, status, time.perf_counter() - start)
    primary_values = _require_solution(primary_stage, highs)
    primary_incumbent = float(np.dot(model.primary_cost, primary_values))
    target_gap = float(solver_config["mip_relative_gap"])
    if primary_stage.mip_gap is None or primary_stage.mip_gap > target_gap + 1e-12:
        raise RuntimeError(
            f"Primary MILP did not certify requested gap {target_gap}: {primary_stage.mip_gap}"
        )

    primary_columns = np.flatnonzero(model.primary_cost).astype(np.int32)
    cap = primary_incumbent + float(config["numerics"]["primary_lexicographic_cap_usd"])
    add_status = highs.addRow(
        -highspy.kHighsInf,
        cap,
        int(primary_columns.size),
        primary_columns,
        model.primary_cost[primary_columns],
    )
    if add_status != highspy.HighsStatus.kOk:
        raise RuntimeError(f"Could not add primary lexicographic cap: {add_status}")
    changed = np.union1d(np.flatnonzero(model.primary_cost), np.flatnonzero(model.secondary_cost)).astype(np.int32)
    change_status = highs.changeColsCost(
        int(changed.size), changed, np.asarray(model.secondary_cost[changed], dtype=np.float64)
    )
    if change_status != highspy.HighsStatus.kOk:
        raise RuntimeError(f"Could not install secondary objective: {change_status}")

    start = time.perf_counter()
    status = highs.run()
    secondary_stage = _stage_summary("secondary_milp", highs, status, time.perf_counter() - start)
    final_values = _require_solution(secondary_stage, highs)
    if secondary_stage.mip_gap is None or secondary_stage.mip_gap > target_gap + 1e-12:
        raise RuntimeError(
            f"Secondary MILP did not certify requested gap {target_gap}: {secondary_stage.mip_gap}"
        )
    final_primary = float(np.dot(model.primary_cost, final_values))
    if final_primary > cap + 1e-5:
        raise RuntimeError(f"Secondary solution violates primary cap: {final_primary} > {cap}")
    return MilpResult(
        primary_stage,
        secondary_stage,
        primary_incumbent,
        final_primary,
        float(np.dot(model.secondary_cost, final_values)),
        final_values,
    )


def solve_pricing_lp(model: CanonicalModel, config: dict, milp_values: np.ndarray) -> PricingResult:
    fixed_columns: list[int] = []
    for state in model.layout.states:
        fixed_columns.extend(range(state.u_start, state.stop))
    fixed = np.asarray(fixed_columns, dtype=np.int32)
    fixed_values = np.asarray(milp_values[fixed], dtype=np.float64)
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
    _configure(highs, config["solver"], mip=False)
    _pass_model(highs, lp)
    start = time.perf_counter()
    status = highs.run()
    stage = _stage_summary("fixed_commitment_pricing_lp", highs, status, time.perf_counter() - start)
    values = _require_solution(stage, highs)
    if highs.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"Pricing LP is not optimal: {stage.model_status}")
    row_duals = np.asarray(highs.getSolution().row_dual, dtype=np.float64)
    base_duals = row_duals[np.asarray(model.metadata.base_balance_rows, dtype=np.int64)]
    return PricingResult(stage, float(np.dot(model.primary_cost, values)), values, base_duals)
