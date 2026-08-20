from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .paths import require_local_path, sha256_file
from .results import load_result, read_npz, save_result
from .source import CaseData, CostSegment, read_case


@dataclass
class ViolationTracker:
    maximum: float = 0.0
    category: str = "none"
    identity: str = ""

    def observe(self, value: float, category: str, identity: object) -> None:
        value = max(0.0, float(value))
        if value > self.maximum:
            self.maximum = value
            self.category = category
            self.identity = str(identity)


def _pwl(quantity_pu: float, segments: tuple[CostSegment, ...], base_mva: float) -> float:
    remaining = max(0.0, float(quantity_pu))
    value = 0.0
    for segment in segments:
        used = min(remaining, segment.width_pu)
        value += used * base_mva * segment.marginal_per_mwh
        remaining -= used
        if remaining <= 1e-10:
            break
    if remaining > 1e-7:
        raise ValueError(f"PWL quantity exceeds source domain by {remaining * base_mva:.6g} MW")
    return value


def _validate_artifact(root: Path, record: dict[str, Any]) -> dict[str, np.ndarray]:
    path = require_local_path(root / record["path"], "result artifact")
    actual = sha256_file(path)
    if actual.casefold() != str(record["sha256"]).casefold():
        raise ValueError(f"Artifact SHA256 mismatch for {path}")
    return read_npz(path)


def _shape(name: str, value: np.ndarray, expected: tuple[int, ...]) -> None:
    if value.shape != expected:
        raise ValueError(f"{name} has shape {value.shape}, expected {expected}")
    if not np.all(np.isfinite(value)):
        raise ValueError(f"{name} contains nonfinite values")


