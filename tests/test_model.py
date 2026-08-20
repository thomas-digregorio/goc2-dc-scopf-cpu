from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import highspy
import numpy as np
import pytest
from jsonschema import Draft202012Validator

from goc2_dc_scopf.ablation import (
    generate_internal_incumbent,
    solve_decomposed_primary,
    validate_cell,
)
from goc2_dc_scopf.checker import _check_physical, _check_primary_solution, _objective
from goc2_dc_scopf.deadline import RunDeadline
from goc2_dc_scopf.highs import solve_pricing_lp, solve_primary_milp
from goc2_dc_scopf.model import build_extensive_model
from goc2_dc_scopf.results import (
    base_prices_from_duals,
    build_primary_checkpoint,
    build_result_payload,
    physical_arrays,
    pricing_arrays,
    primary_result_from_checkpoint,
)


def _ablation_config(config: dict, cell: str) -> dict:
    result = deepcopy(config)
    result["ablation"] = {
        "cell": cell,
        "decomposition": cell[0] == "1",
        "internal_incumbent": cell[1] == "1",
        "strong_valid_cuts": cell[2] == "1",
        "solver_tuning": cell[3] == "1",
        "incumbent_budget_seconds": 120,
        "max_decomposition_rounds": 32,
        "valid_cut_bus_count": 32,
        "linear_algebra_threads": 1 if cell[3] == "1" else None,
    }
    result["solver"]["threads"] = 0
    if cell[3] == "1":
        result["solver"]["threads"] = 24
        result["solver"]["advanced_options"] = {
            "parallel": "on",
            "simplex_strategy": 3,
            "simplex_max_concurrency": 8,
        }
    return result


