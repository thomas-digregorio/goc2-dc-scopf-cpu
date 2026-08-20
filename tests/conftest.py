from __future__ import annotations

import math

import pytest

from goc2_dc_scopf.source import (
    Branch,
    Bus,
    CaseData,
    Contingency,
    CostSegment,
    Generator,
    Load,
)


@pytest.fixture
def tiny_case() -> CaseData:
    buses = (Bus(0, 1, "A"), Bus(1, 2, "B"), Bus(2, 3, "C"))
    loads = (
        Load(
            0,
            (3, "1"),
            2,
            1.0,
            1.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            (CostSegment(1.0, 100.0, 0),),
        ),
    )
    generators = (
        Generator(
            0,
            (1, "1"),
            0,
            1,
            1.0,
            0.2,
            1.5,
            2.0,
            2.0,
            2.0,
            2.0,
            0,
            1,
            0,
            1,
            1.0,
            5.0,
            2.0,
            (CostSegment(1.5, 10.0, 0),),
        ),
        Generator(
            1,
            (2, "1"),
            1,
            0,
            0.0,
            0.1,
            1.2,
            2.0,
            2.0,
            2.0,
            2.0,
            1,
            0,
            1,
            1,
            1.0,
            5.0,
            2.0,
            (CostSegment(1.2, 20.0, 0),),
        ),
    )
    branches = (
        Branch(0, (1, 2, "1"), "line", 0, 1, 0.1, 1.0, 0.0, 2.0, 2.0),
        Branch(1, (2, 3, "1"), "line", 1, 2, 0.1, 1.0, 0.0, 2.0, 2.0),
        Branch(2, (1, 3, "1"), "transformer", 0, 2, 0.1, 1.0, math.radians(1), 2.0, 2.0),
    )
    contingencies = (
        Contingency(0, "BRANCH", "branch", 0, None, ("(1, 2, '1')",)),
        Contingency(1, "GENERATOR", "generator", None, 0, ("(1, '1')",)),
    )
    return CaseData(
        "tiny",
        "tiny/scenario",
        100.0,
        1.0,
        1.0,
        1.0,
        buses,
        loads,
        generators,
        branches,
        (),
        contingencies,
        {},
        "tiny",
        "tiny",
        (),
    )


@pytest.fixture
def tiny_config() -> dict:
    return {
        "solver": {
            "mip_relative_gap": 1e-6,
            "mip_absolute_gap": 0.0,
            "time_limit_seconds": 30,
            "threads": 1,
            "random_seed": 0,
            "presolve": "on",
            "primal_feasibility_tolerance": 1e-7,
            "dual_feasibility_tolerance": 1e-7,
            "mip_feasibility_tolerance": 1e-6,
            "console_logging": False,
        },
        "numerics": {
            "model_residual_tolerance_pu": 1e-6,
            "security_violation_tolerance_pu": 1e-5,
            "integrality_tolerance": 1e-6,
        },
    }
