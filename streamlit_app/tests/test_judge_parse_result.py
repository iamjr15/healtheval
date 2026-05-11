"""Unit tests for :class:`eval.judge_parse_result.JudgeParseResult`.

Codex r2 #3 contract: regardless of which branch fires, the result has
a populated ``score`` + ``rationale``, and ``parser_version`` truthfully
records which path produced it.
"""
from __future__ import annotations

import json

import pytest

from eval.judge_parse_result import JudgeParseResult


def test_v3_clean_payload_uses_v3_branch() -> None:
    """Pydantic-valid JSON → ``parser_version=='v3'`` + populated v3 fields."""
    raw = json.dumps(
        {
            "score": 4.5,
            "confidence": 0.8,
            "rubric_breakdown": {"score_4_anchor": 1.0},
            "failure_type": "missed_red_flag",
            "evidence": ["foo"],
            "reason": "ok",
        }
    )
    result = JudgeParseResult.parse(raw, "rendered prompt")
    assert result.parser_version == "v3"
    assert result.score == pytest.approx(4.5)
    assert result.rationale == "ok"
    assert result.confidence == pytest.approx(0.8)
    assert result.failure_type == "missed_red_flag"
    assert result.evidence == ["foo"]
    assert result.parsed_v3 is not None
    assert result.parsed_v3["score"] == pytest.approx(4.5)
    assert result.validation_errors == []
    assert result.rendered_judge_prompt == "rendered prompt"


def test_v1_shape_falls_back_cleanly() -> None:
    """Old `{score, rationale}` JSON triggers the v1 fallback branch.

    The Pydantic schema accepts ``score`` + an empty ``reason`` (defaults),
    so this actually validates — exercise the case where score is INTEGER
    in legacy form.  v3 rejects integer scores? Score is `float` with ge=1.0
    — Pydantic coerces; this should hit the v3 branch.  Use a malformed
    payload to force the fallback.
    """
    raw = json.dumps({"score": 6.0, "rationale": "judge ignored bounds"})
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v1_fallback"
    # v1 fallback clamps to [1, 5].
    assert result.score == pytest.approx(5.0)
    assert "judge ignored bounds" in result.rationale
    assert result.parsed_v3 is None
    assert result.validation_errors  # at least one validation message


def test_garbage_output_triggers_pure_fallback() -> None:
    """No JSON at all → score defaults to 1.0 (worst Likert) per v1 contract."""
    result = JudgeParseResult.parse("the judge had a bad day", "rp")
    assert result.parser_version == "v1_fallback"
    assert result.score == pytest.approx(1.0)
    assert "unparseable" in result.rationale
    assert result.parsed_v3 is None
    assert result.validation_errors  # documents what went wrong


def test_empty_raw_treated_as_score_one() -> None:
    """Empty judge output → conservative score=1.0 with a clear rationale."""
    result = JudgeParseResult.parse("", "rp")
    assert result.parser_version == "v1_fallback"
    assert result.score == pytest.approx(1.0)
    assert "empty" in result.rationale.lower()


def test_score_clamped_to_likert_range() -> None:
    """v1 fallback clamps to 1..5 even when the judge emits a wild number."""
    raw = json.dumps({"score": -3.0, "rationale": "judge below floor"})
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v1_fallback"
    assert result.score == pytest.approx(1.0)


def test_v3_payload_in_markdown_fence_parses_cleanly() -> None:
    """Live regression: judges fence v3 JSON in ```json ... ``` despite 'JSON only' instruction.

    Reported by deploy-eng during the v3 STRETCH run — 100% of cells
    were dropping to v1_fallback because the parser couldn't get past
    the fence.  The fence stripper plus brace-balanced raw_decode now
    handles it.
    """
    raw = (
        "```json\n"
        '{"score": 4.0, "confidence": 0.7, '
        '"rubric_breakdown": {"score_4_anchor": 0.6, "score_5_anchor": 0.4}, '
        '"failure_type": null, "evidence": ["108 named"], "reason": "ok"}'
        "\n```"
    )
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v3", (
        f"expected v3 path; got {result.parser_version}; "
        f"errors={result.validation_errors}"
    )
    assert result.score == pytest.approx(4.0)
    assert result.rationale == "ok"
    assert result.confidence == pytest.approx(0.7)
    assert result.rubric_breakdown == {"score_4_anchor": 0.6, "score_5_anchor": 0.4}
    assert result.evidence == ["108 named"]
    assert result.failure_type is None


