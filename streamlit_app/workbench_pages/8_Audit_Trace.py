"""Page 8 — Judge Trace / Reproducibility.

Per the shipped workbench design the audit-trace page + the audit-trace design STRETCH note:

* If ``results/judge_trace.jsonl`` is missing or empty (the v3
  STRETCH artefact hasn't shipped yet), render a banner explaining
  that the v2 baseline doesn't emit per-call traces and Page 8 will
  populate once v3 lands.  **Must not crash.**
* When trace data IS present, the page lets the reviewer pick a
  ``(prompt_id, judge_model, principle_id)`` cell and shows:
  * judge model, scoring principle, score, rationale
  * calibration_example_ids (with a pointer to Page 6 for the
    per-example detail)
  * a "Replay this call" pane with the exact judge prompt sent + the
    raw judge output.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from streamlit_app.config import PATH_JUDGE_TRACE_JSONL
from streamlit_app.data_loaders import (
    load_calibration_examples,
    load_constitution,
    load_judge_trace,
)
from streamlit_app.trace_loader import (
    filter_traces,
    summarise_traces,
    trace_count,
    trace_file_available,
    unique_field_values,
)


def _plain_name(value: object) -> str:
    return str(value or "unknown").replace("_", " ")


def _principle_label(value: object, principle_names: dict[int, str]) -> str:
    try:
        pid = int(str(value))
    except (TypeError, ValueError):
        return f"P{value}"
    name = principle_names.get(pid)
    if not name:
        return f"P{pid}"
    return f"P{pid} · {_plain_name(name)}"


def _score_text(value: object) -> str:
    return f"{float(value):.2f}" if isinstance(value, (int, float)) else "—"


def _list_value(value: object) -> list[object]:
    return value if isinstance(value, list) else []


st.title("Audit Trace")
st.caption(
    "Open any judge score and inspect the exact prompt, score rationale, "
    "memory anchors, and raw judge output behind it."
)
# Empty-state guard.
if not trace_file_available():
    st.warning(
        "**Detailed trace data is not available yet.** Run "
        "`scripts/run_panel_refset_eval.py` to write `results/judge_trace.jsonl`.",
        icon="⏳",
    )
    with st.expander("What this page will show"):
        st.markdown(
            """
            For each judge score:

            * The judge model, scoring principle, score, and rationale.
            * The judge-memory examples retrieved for that call.
            * The exact rendered judge prompt and the raw judge output.
            """
        )
    st.caption(
        f"Trace file path: `{PATH_JUDGE_TRACE_JSONL.relative_to(PATH_JUDGE_TRACE_JSONL.parents[1])}`  · "
        "absent → banner above; present-but-empty → same banner."
    )
    st.stop()
# Trace data is available — load + populate sidebar selectors from the file
# itself (never invent options the file doesn't have).
all_rows = load_judge_trace()
total = trace_count(all_rows)
constitution = load_constitution()
principle_names = {
    int(p["id"]): str(p.get("name", ""))
    for p in constitution.get("principles", [])
    if p.get("id")
}
calibration_by_id = {
    str(ex.get("id")): ex
    for ex in load_calibration_examples()
    if ex.get("id")
}
# Trace summary (STRETCH the audit-trace page+) — only renders when trace data exists.  The
# `trace_file_available()` gate above already short-circuited the empty case,
# but we re-guard on `total > 0` so a populated-then-truncated file (rare)
# doesn't render an empty summary card.
if total > 0:
    summary = summarise_traces(all_rows)

    st.subheader("Trace Summary")
    st.caption(
        "Summary over the full trace file, before filters are applied."
    )

    head_cols = st.columns(4)
    with head_cols[0]:
        st.metric("Judge-call rows", f"{summary['total_rows']:,}")
    with head_cols[1]:
        st.metric("Reference cases", len(unique_field_values("prompt_id", rows=all_rows)))
    with head_cols[2]:
        st.metric("Judge models", len(unique_field_values("judge_model", rows=all_rows)))
    with head_cols[3]:
        st.metric(
            "Judge-memory coverage",
            f"{summary['calibration_coverage_pct']:.1f}%",
            help=(
                f"{summary['n_calls_with_calibration']:,} of "
                f"{summary['total_rows']:,} calls retrieved at least one "
                "judge-memory example."
            ),
        )

    breakdown_cols = st.columns(2)

    # Per-judge-model breakdown.
    with breakdown_cols[0]:
        st.markdown("**By Judge Model**")
        judge_rows = []
        for judge, stats in sorted(summary["per_judge"].items()):
            judge_rows.append(
                {
                    "judge_model": judge,
                    "calls": stats["count"],
                    "avg duration (s)": (
                        f"{stats['avg_duration_sec']:.2f}"
                        if stats["avg_duration_sec"] is not None
                        else "—"
                    ),
                }
            )
        st.dataframe(
            pd.DataFrame(judge_rows),
            hide_index=True,
            width="stretch",
        )

    # Per-principle breakdown.
    with breakdown_cols[1]:
        st.markdown("**By Scoring Principle**")
        principle_rows = []

        def _principle_sort_key(item):
            k = item[0]
            try:
                return (0, int(k))
            except ValueError:
                return (1, k)

        for pid, stats in sorted(summary["per_principle"].items(), key=_principle_sort_key):
            principle_rows.append(
                {
                    "principle": _principle_label(pid, principle_names),
                    "calls": stats["count"],
                    "avg duration (s)": (
                        f"{stats['avg_duration_sec']:.2f}"
                        if stats["avg_duration_sec"] is not None
                        else "—"
                    ),
                }
            )
        st.dataframe(
            pd.DataFrame(principle_rows),
            hide_index=True,
            width="stretch",
        )

    st.divider()

with st.sidebar:
    st.header("Filter Trace Rows")
    st.caption(f"{total} trace rows on disk")

    prompt_ids = ["All"] + [str(v) for v in unique_field_values("prompt_id", rows=all_rows)]
    judge_models = ["All"] + [str(v) for v in unique_field_values("judge_model", rows=all_rows)]
    principle_ids_raw = unique_field_values("principle_id", rows=all_rows)
    principle_ids = ["All"] + [str(v) for v in principle_ids_raw]

    sel_prompt = st.selectbox("Prompt id", prompt_ids)
    sel_judge = st.selectbox("Judge model", judge_models)
    sel_principle = st.selectbox(
        "Scoring principle",
        principle_ids,
        format_func=(
            lambda value: "All" if value == "All" else _principle_label(value, principle_names)
        ),
    )

filtered = list(
    filter_traces(
        prompt_id=None if sel_prompt == "All" else sel_prompt,
        judge_model=None if sel_judge == "All" else sel_judge,
        principle_id=None if sel_principle == "All" else sel_principle,
        rows=all_rows,
    )
)

st.markdown(f"**{len(filtered)}** trace rows match the current filter.")
if not filtered:
    st.info("No rows match this combination. Widen a filter in the sidebar.")
    st.stop()
# Row picker — for the trace-detail pane.
def _label(row: dict) -> str:
    return (
        f"{row.get('prompt_id', '?')} · {row.get('judge_model', '?')} · "
        f"{_principle_label(row.get('principle_id', '?'), principle_names)} · "
        f"{row.get('timestamp', '')}"
    )


labels = [_label(r) for r in filtered]
chosen_idx = st.selectbox(
    "Choose a judge-call row",
    options=list(range(len(filtered))),
    format_func=lambda i: labels[i],
)
row = filtered[chosen_idx]
# Provenance row.
st.subheader("Call Details")
prov_cols = st.columns(4)
with prov_cols[0]:
    st.metric("Prompt id", str(row.get("prompt_id", "—")))
with prov_cols[1]:
    st.metric("Judge model", str(row.get("judge_model", "—")))
with prov_cols[2]:
    principle_label = _principle_label(row.get("principle_id", "—"), principle_names)
    st.metric("Scoring principle", principle_label.split(" · ", 1)[0])
    st.caption(principle_label.partition(" · ")[2])
with prov_cols[3]:
    st.metric("Score", _score_text(row.get("score")))

rationale = str(row.get("rationale") or "").strip()
if rationale:
    st.markdown(f"**Judge rationale:** {rationale}")
else:
    st.info("No judge rationale was recorded for this row.")

evidence_quotes = _list_value(row.get("evidence"))
if evidence_quotes:
    st.markdown("**Evidence quoted by the judge**")
    for quote in evidence_quotes:
        st.markdown(f"- {quote}")

failure_type = row.get("failure_type")
if failure_type:
    st.markdown(f"**Failure type:** `{failure_type}`")

cal_ids = _list_value(row.get("calibration_example_ids"))
st.subheader(f"Judge-Memory Anchors ({len(cal_ids)})")
if cal_ids:
    st.caption("These are the precedent examples included in the judge prompt.")
    for cid in cal_ids:
        ex = calibration_by_id.get(str(cid))
        title = str(cid)
        if ex:
            anchor_score = ex.get("human_score", ex.get("reference_score", "—"))
            score_status = "reviewed" if ex.get("approved_by") else "draft"
            title += (
                f" · {score_status} score {anchor_score} · "
                f"{ex.get('failure_category') or 'positive anchor'}"
            )
        with st.expander(title, expanded=False):
            if not ex:
                st.info("This anchor ID is not present in the local judge-memory file.")
                continue
            st.caption(f"Reference case: `{ex.get('ref_id', '—')}`")
            st.markdown("**Prompt**")
            st.markdown(str(ex.get("prompt", "")).strip())
            st.markdown("**Answer used as precedent**")
            st.code(str(ex.get("actual_answer", "")).strip(), language="markdown")
            st.markdown("**Why this anchor has that score**")
            st.markdown(str(ex.get("human_reason", "")).strip())
else:
    st.info("No judge-memory examples were retrieved for this call.")

# Raw evidence is still available for reproducibility, but hidden by default so
# the page stays readable during live review.
st.subheader("Raw Evidence")
st.caption("Open these only when you need to reproduce the exact judge call.")
with st.expander("Full prompt sent to the judge", expanded=False):
    rendered = row.get("rendered_judge_prompt") or ""
    if rendered:
        st.code(rendered, language="markdown")
    else:
        st.info(
            "No rendered judge prompt was recorded in this row. Older runs may "
            "only contain the recovered score and rationale."
        )

with st.expander("Raw judge output", expanded=False):
    raw = row.get("raw_judge_output") or ""
    if raw:
        st.code(raw, language="json")
    else:
        st.info("No raw judge output recorded.")

st.divider()
st.caption(
    "Trace rows are append-only. Filters narrow what you see; the underlying "
    "trace file is not rewritten."
)
