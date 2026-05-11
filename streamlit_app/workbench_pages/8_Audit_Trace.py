"""Page 8 — Judge Trace / Reproducibility.

Per the shipped workbench design the audit-trace page + the audit-trace design STRETCH note:

* If ``results/judge_trace.jsonl`` is missing or empty (the v3
  STRETCH artefact hasn't shipped yet), render a banner explaining
  that the v2 baseline doesn't emit per-call traces and Page 8 will
  populate once v3 lands.  **Must not crash.**
* When trace data IS present, the page lets the reviewer pick a
  ``(prompt_id, judge_model, principle_id)`` cell and shows:
  * temperature, seed, rubric_version, prompt_template_version,
    dataset_version, strategy_version
  * calibration_example_ids (with a pointer to Page 6 for the
    per-example detail)
  * cache_key, timestamp, duration
  * a "Replay this call" pane with the exact judge prompt sent + the
    raw judge output (so reviewers can verify the prompt template
    actually included the rubric + retrieved calibration examples).
"""
from __future__ import annotations

import streamlit as st

import pandas as pd

from streamlit_app.config import PATH_JUDGE_TRACE_JSONL
from streamlit_app.data_loaders import load_judge_trace
from streamlit_app.trace_loader import (
    filter_traces,
    summarise_traces,
    trace_count,
    trace_file_available,
    unique_field_values,
)

