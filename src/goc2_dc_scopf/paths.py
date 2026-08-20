from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


class PathPolicyError(RuntimeError):
    """Raised when a path violates the physical-local-storage policy."""


def require_local_path(path: str | Path, purpose: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if "onedrive" in str(resolved).casefold():
        raise PathPolicyError(f"Refusing {purpose} path containing OneDrive: {resolved}")
    return resolved


def repo_root() -> Path:
    return require_local_path(Path(__file__).resolve().parents[2], "repository")


def resolve_from(root: Path, value: str | Path, purpose: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    return require_local_path(candidate, purpose)


def configure_local_runtime(root: Path) -> Path:
    """Force process scratch/cache paths below the physical-local repository."""
    root = require_local_path(root, "repository")
    require_local_path(sys.prefix, "Python environment")
    scratch = require_local_path(root / ".tmp", "temporary")
    scratch.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR", "XDG_CACHE_HOME"):
        os.environ[name] = str(scratch)
    sys.pycache_prefix = str(require_local_path(scratch / "pycache", "bytecode cache"))
    return scratch


def sha256_file(path: Path, chunk_bytes: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected a JSON object in {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path = require_local_path(path, "JSON output")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = require_local_path(path.with_suffix(path.suffix + ".tmp"), "temporary JSON")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)