def _check_physical(
    case: CaseData,
    arrays: dict[str, np.ndarray],
    *,
    fixed_commitment: np.ndarray | None,
) -> tuple[ViolationTracker, ViolationTracker]:
    ns = case.states
    nb = len(case.buses)
    ng = len(case.generators)
    nl = len(case.loads)
    ne = len(case.branches)
    expected = {
        "theta_rad": (ns, nb),
        "generation_pu": (ns, ng),
        "load_pu": (ns, nl),
        "flow_pu": (ns, ne),
        "commitment": (ns, ng),
        "startup": (ns, ng),
        "shutdown": (ns, ng),
    }
    for name, shape in expected.items():
        if name not in arrays:
            raise ValueError(f"Missing result array {name}")
        _shape(name, arrays[name], shape)

    theta = arrays["theta_rad"]
    pg = arrays["generation_pu"]
    load_values = arrays["load_pu"]
    flow = arrays["flow_pu"]
    raw_u = arrays["commitment"]
    u = np.rint(raw_u).astype(np.int8)
    startup = arrays["startup"]
    shutdown = arrays["shutdown"]
    model = ViolationTracker()
    security = ViolationTracker()
    model.observe(float(np.max(np.abs(raw_u - u))), "integrality", "all states")
    if fixed_commitment is not None:
        model.observe(
            float(np.max(np.abs(raw_u - fixed_commitment))), "fixed commitment", "pricing LP"
        )

    bus_shunt = np.zeros(nb, dtype=np.float64)
    for shunt in case.fixed_shunts:
        bus_shunt[shunt.bus_index] += shunt.conductance_pu
    bus_generators: list[list[int]] = [[] for _ in range(nb)]
    bus_loads: list[list[int]] = [[] for _ in range(nb)]
    bus_branches: list[list[tuple[int, float]]] = [[] for _ in range(nb)]
    for g, generator in enumerate(case.generators):
        bus_generators[generator.bus_index].append(g)
    for load_index, record in enumerate(case.loads):
        bus_loads[record.bus_index].append(load_index)
    for branch_index, branch in enumerate(case.branches):
        bus_branches[branch.from_bus_index].append((branch_index, -1.0))
        bus_branches[branch.to_bus_index].append((branch_index, 1.0))

    prior_u = np.asarray([g.prior_on for g in case.generators], dtype=np.int8)
    prior_pg = np.asarray([g.prior_p_pu for g in case.generators], dtype=np.float64)
    base_start = np.maximum(u[0] - prior_u, 0)
    base_stop = np.maximum(prior_u - u[0], 0)
    model.observe(float(np.max(np.abs(startup[0] - base_start))), "base startup indicator", "all")
    model.observe(float(np.max(np.abs(shutdown[0] - base_stop))), "base shutdown indicator", "all")

    for state in range(ns):
        contingency = None if state == 0 else case.contingencies[state - 1]
        model.observe(abs(theta[state, 0]), "reference angle", state)
        for g, generator in enumerate(case.generators):
            failed = contingency is not None and contingency.generator_index == g
            if failed:
                model.observe(abs(pg[state, g]), "outaged generator dispatch", (state, generator.key))
                model.observe(abs(raw_u[state, g]), "outaged generator status", (state, generator.key))
                continue
            model.observe(generator.pmin_pu * u[state, g] - pg[state, g], "PMIN", (state, generator.key))
            model.observe(pg[state, g] - generator.pmax_pu * u[state, g], "PMAX", (state, generator.key))
            if state == 0:
                previous_u = prior_u[g]
                previous_p = prior_pg[g]
                su_qual = generator.startup_qualified_base
                sd_qual = generator.shutdown_qualified_base
                ru = generator.ramp_up_base_pu_per_h * case.response_base_hours
                rd = generator.ramp_down_base_pu_per_h * case.response_base_hours
            else:
                previous_u = u[0, g]
                previous_p = pg[0, g]
                su_qual = generator.startup_qualified_ctg
                sd_qual = generator.shutdown_qualified_ctg
                ru = generator.ramp_up_ctg_pu_per_h * case.response_ctg_hours
                rd = generator.ramp_down_ctg_pu_per_h * case.response_ctg_hours
                actual_start = max(int(u[state, g]) - int(previous_u), 0)
                actual_stop = max(int(previous_u) - int(u[state, g]), 0)
                model.observe(abs(startup[state, g] - actual_start), "startup indicator", (state, generator.key))
                model.observe(abs(shutdown[state, g] - actual_stop), "shutdown indicator", (state, generator.key))
                model.observe(base_start[g] + actual_stop - 1.0, "startup reversal", (state, generator.key))
                model.observe(base_stop[g] + actual_start - 1.0, "shutdown reversal", (state, generator.key))
            actual_start = max(int(u[state, g]) - int(previous_u), 0)
            actual_stop = max(int(previous_u) - int(u[state, g]), 0)
            model.observe(actual_start - su_qual, "startup permission", (state, generator.key))
            model.observe(actual_stop - sd_qual, "shutdown permission", (state, generator.key))
            if u[state, g] == 0:
                model.observe(abs(pg[state, g]), "off generator dispatch", (state, generator.key))
            elif previous_u == 1:
                model.observe(pg[state, g] - previous_p - ru, "ramp up", (state, generator.key))
                model.observe(previous_p - pg[state, g] - rd, "ramp down", (state, generator.key))
            else:
                model.observe(
                    pg[state, g] - generator.pmin_pu - ru,
                    "startup output capability",
                    (state, generator.key),
                )

        for load_index, record in enumerate(case.loads):
            value = load_values[state, load_index]
            model.observe(record.pmin_pu - value, "load lower bound", (state, record.key))
            model.observe(value - record.pmax_pu, "load upper bound", (state, record.key))
            if state == 0:
                previous = record.prior_p_pu
                ru = record.ramp_up_base_pu_per_h * case.response_base_hours
                rd = record.ramp_down_base_pu_per_h * case.response_base_hours
            else:
                previous = load_values[0, load_index]
                ru = record.ramp_up_ctg_pu_per_h * case.response_ctg_hours
                rd = record.ramp_down_ctg_pu_per_h * case.response_ctg_hours
            model.observe(value - previous - ru, "load ramp up", (state, record.key))
            model.observe(previous - value - rd, "load ramp down", (state, record.key))

        for branch_index, branch in enumerate(case.branches):
            outaged = contingency is not None and contingency.branch_index == branch_index
            if outaged:
                model.observe(abs(flow[state, branch_index]), "outaged branch flow", (state, branch.key))
                continue
            expected_flow = (
                theta[state, branch.from_bus_index]
                - theta[state, branch.to_bus_index]
                - branch.phase_shift_rad
            ) / (branch.reactance_pu * branch.tap_magnitude)
            residual = abs(flow[state, branch_index] - expected_flow)
            model.observe(residual, "DC branch equation", (state, branch.key))
            limit = branch.normal_limit_pu if state == 0 else branch.emergency_limit_pu
            violation = abs(flow[state, branch_index]) - limit
            model.observe(violation, "thermal limit", (state, branch.key))
            if state > 0:
                security.observe(violation, "contingency thermal limit", (state, branch.key))

        for bus_index, bus in enumerate(case.buses):
            balance = -bus_shunt[bus_index]
            balance += sum(pg[state, g] for g in bus_generators[bus_index])
            balance -= sum(load_values[state, l] for l in bus_loads[bus_index])
            balance += sum(sign * flow[state, e] for e, sign in bus_branches[bus_index])
            model.observe(abs(balance), "nodal balance", (state, bus.number))
            if state > 0:
                security.observe(abs(balance), "contingency nodal balance", (state, bus.number))

    return model, security