def test_tiny_primary_milp_and_pricing(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    primary = solve_primary_milp(model, tiny_config)
    pricing = solve_pricing_lp(model, tiny_config, primary)
    arrays = physical_arrays(model, primary.column_values)
    pricing_primal = physical_arrays(model, pricing.column_values)
    violation, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    pricing_violation, pricing_security = _check_physical(
        tiny_case, pricing_primal, fixed_commitment=arrays["commitment"]
    )
    assert violation.maximum <= 1e-7
    assert security.maximum <= 1e-7
    assert pricing_violation.maximum <= 1e-7
    assert pricing_security.maximum <= 1e-7
    assert abs(_objective(tiny_case, arrays) - primary.objective) <= 1e-7
    assert abs(_objective(tiny_case, pricing_primal) - pricing.objective) <= 1e-7
    prices = base_prices_from_duals(
        pricing.base_balance_duals, tiny_case.base_mva, tiny_case.delta_hours
    )
    assert prices.tolist() == pytest.approx([10.0, 10.0, 10.0])
    retained_pricing = pricing_arrays(model, pricing)
    assert retained_pricing["base_balance_duals"].tolist() == pytest.approx(
        pricing.base_balance_duals.tolist()
    )
    assert primary.resident_highs is None
    assert not pricing.hot_start.required
    assert not pricing.hot_start.resident_model_reused
    assert pricing.hot_start.selected_method == "fresh_lp_no_start"
    assert pricing.hot_start.pricing_solver == "simplex"
    assert pricing.hot_start.fixed_bounds_status == "applied_while_building_fresh_lp"
    assert pricing.hot_start.relaxed_integrality_status == "applied_while_building_fresh_lp"
    assert not pricing.hot_start.basis_attempted
    assert not pricing.hot_start.basis_accepted
    assert not pricing.hot_start.primal_start_attempted
    assert not pricing.hot_start.primal_start_accepted
    assert pricing.hot_start.basis_valid_after_run

    commitment = np.rint(arrays["commitment"]).astype(int)
    assert commitment[0].tolist() == [1, 0]
    assert commitment[2].tolist() == [0, 1]
    assert arrays["generation_pu"][2, 1] == pytest.approx(1.0)

    primary_check = _check_primary_solution(
        tiny_case,
        arrays,
        asdict(primary.primary),
        {
            "primary_usd": primary.objective,
            "primary_dual_bound_usd": primary.primary.dual_bound,
            "primary_mip_gap": primary.primary.mip_gap,
        },
        tiny_config,
    )
    assert primary_check["status"] == "pass"

    checkpoint = build_primary_checkpoint(
        model,
        tiny_config,
        "config-hash",
        "commit",
        primary,
        {"path": "primary-primal.npz", "sha256": "0" * 64, "bytes": 1},
        {"primary_milp": primary.primary.wall_seconds},
        1,
    )
    assert checkpoint["status"] == "primary_solved"
    assert checkpoint["run"] == {"cold_start": True, "initial_solution": "none"}
    assert "secondary" not in checkpoint["solver"]
    checkpoint["profile"] = "GOC2-DC-D1-CORRECTIVE-v2"
    checkpoint_schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "primary-checkpoint.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(checkpoint_schema).validate(checkpoint)

    restored = primary_result_from_checkpoint(model, checkpoint, arrays)
    restored_arrays = physical_arrays(model, restored.column_values)
    for name, values in arrays.items():
        assert np.array_equal(restored_arrays[name], values)

    artifact = {"path": "artifact", "sha256": "0" * 64, "bytes": 1}
    payload = build_result_payload(
        model,
        tiny_config,
        "config-hash",
        "commit",
        primary,
        pricing,
        artifact,
        artifact,
        artifact,
        {},
        1,
    )
    assert payload["result_version"] == 2
    assert payload["objectives"]["primary_usd"] == pytest.approx(primary.objective)
    assert "secondary" not in payload["solver"]
    assert payload["solver"]["pricing_hot_start"] == asdict(pricing.hot_start)
    assert "secondary" not in payload["objectives"]
    assert [record["price"] for record in payload["pricing"]["base_usd_per_mwh"]] == pytest.approx(
        [10.0, 10.0, 10.0]
    )
    payload["profile"] = "GOC2-DC-D1-CORRECTIVE-v2"
    payload["contingencies"] = [{} for _ in range(815)]
    payload["pricing"]["base_usd_per_mwh"] = [{"bus": bus, "price": 10.0} for bus in range(617)]
    result_schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "result.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(result_schema).validate(payload)


def test_primary_model_has_no_corrective_movement_auxiliaries(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    state_columns = sum(state.stop - state.offset for state in model.layout.states)
    segment_columns = sum(len(x) for x in model.layout.generator_segment_columns)
    segment_columns += sum(len(x) for x in model.layout.load_segment_columns)
    assert model.layout.num_columns == state_columns + segment_columns
    assert not hasattr(model, "secondary_cost")


def test_strong_valid_cuts_preserve_tiny_optimum(tiny_case, tiny_config) -> None:
    default_model = build_extensive_model(tiny_case, tiny_config)
    default = solve_primary_milp(default_model, tiny_config)
    cut_config = _ablation_config(tiny_config, "0010")
    cut_model = build_extensive_model(tiny_case, cut_config)
    cut = solve_primary_milp(cut_model, cut_config)
    assert cut_model.metadata.valid_inequality_rows
    assert cut_model.rows.num_rows > default_model.rows.num_rows
    assert cut.objective == pytest.approx(default.objective, abs=1e-8)
    assert cut_model.maximum_valid_inequality_violation(cut.column_values) <= 1e-8
    arrays = physical_arrays(cut_model, cut.column_values)
    residual, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    assert residual.maximum <= 1e-7
    assert security.maximum <= 1e-7


def test_exact_scenario_generation_matches_extensive_tiny(tiny_case, tiny_config) -> None:
    config = _ablation_config(tiny_config, "1000")
    full_model = build_extensive_model(tiny_case, config)
    extensive = solve_primary_milp(full_model, config)
    decomposed = solve_decomposed_primary(
        tiny_case,
        full_model,
        config,
        RunDeadline.start(30.0),
        reserve_seconds=0.0,
        initial_full_start=None,
        incumbent_diagnostics=None,
    )
    assert decomposed.objective == pytest.approx(extensive.objective, abs=1e-8)
    assert decomposed.primary.dual_bound <= decomposed.objective + 1e-8
    assert decomposed.primary.mip_gap <= config["solver"]["mip_relative_gap"]
    arrays = physical_arrays(full_model, decomposed.column_values)
    residual, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    assert residual.maximum <= 1e-7
    assert security.maximum <= 1e-7
    assert decomposed.acceleration["decomposition"]["final_exhaustive_screens"] == 2


def test_source_only_internal_incumbent_is_complete_and_accepted(tiny_case, tiny_config) -> None:
    config = _ablation_config(tiny_config, "0100")
    full_model = build_extensive_model(tiny_case, config)
    incumbent, diagnostics = generate_internal_incumbent(
        tiny_case,
        full_model,
        config,
        RunDeadline.start(30.0),
        reserve_seconds=0.0,
    )
    assert incumbent is not None, diagnostics
    assert incumbent.shape == (full_model.layout.num_columns,)
    solved = solve_primary_milp(full_model, config, initial_solution=incumbent)
    assert solved.acceleration["mip_start"]["accepted"]
    arrays = physical_arrays(full_model, incumbent)
    residual, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    assert residual.maximum <= 1e-7
    assert security.maximum <= 1e-7


def test_factor_cell_validation(tiny_config) -> None:
    validate_cell(_ablation_config(tiny_config, "0000"))
    validate_cell(_ablation_config(tiny_config, "1111"))
    invalid = _ablation_config(tiny_config, "1000")
    invalid["ablation"]["cell"] = "0000"
    with pytest.raises(ValueError, match="does not match"):
        validate_cell(invalid)


def test_zero_factor_model_is_byte_identical(tiny_case, tiny_config) -> None:
    default = build_extensive_model(tiny_case, tiny_config)
    zero = build_extensive_model(tiny_case, _ablation_config(tiny_config, "0000"))
    assert default.statistics() == zero.statistics()
    for default_buffer, zero_buffer in zip(
        default.rows.numpy_buffers(), zero.rows.numpy_buffers(), strict=True
    ):
        assert np.array_equal(default_buffer, zero_buffer)
    assert np.array_equal(default.column_lower, zero.column_lower)
    assert np.array_equal(default.column_upper, zero.column_upper)
    assert np.array_equal(default.primary_cost, zero.primary_cost)


def test_registered_ablation_matrix_is_complete_and_valid() -> None:
    root = Path(__file__).parents[1]
    schema = json.loads((root / "schemas" / "config.schema.json").read_text(encoding="utf-8"))
    paths = sorted((root / "configs" / "ablation").glob("*.json"))
    expected = {f"{value:04b}" for value in range(1, 16)}
    actual: set[str] = set()
    for path in paths:
        config = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(config)
        validate_cell(config)
        actual.add(config["ablation"]["cell"])
        assert config["run_budget"]["end_to_end_limit_seconds"] == 1800
        assert config["solver"]["pricing_hot_start_required"] is False
    assert actual == expected


def test_hipo_root_and_required_resident_pricing_hot_start(tiny_case, tiny_config) -> None:
    capability_probe = highspy.Highs()
    capability_probe.setOptionValue("output_flag", False)
    if (
        capability_probe.setOptionValue("mip_lp_solver", "hipo")
        != highspy.HighsStatus.kOk
    ):
        pytest.skip("installed HiGHS build does not provide the optional HiPO dependencies")

    config = deepcopy(tiny_config)
    config["solver"].update(
        {
            "mip_lp_solver": "hipo",
            "pricing_lp_solver": "simplex",
            "pricing_hot_start_required": True,
        }
    )
    model = build_extensive_model(tiny_case, config)
    primary = solve_primary_milp(model, config)
    option_status, option_value = primary.resident_highs.getOptionValue("mip_lp_solver")
    assert str(option_status) == "HighsStatus.kOk"
    assert option_value == "hipo"

    pricing = solve_pricing_lp(model, config, primary)
    assert pricing.hot_start.required
    assert pricing.hot_start.resident_model_reused
    assert pricing.hot_start.pricing_solver == "simplex"
    assert pricing.hot_start.basis_accepted or pricing.hot_start.primal_start_accepted
    assert pricing.hot_start.selected_method == "complete_primary_primal"


def test_exact_pmin_is_active(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    state = model.layout.states[0]
    assert tiny_case.generators[0].pmin_pu == 0.2
    assert model.column_lower[state.pg(0)] == 0.0
    starts, indices, values, _, _ = model.rows.numpy_buffers()
    found = False
    for row in range(model.rows.num_rows):
        lo, hi = starts[row], starts[row + 1]
        pairs = dict(zip(indices[lo:hi].tolist(), values[lo:hi].tolist(), strict=True))
        if pairs.get(state.pg(0)) == -1.0 and pairs.get(state.u(0)) == 0.2:
            found = True
            break
    assert found


def test_base_indicators_are_directionally_bounded(tiny_case, tiny_config) -> None:
    online = replace(tiny_case.generators[0], startup_qualified_base=1)
    offline = replace(tiny_case.generators[1], shutdown_qualified_base=1)
    case = replace(tiny_case, generators=(online, offline))
    model = build_extensive_model(case, tiny_config)
    base = model.layout.states[0]
    assert model.column_upper[base.startup(0)] == 0.0
    assert model.column_upper[base.shutdown(1)] == 0.0
