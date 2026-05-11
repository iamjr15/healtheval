"""Tests for script argument surfaces used by the dashboard evidence flow."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _ensure_repo_on_path() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
# scripts.compute_panel_tool_meta
def test_compute_panel_tool_meta_argparse_defaults() -> None:
    mod = importlib.import_module("scripts.compute_panel_tool_meta")
    args = mod._parse_args([])
    assert args.panel.name == "methodology_panel_refset_eval.json"
    assert args.output.name == "tool_meta_evaluation.json"


def test_compute_panel_tool_meta_argparse_custom_paths() -> None:
    mod = importlib.import_module("scripts.compute_panel_tool_meta")
    args = mod._parse_args(
        [
            "--panel",
            "results/custom_panel.json",
            "--output",
            "results/custom_tool_meta.json",
        ]
    )
    assert args.panel == Path("results/custom_panel.json")
    assert args.output == Path("results/custom_tool_meta.json")