def _objective(case: CaseData, arrays: dict[str, np.ndarray]) -> float:
    pg = arrays["generation_pu"][0]
    load = arrays["load_pu"][0]
    u = np.rint(arrays["commitment"][0]).astype(np.int8)
    startup = arrays["startup"][0]
    shutdown = arrays["shutdown"][0]
    value = 0.0
    for g, generator in enumerate(case.generators):
        value += _pwl(pg[g], generator.cost_segments, case.base_mva) * case.delta_hours
        value += generator.on_cost_per_h * case.delta_hours * u[g]
        value += generator.startup_cost * startup[g] + generator.shutdown_cost * shutdown[g]
    for load_index, record in enumerate(case.loads):
        value -= _pwl(load[load_index], record.benefit_segments, case.base_mva) * case.delta_hours
    return float(value)


def verify_result(root: Path, config: dict, result_path: Path) -> dict[str, Any]:
    root = require_local_path(root, "repository")
    result_path = require_local_path(result_path, "result JSON")
    payload = load_result(result_path)
    case = read_case(root, config)
    if payload["profile"] != case.profile or payload["source"]["scenario"] != case.scenario:
        raise ValueError("Result source identity does not match the registered case")
    if payload["source"]["hashes"] != case.source_hashes:
        raise ValueError("Result source hashes do not match freshly read inputs")

    milp_arrays = _validate_artifact(root, payload["artifacts"]["milp_primal"])
    pricing_arrays = _validate_artifact(root, payload["artifacts"]["pricing_primal"])
    model_violation, security_violation = _check_physical(case, milp_arrays, fixed_commitment=None)
    pricing_violation, pricing_security = _check_physical(
        case, pricing_arrays, fixed_commitment=milp_arrays["commitment"]
    )
    objective = _objective(case, milp_arrays)
    pricing_objective = _objective(case, pricing_arrays)
    objective_error = abs(objective - float(payload["objectives"]["final_primary_usd"]))
    pricing_objective_error = abs(
        pricing_objective - float(payload["objectives"]["fixed_commitment_pricing_lp_usd"])
    )
    model_violation.observe(objective_error / max(case.base_mva, 1.0), "objective", "MILP")
    pricing_violation.observe(
        pricing_objective_error / max(case.base_mva, 1.0), "objective", "pricing LP"
    )

    prices = payload["pricing"]["base_usd_per_mwh"]
    if len(prices) != len(case.buses) or not all(math.isfinite(float(x["price"])) for x in prices):
        raise ValueError("Pricing output is missing or nonfinite")
    requested_gap = float(config["solver"]["mip_relative_gap"])
    reported_gap = payload["objectives"]["primary_mip_gap"]
    gap_pass = reported_gap is not None and float(reported_gap) <= requested_gap + 1e-12
    residual_tolerance = float(config["numerics"]["model_residual_tolerance_pu"])
    security_tolerance = float(config["numerics"]["security_violation_tolerance_pu"])
    pricing_optimal = payload["solver"]["pricing"]["model_status"] == "Optimal"
    maximum_model = max(model_violation.maximum, pricing_violation.maximum)
    maximum_security = max(security_violation.maximum, pricing_security.maximum)
    passed = (
        gap_pass
        and maximum_model <= residual_tolerance
        and maximum_security <= security_tolerance
        and pricing_optimal
    )
    summary = {
        "status": "pass" if passed else "fail",
        "mip_gap_pass": gap_pass,
        "pricing_lp_optimal": pricing_optimal,
        "maximum_model_residual_pu": maximum_model,
        "maximum_model_residual_detail": {
            "milp": model_violation.__dict__,
            "pricing": pricing_violation.__dict__,
        },
        "maximum_exhaustive_security_violation_pu": maximum_security,
        "maximum_security_violation_detail": {
            "milp": security_violation.__dict__,
            "pricing": pricing_security.__dict__,
        },
        "recomputed_primary_objective_usd": objective,
        "primary_objective_error_usd": objective_error,
        "recomputed_pricing_objective_usd": pricing_objective,
        "pricing_objective_error_usd": pricing_objective_error,
        "states_checked": case.states,
        "source_contingencies_checked": len(case.contingencies),
    }
    payload["checker"] = summary
    save_result(result_path, payload)
    return summary

