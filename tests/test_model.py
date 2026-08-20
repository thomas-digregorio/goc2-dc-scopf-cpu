from __future__ import annotations

import numpy as np

from goc2_dc_scopf.checker import _check_physical, _objective
from goc2_dc_scopf.highs import solve_lexicographic, solve_pricing_lp
from goc2_dc_scopf.model import build_extensive_model
from goc2_dc_scopf.results import physical_arrays


def test_tiny_corrective_milp_and_pricing(tiny_case, tiny_config) -> None:
    model = build_extensive_model(tiny_case, tiny_config)
    milp = solve_lexicographic(model, tiny_config)
    pricing = solve_pricing_lp(model, tiny_config, milp.column_values)
    arrays = physical_arrays(model, milp.column_values)
    pricing_arrays = physical_arrays(model, pricing.column_values)
    violation, security = _check_physical(tiny_case, arrays, fixed_commitment=None)
    pricing_violation, pricing_security = _check_physical(
        tiny_case, pricing_arrays, fixed_commitment=arrays["commitment"]
    )
    assert violation.maximum <= 1e-7
    assert security.maximum <= 1e-7
    assert pricing_violation.maximum <= 1e-7
    assert pricing_security.maximum <= 1e-7
    assert abs(_objective(tiny_case, arrays) - milp.final_primary_objective) <= 1e-7
    assert abs(_objective(tiny_case, pricing_arrays) - pricing.objective) <= 1e-7

    commitment = np.rint(arrays["commitment"]).astype(int)
    assert commitment[0].tolist() == [1, 0]
    assert commitment[2].tolist() == [0, 1]
    assert arrays["generation_pu"][2, 1] == pytest.approx(1.0)


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


import pytest

