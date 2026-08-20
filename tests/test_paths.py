from pathlib import Path

import pytest

from goc2_dc_scopf.paths import PathPolicyError, require_local_path


def test_onedrive_is_refused() -> None:
    with pytest.raises(PathPolicyError):
        require_local_path(Path("C:/Users/example/OneDrive/output.json"), "output")


def test_physical_documents_path_is_allowed() -> None:
    value = require_local_path(Path("C:/Users/example/Documents/output.json"), "output")
    assert "onedrive" not in str(value).casefold()

