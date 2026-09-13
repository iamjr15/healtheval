"""Integration tests for the v3 opt-in surface on :func:`eval.judges.judge_panel`.

Codex r2 #3 contract: passing v3 kwargs MUST NOT change the public
``JudgeScore`` shape — v3 metadata lives only in the trace row written
via ``trace_writer``.

These tests stub the vendor-call helpers so no network I/O happens; they
verify (a) the public list-of-JudgeScore signature is preserved, (b) the
trace writer is called once per (judge, principle) cell, (c) trace rows
carry the expected metadata, and (d) the rubric_pack_version + retrieval
flags propagate into the judge prompt.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import eval.judges as judges_mod
from eval.judges import (
    JudgeConfig,
    judge_panel,
    make_jsonl_trace_writer,
)
# Fixtures: a one-judge stub jury + a 2-principle constitution + a fake
# ``_safe_call_judge`` that returns a fixed JSON payload, so we can exercise
# the end-to-end ``judge_panel`` flow without any vendor SDK calls.
_STUB_JURY = (JudgeConfig("test-judge-1", "anthropic", "test-judge-1", "anthropic"),)


_STUB_CONSTITUTION = [
    {
        "id": 1,
        "name": "stub_principle_1",
        "description": "test",
        "scoring_rubric": {"score_1": "x", "score_5": "y"},
    },
    {
        "id": 3,
        "name": "stub_principle_3",
        "description": "test",
        "scoring_rubric": {"score_1": "x", "score_5": "y"},
    },
]


def _v3_payload() -> str:
    return json.dumps(
        {
            "score": 4.0,
            "confidence": 0.7,
            "rubric_breakdown": {"score_4_anchor": 1.0},
            "failure_type": None,
            "evidence": [],
            "reason": "stub",
        }
    )


def _v1_payload() -> str:
    return json.dumps({"score": 4.0, "rationale": "stub"})


def test_v1_legacy_call_returns_judge_scores_with_no_trace_kwargs() -> None:
    """No v3 kwargs → returns a list of JudgeScore-shaped objects, no trace."""
    with patch.object(judges_mod, "_safe_call_judge", return_value=_v1_payload()):
        scores = judge_panel(
            prompt="कोई प्रश्न",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
        )
    # 1 judge × 2 principles = 2 cells.
    assert len(scores) == 2
    for cell in scores:
        # Both Pydantic + dataclass shapes expose these attributes.
        assert hasattr(cell, "judge_model_id")
        assert hasattr(cell, "principle_id")
        assert hasattr(cell, "score")
        assert hasattr(cell, "rationale")
        assert cell.judge_model_id == "test-judge-1"
        assert cell.score == pytest.approx(4.0)


def test_trace_writer_called_once_per_cell(tmp_path: Path) -> None:
    """``trace_writer`` fires once per (judge × principle) cell."""
    captured: list[dict[str, Any]] = []
    trace_path = tmp_path / "judge_trace.jsonl"
    writer = make_jsonl_trace_writer(trace_path)

    def _capture(row: dict[str, Any]) -> None:
        captured.append(row)
        writer(row)

    with patch.object(judges_mod, "_safe_call_judge", return_value=_v3_payload()):
        scores = judge_panel(
            prompt="कोई प्रश्न",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="health_safety_v1",
            retrieve_calibration=False,
            trace_writer=_capture,
            prompt_id="ref-001",
            prompt_template_version="v3",
            dataset_version="reference_set_v2",
            strategy_version="v3_with_retrieval",
        )

    assert len(scores) == 2
    assert len(captured) == 2

    # JSONL on disk should contain the same 2 lines.
    assert trace_path.exists()
    lines = [line for line in trace_path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    for row in parsed:
        assert row["prompt_id"] == "ref-001"
        assert row["judge_model"] == "test-judge-1"
        assert row["rubric_version"] == "health_safety_v1"
        assert row["prompt_template_version"] == "v3"
        assert row["strategy_version"] == "v3_with_retrieval"
        assert row["score"] == pytest.approx(4.0)
        assert row["parser_version"] == "v3"
        assert row["principle_id"] in {1, 3}
        assert "cache_key" in row
        assert "timestamp" in row


def test_v3_judgescore_shape_unchanged_when_trace_writer_set() -> None:
    """JudgeScore has no v3 fields — they MUST land only in the trace row."""
    captured: list[dict[str, Any]] = []
    with patch.object(judges_mod, "_safe_call_judge", return_value=_v3_payload()):
        scores = judge_panel(
            prompt="कोई प्रश्न",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="health_safety_v1",
            trace_writer=captured.append,
            prompt_id="ref-001",
        )
    for cell in scores:
        # No v3 metadata leaked onto the public score row.
        assert not hasattr(cell, "confidence") or getattr(cell, "confidence", None) is None
        assert not hasattr(cell, "rubric_breakdown") or getattr(cell, "rubric_breakdown", None) in (None, {})
        assert not hasattr(cell, "failure_type") or getattr(cell, "failure_type", None) is None
        assert not hasattr(cell, "evidence") or getattr(cell, "evidence", None) in (None, [])
    # But the trace row DOES have them.
    for row in captured:
        assert "confidence" in row
        assert "rubric_breakdown" in row
        assert "failure_type" in row
        assert "evidence" in row


def test_failed_judge_call_still_writes_trace_row() -> None:
    """A None-returning judge call → trace row with parser_version=v1_fallback."""
    captured: list[dict[str, Any]] = []
    with patch.object(judges_mod, "_safe_call_judge", return_value=None):
        judge_panel(
            prompt="x",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="health_safety_v1",
            trace_writer=captured.append,
            prompt_id="ref-099",
        )
    assert len(captured) == 2
    for row in captured:
        assert row["parser_version"] == "v1_fallback"
        assert row["score"] == pytest.approx(1.0)
        assert "judge call failed" in row["rationale"]


def test_rubric_pack_version_appears_in_judge_prompt() -> None:
    """When ``rubric_pack_version`` is set, the rendered prompt includes it."""
    captured: list[dict[str, Any]] = []
    with patch.object(judges_mod, "_safe_call_judge", return_value=_v3_payload()):
        judge_panel(
            prompt="x",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="factuality_v1",
            trace_writer=captured.append,
            prompt_id="ref-001",
        )
    for row in captured:
        assert "Rubric pack: factuality_v1" in row["rendered_judge_prompt"]


def test_calibration_retrieval_emits_anchor_ids() -> None:
    """retrieve_calibration=True → trace row carries the calibration_example_ids list."""
    captured: list[dict[str, Any]] = []
    with patch.object(judges_mod, "_safe_call_judge", return_value=_v3_payload()):
        judge_panel(
            prompt="दवा लेकर खुद इलाज",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="health_safety_v1",
            retrieve_calibration=True,
            calibration_k=2,
            trace_writer=captured.append,
            prompt_id="ref-009",
        )
    assert captured
    for row in captured:
        # n_cells × calibration_k entries per cell — each row should carry IDs.
        assert isinstance(row["calibration_example_ids"], list)
        assert all(isinstance(x, str) for x in row["calibration_example_ids"])
        # The anchors block should be in the rendered prompt.
        assert "Retrieved calibration anchors" in row["rendered_judge_prompt"]


def test_trace_row_duration_sec_is_real_wall_clock_time() -> None:
    """Regression: ``_emit_trace_row`` previously hard-coded duration_sec=0.0.

    Reported by page-builder-C / page-builder-B during the v3 STRETCH
    run.  Now ``judge_panel`` wraps the ``_safe_call_judge`` invocation
    with ``time.perf_counter()`` and threads the elapsed value through
    ``_emit_trace_row`` so the trace records real latency.
    """
    captured: list[dict[str, Any]] = []

    def _slow_judge_call(judge: Any, prompt: str) -> str:
        # Sleep 5 ms so duration_sec is meaningfully non-zero.
        import time as _time

        _time.sleep(0.005)
        return _v3_payload()

    with patch.object(judges_mod, "_safe_call_judge", side_effect=_slow_judge_call):
        judge_panel(
            prompt="x",
            response_dict={"response": "स्टब", "triage_json": {"triage_label": "GREEN"}},
            panel_model_id="some-panel-model",
            jury=_STUB_JURY,
            constitution=_STUB_CONSTITUTION,
            rubric_pack_version="health_safety_v1",
            trace_writer=captured.append,
            prompt_id="ref-001",
        )
    assert captured
    for row in captured:
        # Real timing — must be > 0 and reasonable (< 1s for a stubbed call).
        assert row["duration_sec"] > 0.0, (
            f"duration_sec was not measured: row={row['duration_sec']}"
        )
        assert row["duration_sec"] < 1.0, "stubbed call should never take 1s+"


def test_make_jsonl_trace_writer_creates_parent_dir(tmp_path: Path) -> None:
    """Writer should make missing parent directories so a clean run never crashes."""
    target = tmp_path / "deeply" / "nested" / "trace.jsonl"
    writer = make_jsonl_trace_writer(target)
    writer({"hello": "world"})
    assert target.exists()
    assert json.loads(target.read_text().strip()) == {"hello": "world"}
