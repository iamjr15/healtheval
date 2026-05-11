"""Filter + summary helpers over ``results/judge_trace.jsonl``.

The raw JSONL read (with partial-trailing-line tolerance + 60 s TTL +
mtime cache key) lives in ``data_loaders.load_judge_trace``.  This
module sits on top and provides:

* ``trace_file_available()`` — Page 8 uses it to decide between the
  empty-state banner and the full filter UI.  Returns False when the
  file is missing OR present-but-empty (the v3 STRETCH artefact).
* ``filter_traces()`` — generator over the loaded rows applying any
  combination of (prompt_id, judge_model, principle_id, rubric_version)
  filters.  Skips rows that fail to match without raising.
* ``unique_field_values()`` — populate the sidebar selectors without
  hard-coding what's currently in the file.
* ``summarise_traces()`` — aggregate stats (per-judge call counts +
  avg duration, per-principle call counts + avg duration, parser-version
  breakdown v3 vs v1_fallback with %, calibration retrieval coverage %)
  for the "Trace summary" section at the top of Page 8.

Per the shipped workbench design the audit-trace page + the audit-trace design: this page MUST gracefully render the
"v3 trace data pending" banner when the file is missing.  Every
function in this module returns sensibly when there's nothing to read.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, TypedDict

from .config import PATH_JUDGE_TRACE_JSONL
from .data_loaders import load_judge_trace
from .schemas import JudgeTraceRow


class GroupStats(TypedDict):
    """Per-bucket aggregate (judge model or principle id)."""

    count: int
    avg_duration_sec: float | None  # None when no row had a duration field
    total_duration_sec: float
    n_with_duration: int


class TraceSummary(TypedDict):
    """Aggregate stats over the trace JSONL.

    Keyed lookups use string IDs so the page can render them in metric
    cards directly (``str(principle_id)`` for the principle bucket).
    """

    total_rows: int
    per_judge: dict[str, GroupStats]
    per_principle: dict[str, GroupStats]
    parser_breakdown: dict[str, int]
    parser_pct: dict[str, float]
    calibration_coverage_pct: float
    n_calls_with_calibration: int
    avg_duration_sec: float | None


def trace_file_available(path: Path | None = None) -> bool:
    """Return True iff the trace JSONL exists *and* contains ≥ 1 byte.

    The file is created (empty) by some scaffolders before the v3 run
    actually runs — we treat that as "still pending".  Page 8 calls
    this first and short-circuits to the banner if False.
    """
    p = path or PATH_JUDGE_TRACE_JSONL
    try:
        return p.stat().st_size > 0
    except FileNotFoundError:
        return False


def _matches(row: JudgeTraceRow, filters: dict[str, Any]) -> bool:
    for field, expected in filters.items():
        if expected in (None, "", "All"):
            continue
        actual = row.get(field)  # type: ignore[arg-type]
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        else:
            # principle_id is int in the schema but the sidebar may pass str.
            if str(actual) != str(expected):
                return False
    return True


def filter_traces(
    *,
    prompt_id: str | None = None,
    judge_model: str | None = None,
    principle_id: int | str | None = None,
    rubric_version: str | None = None,
    rows: Iterable[JudgeTraceRow] | None = None,
) -> Iterator[JudgeTraceRow]:
    """Yield trace rows that match every supplied filter.

    Pass ``None`` (or ``"All"`` from a Streamlit selectbox) to skip a
    given dimension.  ``rows`` lets tests inject a fixture; in normal
    use we call ``data_loaders.load_judge_trace`` to fetch the cached
    list.
    """
    if rows is None:
        rows = load_judge_trace()
    filters: dict[str, Any] = {
        "prompt_id": prompt_id,
        "judge_model": judge_model,
        "principle_id": principle_id,
        "rubric_version": rubric_version,
    }
    for row in rows:
        if _matches(row, filters):
            yield row


def unique_field_values(
    field: str,
    *,
    rows: Iterable[JudgeTraceRow] | None = None,
) -> list[Any]:
    """Distinct sorted values of ``field`` across the trace JSONL.

    Skips rows that don't carry the field (e.g., legacy cells without
    ``rubric_version``).  Used to populate sidebar selectors without
    inventing options the trace file doesn't actually have.
    """
    if rows is None:
        rows = load_judge_trace()
    seen: set[Any] = set()
    for row in rows:
        v = row.get(field)  # type: ignore[arg-type]
        if v is None or v == "":
            continue
        seen.add(v)
    try:
        return sorted(seen)
    except TypeError:
        # Mixed-type values (shouldn't happen given the schema) — fall
        # back to string-sorted to keep the selector stable.
        return sorted(seen, key=str)


def trace_count(rows: Iterable[JudgeTraceRow] | None = None) -> int:
    """Total number of parseable trace rows (after partial-line skip)."""
    if rows is None:
        rows = load_judge_trace()
    return sum(1 for _ in rows)


def _row_duration(row: JudgeTraceRow) -> float | None:
    """Pick the duration off a trace row.

    The schema names it ``duration_sec`` but very early v3 rows used
    ``duration``; accept either.  Returns ``None`` when no numeric
    duration is present so the avg-stat caller can skip it without
    poisoning the average with zeros.
    """
    for key in ("duration_sec", "duration"):
        v = row.get(key)  # type: ignore[arg-type]
        if isinstance(v, (int, float)) and v >= 0:
            return float(v)
    return None


def _new_group() -> dict[str, Any]:
    return {"count": 0, "total_duration_sec": 0.0, "n_with_duration": 0}


def _finalise_group(g: dict[str, Any]) -> GroupStats:
    n = g["n_with_duration"]
    avg = g["total_duration_sec"] / n if n else None
    return {
        "count": g["count"],
        "avg_duration_sec": avg,
        "total_duration_sec": g["total_duration_sec"],
        "n_with_duration": n,
    }


def summarise_traces(
    rows: Iterable[JudgeTraceRow] | None = None,
) -> TraceSummary:
    """Aggregate stats over the trace JSONL for the Page 8 summary section.

    Walks ``rows`` exactly once so it remains generator-safe.  An empty
    or missing file produces an empty summary (``total_rows == 0``);
    callers should gate the section on ``trace_file_available()`` /
    ``summary["total_rows"] > 0`` rather than checking the dict shape.

    Bucketing rules:

    * ``per_judge`` — keyed on ``judge_model`` (string, falls back to
      ``"unknown"`` when the field is missing).
    * ``per_principle`` — keyed on ``str(principle_id)`` so the
      Streamlit metric cards can render the key directly.
    * ``parser_breakdown`` / ``parser_pct`` — count + %-of-total for
      every distinct ``parser_version`` value, plus an explicit
      ``"unknown"`` bucket for rows missing the field (legacy / partial
      writes).  Percentages are rounded to two decimal places.
    * ``calibration_coverage_pct`` — % of rows whose
      ``calibration_example_ids`` is a non-empty list.  Rows missing
      the field count toward the denominator (zero retrieval).
    """
    if rows is None:
        rows = load_judge_trace()

    total_rows = 0
    per_judge: dict[str, dict[str, Any]] = defaultdict(_new_group)
    per_principle: dict[str, dict[str, Any]] = defaultdict(_new_group)
    parser_breakdown: dict[str, int] = defaultdict(int)
    n_with_calibration = 0
    overall_total_duration = 0.0
    overall_n_with_duration = 0

    for row in rows:
        total_rows += 1
        duration = _row_duration(row)

        judge = str(row.get("judge_model") or "unknown")
        per_judge[judge]["count"] += 1
        if duration is not None:
            per_judge[judge]["total_duration_sec"] += duration
            per_judge[judge]["n_with_duration"] += 1

        principle_raw = row.get("principle_id")
        principle_key = "unknown" if principle_raw is None else str(principle_raw)
        per_principle[principle_key]["count"] += 1
        if duration is not None:
            per_principle[principle_key]["total_duration_sec"] += duration
            per_principle[principle_key]["n_with_duration"] += 1

        parser = str(row.get("parser_version") or "unknown")
        parser_breakdown[parser] += 1

        cal_ids = row.get("calibration_example_ids")
        if isinstance(cal_ids, list) and cal_ids:
            n_with_calibration += 1

        if duration is not None:
            overall_total_duration += duration
            overall_n_with_duration += 1

    parser_pct: dict[str, float] = {}
    if total_rows:
        for k, v in parser_breakdown.items():
            parser_pct[k] = round((v / total_rows) * 100.0, 2)

    coverage_pct = (
        round((n_with_calibration / total_rows) * 100.0, 2) if total_rows else 0.0
    )

    avg_duration = (
        overall_total_duration / overall_n_with_duration
        if overall_n_with_duration
        else None
    )

    return {
        "total_rows": total_rows,
        "per_judge": {k: _finalise_group(g) for k, g in per_judge.items()},
        "per_principle": {k: _finalise_group(g) for k, g in per_principle.items()},
        "parser_breakdown": dict(parser_breakdown),
        "parser_pct": parser_pct,
        "calibration_coverage_pct": coverage_pct,
        "n_calls_with_calibration": n_with_calibration,
        "avg_duration_sec": avg_duration,
    }


__all__ = [
    "GroupStats",
    "TraceSummary",
    "filter_traces",
    "summarise_traces",
    "trace_count",
    "trace_file_available",
    "unique_field_values",
]
