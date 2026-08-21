from __future__ import annotations

import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator

from goc2_dc_scopf.ablation import factors, validate_cell
from goc2_dc_scopf.cli import DEFAULT_CONFIG
from goc2_dc_scopf.paths import configure_linear_algebra_runtime


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_default_configuration_is_certified_dt_profile() -> None:
    root = Path(__file__).parents[1]
    assert DEFAULT_CONFIG == "configs/GOC2-DC-D1-CORRECTIVE-v2-617-dt-default.json"
    config = _load(root / DEFAULT_CONFIG)
    schema = _load(root / "schemas" / "config.schema.json")
    Draft202012Validator(schema).validate(config)
    validate_cell(config)

    assert factors(config) == {
        "decomposition": True,
        "internal_incumbent": False,
        "strong_valid_cuts": False,
        "solver_tuning": True,
    }
    assert config["solver"]["mip_relative_gap"] == 1e-3
    assert config["run_budget"]["end_to_end_limit_seconds"] == 1800
    assert config["result_directory"] == "results/default-617-dt"
    assert config["solver"]["pricing_hot_start_required"] is False


def test_dt_default_applies_thread_policy_before_solver_import(monkeypatch) -> None:
    root = Path(__file__).parents[1]
    config = _load(root / DEFAULT_CONFIG)
    names = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    for name in names:
        monkeypatch.delenv(name, raising=False)

    applied = configure_linear_algebra_runtime(config)

    assert applied == {name: "1" for name in names}
    assert {name: os.environ[name] for name in names} == applied


def test_explicit_extensive_baseline_does_not_override_thread_environment(monkeypatch) -> None:
    root = Path(__file__).parents[1]
    baseline = _load(
        root / "configs" / "GOC2-DC-D1-CORRECTIVE-v2-617-simplex-fresh-pricing.json"
    )
    names = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    for name in names:
        monkeypatch.setenv(name, "7")

    assert configure_linear_algebra_runtime(baseline) == {}
    assert {name: os.environ[name] for name in names} == {name: "7" for name in names}
