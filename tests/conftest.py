"""Shared fixtures for phaicaid tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure the SDK package is importable.
_pydaemon_dir = str(Path(__file__).resolve().parent.parent / "templates" / "pydaemon")
if _pydaemon_dir not in sys.path:
    sys.path.insert(0, _pydaemon_dir)


@pytest.fixture()
def tmp_runtime(tmp_path: Path) -> Path:
    """Create a temporary runtime directory with hooks/ and run/ subdirs."""
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    return tmp_path
