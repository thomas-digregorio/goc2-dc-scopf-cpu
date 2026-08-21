from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from goc2_dc_scopf.ablation import factors, validate_cell
from goc2_dc_scopf.source import _verify_manifest_identity


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_2020_registration_uses_same_dt_profile_and_separate_outputs() -> None:
    root = Path(__file__).parents[1]
    config = _load(root / "configs" / "GOC2-DC-D1-CORRECTIVE-v2-2020-dt.json")
    schema = _load(root / "schemas" / "config.schema.json")
    manifest = _load(root / "docs" / "source-manifest-2020.json")

    Draft202012Validator(schema).validate(config)
    validate_cell(config)
    _verify_manifest_identity(config, manifest)

    assert config["scenario"] == "C2S7N02020/scenario_001"
    assert config["run_budget"]["end_to_end_limit_seconds"] == 1800
    assert config["result_directory"] == "results/default-2020-dt"
    assert factors(config) == {
        "decomposition": True,
        "internal_incumbent": False,
        "strong_valid_cuts": False,
        "solver_tuning": True,
    }


def test_manifest_identity_rejects_cross_case_configuration() -> None:
    config = {"profile": "GOC2-DC-D1-CORRECTIVE-v2", "scenario": "case/a"}
    manifest = {
        "profile": "GOC2-DC-D1-CORRECTIVE-v2",
        "scenario": {"archive_directory": "case/b"},
    }
    with pytest.raises(ValueError, match="scenario"):
        _verify_manifest_identity(config, manifest)