st.title("Audit Trace")
st.caption(
    "Inspect the evidence behind individual judge scores: which prompt was "
    "sent, which rubric and memory examples were included, which model judged "
    "it, and what raw output came back."
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

            * The judge model, temperature, seed, rubric version, dataset version,
              and strategy version.
            * The judge-memory examples retrieved for that call.
            * The exact rendered judge prompt and the raw judge output.
            * Parser status, so reviewers can see whether structured judge output
              was accepted or recovered by a fallback parser.
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
# Trace summary (STRETCH the audit-trace page+) — only renders when trace data exists.  The
# `trace_file_available()` gate above already short-circuited the empty case,
# but we re-guard on `total > 0` so a populated-then-truncated file (rare)
# doesn't render an empty summary card.
if total > 0:
    summary = summarise_traces(all_rows)

    st.subheader("Trace Summary")
    st.caption(
        "Summary over the full trace file, before filters are applied. A high "
        "fallback-parser rate means too many judge outputs missed the structured "
        "format and should be inspected."
    )

    head_cols = st.columns(4)
    with head_cols[0]:
        st.metric("Total judge-call rows", f"{summary['total_rows']:,}")
    with head_cols[1]:
        avg_d = summary["avg_duration_sec"]
        st.metric(
            "Avg call duration",
            f"{avg_d:.2f}s" if avg_d is not None else "—",
        )
    with head_cols[2]:
        st.metric(
            "Judge-memory coverage",
            f"{summary['calibration_coverage_pct']:.1f}%",
            help=(
                f"{summary['n_calls_with_calibration']:,} of "
                f"{summary['total_rows']:,} calls retrieved at least one "
                "judge-memory example."
            ),
        )
    with head_cols[3]:
        v3_pct = summary["parser_pct"].get("v3", 0.0)
        fallback_pct = summary["parser_pct"].get("v1_fallback", 0.0)
        st.metric(
            "Structured / fallback parser split",
            f"{v3_pct:.1f}% / {fallback_pct:.1f}%",
            help=(
                "v3 = structured judge output validated. v1_fallback = older "
                "fallback parser recovered the score."
            ),
        )

    breakdown_cols = st.columns(3)

    # Parser-version breakdown table.
    with breakdown_cols[0]:
        st.markdown("**Parser Status**")
        parser_rows = [
            {
                "parser_version": k,
                "count": summary["parser_breakdown"][k],
                "pct": f"{summary['parser_pct'].get(k, 0.0):.2f}%",
            }
            for k in sorted(summary["parser_breakdown"])
        ]
        st.dataframe(
            pd.DataFrame(parser_rows),
            hide_index=True,
            width="stretch",
        )

    # Per-judge-model breakdown.
    with breakdown_cols[1]:
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
    with breakdown_cols[2]:
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
                    "principle_id": pid,
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
    rubric_versions = ["All"] + [
        str(v) for v in unique_field_values("rubric_version", rows=all_rows)
    ]

    sel_prompt = st.selectbox("Prompt id", prompt_ids)
    sel_judge = st.selectbox("Judge model", judge_models)
    sel_principle = st.selectbox("Scoring principle", principle_ids)
    sel_rubric = st.selectbox("Rubric version", rubric_versions)

filtered = list(
    filter_traces(
        prompt_id=None if sel_prompt == "All" else sel_prompt,
        judge_model=None if sel_judge == "All" else sel_judge,
        principle_id=None if sel_principle == "All" else sel_principle,
        rubric_version=None if sel_rubric == "All" else sel_rubric,
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
        f"P{row.get('principle_id', '?')} · "
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
    st.metric("Judge model", str(row.get("judge_model", "—")))
with prov_cols[1]:
    st.metric("Scoring principle", str(row.get("principle_id", "—")))
    st.metric("Score", f"{row.get('score', float('nan')):.2f}" if "score" in row else "—")
with prov_cols[2]:
    st.metric("Temperature", str(row.get("temperature", "—")))
    st.metric("Seed", str(row.get("seed", "—")))
with prov_cols[3]:
    st.metric("Rubric version", str(row.get("rubric_version", "—")))
    st.metric("Parser version", str(row.get("parser_version", "—")))

meta_cols = st.columns(3)
with meta_cols[0]:
    st.markdown(
        f"**Prompt template version**: `{row.get('prompt_template_version', '—')}`"
    )
    st.markdown(f"**Dataset version**: `{row.get('dataset_version', '—')}`")
    st.markdown(f"**Strategy version**: `{row.get('strategy_version', '—')}`")
with meta_cols[1]:
    st.markdown(f"**Timestamp**: `{row.get('timestamp', '—')}`")
    duration = row.get("duration_sec", row.get("duration"))
    st.markdown(
        "**Duration**: "
        + (f"`{duration:.3f}s`" if isinstance(duration, (int, float)) else "—")
    )
    st.markdown(f"**Cache key**: `{row.get('cache_key', '—')}`")
with meta_cols[2]:
    cal_ids = row.get("calibration_example_ids") or []
    st.markdown(f"**Judge-memory examples** ({len(cal_ids)})")
    if cal_ids:
        for cid in cal_ids:
            # Cross-link: Streamlit anchors per-page via st.page_link;
            # "Calibration Memory" is page 6 owned by page-builder-B.
            st.markdown(f"- `{cid}`")
        st.caption(
            "Open **Judge Memory** in the sidebar to inspect these examples."
        )
    else:
        st.caption(
            "No judge-memory examples were retrieved for this call."
        )

st.markdown(f"**Judge rationale**: {row.get('rationale', '_not recorded_')}")
# "Replay this call" — the exact prompt sent + raw judge output.
st.subheader("Replay Evidence")
replay_cols = st.columns(2)
with replay_cols[0]:
    st.markdown("**Prompt sent to the judge**")
    rendered = row.get("rendered_judge_prompt") or ""
    if rendered:
        st.code(rendered, language="markdown")
    else:
        st.info(
            "No rendered judge prompt was recorded in this row. Older runs may "
            "only contain the recovered score and rationale."
        )
with replay_cols[1]:
    st.markdown("**Raw judge output**")
    raw = row.get("raw_judge_output") or ""
    if raw:
        # Show as plain text + a download link in case the JSON is long.
        st.code(raw, language="json")
    else:
        st.info("No raw judge output recorded.")

st.divider()
st.caption(
    "Trace rows are append-only. Filters narrow what you see; the underlying "
    "trace file is not rewritten."
)
