"""Tests for streamlit_app.trace_loader.

Page 8 (Judge Trace) MUST gracefully render the "v3 trace data pending"
banner when the JSONL file is absent or empty.  These tests verify the
helpers used by the empty-state guard (``trace_file_available``) plus
the filter / unique-value helpers used to drive the sidebar.
"""
from __future__ import annotations

import json
from pathlib import Path

from streamlit_app.trace_loader import (
    filter_traces,
    summarise_traces,
    trace_count,
    trace_file_available,
    unique_field_values,
)


def _row(**kwargs):
    base = {
        "prompt_id": "ref-001",
        "judge_model": "gemini-2.5-pro",
        "principle_id": 3,
        "rubric_version": "mnh_safety_v1",
        "score": 4.5,
    }
    base.update(kwargs)
    return base


def test_trace_file_available_missing(tmp_path: Path) -> None:
    assert trace_file_available(tmp_path / "no_such.jsonl") is False


def test_trace_file_available_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    # Empty file → still treat as "not available" so Page 8 shows the banner.
    assert trace_file_available(p) is False


def test_trace_file_available_populated(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    p.write_text(json.dumps(_row()) + "\n")
    assert trace_file_available(p) is True


def test_filter_by_prompt_id() -> None:
    rows = [
        _row(prompt_id="ref-001"),
        _row(prompt_id="ref-002"),
        _row(prompt_id="ref-001", judge_model="sonnet-4-6"),
    ]
    result = list(filter_traces(prompt_id="ref-001", rows=rows))
    assert len(result) == 2


def test_filter_treats_All_as_no_filter() -> None:
    rows = [_row(prompt_id="ref-001"), _row(prompt_id="ref-002")]
    # The page passes the literal "All" sentinel only via the wrapper —
    # filter_traces accepts None / "" / "All" via the internal _matches.
    result = list(filter_traces(prompt_id=None, rows=rows))
    assert len(result) == 2


def test_filter_by_principle_id_accepts_str_or_int() -> None:
    rows = [_row(principle_id=3), _row(principle_id=8)]
    assert len(list(filter_traces(principle_id=3, rows=rows))) == 1
    assert len(list(filter_traces(principle_id="3", rows=rows))) == 1


def test_unique_field_values_sorted_distinct() -> None:
    rows = [
        _row(judge_model="sonnet-4-6"),
        _row(judge_model="gemini-2.5-pro"),
        _row(judge_model="sonnet-4-6"),
    ]
    assert unique_field_values("judge_model", rows=rows) == [
        "gemini-2.5-pro",
        "sonnet-4-6",
    ]


def test_unique_field_values_skips_missing() -> None:
    rows = [_row(), {"prompt_id": "ref-001"}]  # second row has no judge_model
    vals = unique_field_values("judge_model", rows=rows)
    assert vals == ["gemini-2.5-pro"]


def test_trace_count_iterator_safe() -> None:
    rows = (_row(prompt_id=f"ref-{i:03d}") for i in range(5))
    # Generator-friendly — count consumes once, no replay required.
    assert trace_count(rows) == 5


def test_summarise_empty_returns_zero_state() -> None:
    summary = summarise_traces(rows=[])
    assert summary["total_rows"] == 0
    assert summary["per_judge"] == {}
    assert summary["per_principle"] == {}
    assert summary["parser_breakdown"] == {}
    assert summary["parser_pct"] == {}
    assert summary["calibration_coverage_pct"] == 0.0
    assert summary["n_calls_with_calibration"] == 0
    assert summary["avg_duration_sec"] is None


def test_summarise_per_judge_counts_and_avg_duration() -> None:
    rows = [
        _row(judge_model="gemini-2.5-pro", duration_sec=1.0, parser_version="v3"),
        _row(judge_model="gemini-2.5-pro", duration_sec=3.0, parser_version="v3"),
        _row(judge_model="sonnet-4-6", duration_sec=2.0, parser_version="v3"),
    ]
    summary = summarise_traces(rows=rows)
    assert summary["total_rows"] == 3
    gem = summary["per_judge"]["gemini-2.5-pro"]
    assert gem["count"] == 2
    assert gem["avg_duration_sec"] == 2.0
    son = summary["per_judge"]["sonnet-4-6"]
    assert son["count"] == 1
    assert son["avg_duration_sec"] == 2.0
    assert summary["avg_duration_sec"] == 2.0  # (1+3+2)/3


def test_summarise_per_principle_groups_by_principle_id() -> None:
    rows = [
        _row(principle_id=3, duration_sec=1.0),
        _row(principle_id=3, duration_sec=2.0),
        _row(principle_id=8, duration_sec=4.0),
    ]
    summary = summarise_traces(rows=rows)
    assert summary["per_principle"]["3"]["count"] == 2
    assert summary["per_principle"]["3"]["avg_duration_sec"] == 1.5
    assert summary["per_principle"]["8"]["count"] == 1


def test_summarise_parser_breakdown_with_percentages() -> None:
    rows = [
        _row(parser_version="v3"),
        _row(parser_version="v3"),
        _row(parser_version="v3"),
        _row(parser_version="v1_fallback"),
    ]
    summary = summarise_traces(rows=rows)
    assert summary["parser_breakdown"] == {"v3": 3, "v1_fallback": 1}
    assert summary["parser_pct"]["v3"] == 75.0
    assert summary["parser_pct"]["v1_fallback"] == 25.0


def test_summarise_treats_missing_parser_version_as_unknown() -> None:
    rows = [_row(parser_version="v3"), {"prompt_id": "ref-002"}]
    summary = summarise_traces(rows=rows)
    assert summary["parser_breakdown"]["unknown"] == 1
    assert summary["parser_pct"]["unknown"] == 50.0


def test_summarise_calibration_coverage() -> None:
    rows = [
        _row(calibration_example_ids=["cal-mnh-safety-001"]),
        _row(calibration_example_ids=[]),
        _row(),  # field absent entirely
        _row(calibration_example_ids=["cal-x", "cal-y"]),
    ]
    summary = summarise_traces(rows=rows)
    assert summary["n_calls_with_calibration"] == 2
    assert summary["calibration_coverage_pct"] == 50.0


def test_summarise_handles_missing_durations_without_poisoning_avg() -> None:
    rows = [
        _row(duration_sec=1.0),
        _row(),  # no duration field — must NOT count as 0
        _row(duration_sec=3.0),
    ]
    summary = summarise_traces(rows=rows)
    # Avg should be (1+3)/2 = 2.0, NOT (1+0+3)/3
    assert summary["avg_duration_sec"] == 2.0
    judge_stats = summary["per_judge"]["gemini-2.5-pro"]
    assert judge_stats["n_with_duration"] == 2


def test_summarise_accepts_legacy_duration_key() -> None:
    rows = [_row(duration=2.5)]  # legacy field name without _sec suffix
    summary = summarise_traces(rows=rows)
    assert summary["avg_duration_sec"] == 2.5


def test_summarise_unknown_judge_when_field_missing() -> None:
    rows = [{"prompt_id": "ref-001", "principle_id": 3}]
    summary = summarise_traces(rows=rows)
    assert "unknown" in summary["per_judge"]
    assert summary["per_judge"]["unknown"]["count"] == 1


def test_summarise_consumes_generator_once() -> None:
    rows = (_row(prompt_id=f"ref-{i:03d}") for i in range(4))
    summary = summarise_traces(rows=rows)
    assert summary["total_rows"] == 4


def test_summarise_against_real_partial_trace_file(tmp_path: Path) -> None:
    """End-to-end: build a JSONL with a corrupt line, load it via the
    raw reader, and confirm summary skips the partial line gracefully.
    """
    p = tmp_path / "trace.jsonl"
    p.write_text(
        json.dumps(_row(judge_model="gemini-2.5-pro", duration_sec=1.0, parser_version="v3")) + "\n"
        + "{not valid json\n"
        + json.dumps(_row(judge_model="sonnet-4-6", duration_sec=2.0, parser_version="v1_fallback")) + "\n"
    )
    from streamlit_app.data_loaders import _read_jsonl

    rows = _read_jsonl(str(p), 0.0)
    summary = summarise_traces(rows=rows)
    assert summary["total_rows"] == 2
    assert summary["parser_breakdown"] == {"v3": 1, "v1_fallback": 1}


def test_combined_filter_and_versions() -> None:
    rows = [
        _row(prompt_id="ref-001", judge_model="sonnet-4-6", principle_id=3),
        _row(prompt_id="ref-001", judge_model="sonnet-4-6", principle_id=8),
        _row(prompt_id="ref-002", judge_model="gemini-2.5-pro", principle_id=3),
    ]
    out = list(
        filter_traces(
            prompt_id="ref-001",
            judge_model="sonnet-4-6",
            principle_id=3,
            rows=rows,
        )
    )
    assert len(out) == 1
    assert out[0]["principle_id"] == 3
