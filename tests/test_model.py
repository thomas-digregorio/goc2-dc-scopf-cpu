from __future__ import annotations

from dataclasses import asdict, replace

import numpy as np
import pytest

from goc2_dc_scopf.checker import _check_physical, _check_primary_solution, _objective
from goc2_dc_scopf.highs import solve_pricing_lp, solve_primary_milp
from goc2_dc_scopf.model import build_extensive_model
from goc2_dc_scopf.results import (
    build_primary_checkpoint,
    build_result_payload,
    physical_arrays,
)


def test_tiny_primary_milp_and_pricing(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    primary = solve_primary_milp(model, tiny_config)
    pricing = solve_pricing_lp(model, tiny_config, primary.column_values)
    arrays = physical_arrays(model, primary.column_values)
    pricing_arrays = physical_arrays(model, pricing.column_values)
    violation, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    pricing_violation, pricing_security = _check_physical(
        tiny_case, pricing_arrays, fixed_commitment=arrays["commitment"]
    )
    assert violation.maximum <= 1e-7
    assert security.maximum <= 1e-7
    assert pricing_violation.maximum <= 1e-7
    assert pricing_security.maximum <= 1e-7
    assert abs(_objective(tiny_case, arrays) - primary.objective) <= 1e-7
    assert abs(_objective(tiny_case, pricing_arrays) - pricing.objective) <= 1e-7

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
        {"path": "primary-primal.npz", "sha256": "artifact-hash", "bytes": 1},
        {"primary_milp": primary.primary.wall_seconds},
        1,
    )
    assert checkpoint["status"] == "primary_solved"
    assert checkpoint["run"] == {"cold_start": True, "initial_solution": "none"}
    assert "secondary" not in checkpoint["solver"]

    artifact = {"path": "artifact", "sha256": "hash", "bytes": 1}
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
    assert "secondary" not in payload["objectives"]


def test_primary_model_has_no_corrective_movement_auxiliaries(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    state_columns = sum(state.stop - state.offset for state in model.layout.states)
    segment_columns = sum(len(x) for x in model.layout.generator_segment_columns)
    segment_columns += sum(len(x) for x in model.layout.load_segment_columns)
    assert model.layout.num_columns == state_columns + segment_columns
    assert not hasattr(model, "secondary_cost")


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
