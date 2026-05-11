"""Pydantic-validation tests for :class:`eval.judge_schema.JudgeOutputV3`.

The v3 judge schema is the internal contract
the v3 judge prompt asks the LLM to fill out.  These tests pin its
behaviour so a future refactor doesn't quietly relax a guard rail.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eval.judge_schema import JudgeOutputV3


def test_minimal_valid_payload() -> None:
    """Score in-band; everything else falls back to defaults."""
    out = JudgeOutputV3.model_validate({"score": 4.0})
    assert out.score == pytest.approx(4.0)
    assert out.confidence == pytest.approx(1.0)
    assert out.rubric_breakdown == {}
    assert out.failure_type is None
    assert out.evidence == []
    assert out.reason == ""


def test_full_v3_payload_round_trips() -> None:
    """All v3 fields populate; ``model_dump()`` re-serialises cleanly."""
    payload = {
        "score": 4.5,
        "confidence": 0.75,
        "rubric_breakdown": {"score_4_anchor": 0.6, "score_5_anchor": 0.4},
        "failure_type": "missed_red_flag",
        "evidence": ["108 helpline named", "respectful register"],
        "reason": "Strong principle-3 anchor; missed explicit MoHFW citation.",
    }
    out = JudgeOutputV3.model_validate(payload)
    dumped = out.model_dump()
    assert dumped["score"] == pytest.approx(4.5)
    assert dumped["confidence"] == pytest.approx(0.75)
    assert dumped["rubric_breakdown"]["score_4_anchor"] == pytest.approx(0.6)
    assert dumped["failure_type"] == "missed_red_flag"
    assert dumped["evidence"] == ["108 helpline named", "respectful register"]
    assert dumped["reason"].startswith("Strong principle-3 anchor")


@pytest.mark.parametrize("bad_score", [0.0, 0.99, 5.01, 6.0, -1.0])
def test_score_out_of_range_rejected(bad_score: float) -> None:
    """Score must satisfy 1.0 ≤ score ≤ 5.0 — anything else → ValidationError."""
    with pytest.raises(ValidationError):
        JudgeOutputV3.model_validate({"score": bad_score})


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.5, 2.0])
def test_confidence_out_of_range_rejected(bad_confidence: float) -> None:
    """Confidence must satisfy 0.0 ≤ confidence ≤ 1.0."""
    with pytest.raises(ValidationError):
        JudgeOutputV3.model_validate({"score": 3.0, "confidence": bad_confidence})


def test_extra_fields_ignored_not_rejected() -> None:
    """``extra="ignore"`` keeps a noisy judge from triggering hard failures."""
    out = JudgeOutputV3.model_validate(
        {"score": 3.0, "rubric_breakdown": {}, "spurious_field": "noise"}
    )
    assert out.score == pytest.approx(3.0)
    assert "spurious_field" not in out.model_dump()


def test_missing_score_is_required() -> None:
    """``score`` has no default — must be present."""
    with pytest.raises(ValidationError):
        JudgeOutputV3.model_validate({"reason": "no score given"})
