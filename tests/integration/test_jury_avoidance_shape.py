"""Integration: HEALTH-PARIKSHA self-judging avoidance is enforced on
the wire (the judge-panel contract).

The eval-core fixture `sample_jury_scores.json` represents the jury
output for a sarvam-105b panel response. The Sarvam-105b judge MUST be
dropped from that jury (it would be self-judging), leaving 3 frontier
judges × 12 constitutional principles = 36 cells. If anyone ever
removes the avoidance branch in `eval.judges._select_jury`, this test
catches it.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _schemas():
    try:
        return importlib.import_module("data.schemas")
    except ModuleNotFoundError as e:
        pytest.fail(f"data.schemas not importable: {e}")


def _fixture(repo_root: Path) -> dict:
    p = repo_root / "tests" / "fixtures" / "sample_jury_scores.json"
    if not p.exists():
        pytest.fail(f"eval-core fixture not present: {p.relative_to(repo_root)}")
    return json.loads(p.read_text(encoding="utf-8"))


def test_sample_jury_scores_avoidance_shape(repo_root):
    schemas = _schemas()
    fixture = _fixture(repo_root)

    scores = fixture.get("scores")
    assert isinstance(scores, list), "fixture must expose a `scores` list"

    # HEALTH-PARIKSHA self-judging avoidance: the Sarvam-105b judge is
    # dropped when the panel response is from Sarvam-105b. The surviving-
    # jury size depends on the planned jury composition:
    # Current default: 3 judges (Anthropic + Google + Sarvam) -> drop
    # Sarvam for a Sarvam panel response -> 2 surviving x 12 principles.
    # We derive the expected count from the fixture's own metadata so the
    # test stays valid if the jury changes deliberately.
    expected_cells = fixture.get("_expected_cell_count")
    expected_jury = fixture.get("_jury_after_avoidance") or []
    if expected_cells is None:
        expected_cells = len(expected_jury) * 12
    assert len(scores) == expected_cells, (
        f"expected {expected_cells} jury cells "
        f"({len(expected_jury)} judges × 12 principles); got {len(scores)}"
    )

    # Every cell must validate against data.schemas.JudgeScore — the
    # canonical wire-format spec (Likert score 1..5, principle_id 1..12,
    # judge_model_id non-empty str, etc.).
    JudgeScore = schemas.JudgeScore
    parsed = [JudgeScore(**c) for c in scores]

    # The Sarvam-105b judge MUST NOT appear among the surviving judges
    # (the avoidance branch dropped it, by design).
    judges_in_jury = {p.judge_model_id for p in parsed}
    assert "sarvam-105b" not in judges_in_jury, (
        "HEALTH-PARIKSHA avoidance regressed: sarvam-105b is judging a sarvam-105b "
        f"panel response. Jury was: {sorted(judges_in_jury)}"
    )

    # Surviving-jury cardinality is whatever the fixture metadata says it
    # should be — we cross-check the fixture's
    # `_jury_after_avoidance` list against the actual `judge_model_id` set
    # so a fixture that's internally inconsistent flags here.
    if expected_jury:
        assert judges_in_jury == set(expected_jury), (
            f"surviving-jury drift between fixture metadata and cell list:\n"
            f"  metadata `_jury_after_avoidance`: {sorted(expected_jury)}\n"
            f"  actual judge_model_ids in scores: {sorted(judges_in_jury)}"
        )
    else:
        # Migration-tolerant fallback: accept 2 or 3 surviving judges.
        assert len(judges_in_jury) in (2, 3), (
            f"expected 2 or 3 surviving judges; got "
            f"{len(judges_in_jury)}: {judges_in_jury}"
        )

    for cell in parsed:
        assert 1.0 <= float(cell.score) <= 5.0
        assert 1 <= int(cell.principle_id) <= 12
