"""Shared fixtures for the v1.5.3 foundation smoke gate.

These fixtures keep tests offline (the reproducibility gate non-negotiable: <60s, no
network) and make the repo root importable as a flat package layout
regardless of pytest invocation cwd.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


# Make repository top-level packages (`data`, `eval`, ...) importable as
# bare modules — they live at repo root rather than inside a src/ layout.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root, regardless of pytest invocation cwd."""
    return REPO_ROOT
