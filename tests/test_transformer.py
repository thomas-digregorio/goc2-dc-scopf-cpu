from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from goc2_dc_scopf.model import build_extensive_model
from goc2_dc_scopf.source import _interpolate_impedance_correction


def test_impedance_correction_interpolation() -> None:
    table = SimpleNamespace(t=[0.9, 1.0, 1.1, None], f=[0.8, 1.0, 1.4, None])
    assert _interpolate_impedance_correction(0.95, table) == pytest.approx(0.9)
    assert _interpolate_impedance_correction(0.5, table) == pytest.approx(0.8)
    assert _interpolate_impedance_correction(1.5, table) == pytest.approx(1.4)


def test_dc_flow_row_uses_effective_reactance(tiny_case, tiny_config) -> None:
    corrected = replace(tiny_case.branches[2], impedance_correction_factor=0.5)
    case = replace(tiny_case, branches=(*tiny_case.branches[:2], corrected))
    model = build_extensive_model(case, tiny_config)
    base = model.layout.states[0]
    starts, indices, values, lower, upper = model.rows.numpy_buffers()
    expected = 1.0 / (corrected.reactance_pu * 0.5 * corrected.tap_magnitude)
    matching = []
    for row in range(model.rows.num_rows):
        lo, hi = starts[row], starts[row + 1]
        pairs = dict(zip(indices[lo:hi].tolist(), values[lo:hi].tolist(), strict=True))
        if pairs.get(base.flow(2)) == 1.0 and base.theta(0) in pairs and base.theta(2) in pairs:
            matching.append((pairs, lower[row], upper[row]))
    assert len(matching) == 1
    pairs, row_lower, row_upper = matching[0]
    assert pairs[base.theta(0)] == pytest.approx(-expected)
    assert pairs[base.theta(2)] == pytest.approx(expected)
    assert row_lower == pytest.approx(-expected * corrected.phase_shift_rad)
    assert row_upper == pytest.approx(row_lower)

