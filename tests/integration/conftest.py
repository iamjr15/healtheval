"""Shared fixtures for integration tests.

Integration tests are slower than smoke (the <60s budget does NOT apply)
and they assume data-spec + eval-core have shipped — i.e. they should
run AFTER the smoke gate is green, not as a precondition for it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
