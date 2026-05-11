"""Pytest configuration: makes the repo root importable as ``streamlit_app.*``.

Allows ``uv run pytest streamlit_app/tests/ -v`` from the repo root without
installing ``streamlit_app`` as a package.  The repo's main pyproject.toml
declares its testpath at the top-level ``tests/`` directory; this file
extends that to cover the workbench tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