def test_v3_with_natural_language_preamble_then_fenced_json() -> None:
    """Some judges emit a sentence then the fenced JSON — extract anyway."""
    raw = (
        "Here's the score:\n\n"
        "```json\n"
        '{"score": 3.5, "confidence": 0.5, "rubric_breakdown": {"a": 1.0}, "reason": "mid"}\n'
        "```"
    )
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v3"
    assert result.score == pytest.approx(3.5)


def test_v3_unfenced_with_nested_object_uses_brace_balanced_extractor() -> None:
    """v3 JSON without fences but with nested rubric_breakdown — the v1
    regex (\\{[^{}]*"score"[^{}]*\\}) can't match across nested braces;
    the brace-balanced extractor must rescue it.
    """
    raw = '{"score": 2.0, "rubric_breakdown": {"x": 0.5, "y": 0.5}, "reason": "low"}'
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v3"
    assert result.score == pytest.approx(2.0)
    assert result.rubric_breakdown == {"x": 0.5, "y": 0.5}


def test_v3_json_with_trailing_commentary_strips_to_first_object() -> None:
    """Judge sometimes appends explanatory text after the JSON; we should
    still extract the first balanced object.
    """
    raw = (
        '{"score": 5.0, "confidence": 1.0, "rubric_breakdown": {}, "reason": "perfect"}'
        "\n\nThis was a clean response."
    )
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v3"
    assert result.score == pytest.approx(5.0)


def test_v3_payload_with_braces_in_string_literal() -> None:
    """A judge rationale containing literal braces must not break extraction."""
    raw = (
        '{"score": 4.0, "rubric_breakdown": {"a": 1.0}, '
        '"reason": "model said {triage_label} = RED"}'
    )
    result = JudgeParseResult.parse(raw, "rp")
    assert result.parser_version == "v3"
    assert result.score == pytest.approx(4.0)
    assert "{triage_label}" in result.rationale


def test_to_trace_row_shape() -> None:
    """Trace-row keys match the dashboard's JudgeTraceRow contract."""
    raw = json.dumps({"score": 4.0, "reason": "fine"})
    result = JudgeParseResult.parse(raw, "rendered prompt body")
    row = result.to_trace_row(
        prompt_id="ref-001",
        judge_model="anthropic-claude-sonnet-4-6",
        principle_id=3,
        rubric_version="mnh_safety_v1",
        prompt_template_version="v3",
        dataset_version="reference_set_v2",
        strategy_version="v3_with_retrieval",
        calibration_example_ids=["cal-mnh-safety-001", "cal-mnh-safety-002"],
        cache_key="abc123",
        timestamp_iso="2026-05-10T20:30:00+00:00",
        duration_sec=1.23,
        temperature=0.1,
        seed=42,
    )
    assert row["prompt_id"] == "ref-001"
    assert row["judge_model"] == "anthropic-claude-sonnet-4-6"
    assert row["principle_id"] == 3
    assert row["rubric_version"] == "mnh_safety_v1"
    assert row["prompt_template_version"] == "v3"
    assert row["dataset_version"] == "reference_set_v2"
    assert row["strategy_version"] == "v3_with_retrieval"
    assert row["calibration_example_ids"] == [
        "cal-mnh-safety-001",
        "cal-mnh-safety-002",
    ]
    assert row["cache_key"] == "abc123"
    assert row["temperature"] == pytest.approx(0.1)
    assert row["seed"] == 42
    assert row["score"] == pytest.approx(4.0)
    assert row["rationale"] == "fine"
    assert row["parser_version"] == "v3"
    assert row["rendered_judge_prompt"] == "rendered prompt body"
    assert row["timestamp"] == "2026-05-10T20:30:00+00:00"
    assert row["duration_sec"] == pytest.approx(1.23)
