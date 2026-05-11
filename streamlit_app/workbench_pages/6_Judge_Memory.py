"""Page 6 — Calibration Memory.

Per the shipped workbench design the judge-memory page: browse ``data/judge_calibration_examples.yaml`` —
the seed pack the judge prompt's retriever reads from.  Surfaces:

- Filter controls (metric, source = seed | hitl_promoted, language).
- One card per calibration example (id, rubric_version, prompt +
  expected behaviour, actual answer + human score + reason, failure
  category, approved-by, source provenance).
- A cold-start banner naming how many seed examples cover each metric
  and explicitly noting that real benefit accrues only after sustained
  HITL promotion accumulates.

The page is read-only — no writes to the YAML happen here.  HITL
promotions land in ``data/judge_calibration_candidates.jsonl`` (via
the persistent-mode endpoint) and are bumped into the YAML offline by
``scripts/promote_to_calibration.py``.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import streamlit as st

from streamlit_app.data_loaders import (
    load_all_rubric_packs,
    load_judge_calibration_examples,
)


def _coverage_summary(examples: list[Mapping[str, Any]]) -> dict[str, int]:
    """Count seed + hitl-promoted examples per metric for the cold-start banner."""
    return dict(Counter(str(e.get("metric", "?")) for e in examples))


def _example_card(ex: Mapping[str, Any], idx: int) -> None:
    src = str(ex.get("source", "?"))
    badge = "seed example" if src == "seed" else "human-promoted example"
    title = (
        f"#{idx + 1}  ·  `{ex.get('id', '?')}`  ·  "
        f"{_plain_option(str(ex.get('metric', '?')))}  ·  {badge}"
    )
    with st.expander(title, expanded=False):
        cols = st.columns(3)
        with cols[0]:
            st.metric("Rubric version", str(ex.get("rubric_version", "?")))
        with cols[1]:
            score = ex.get("human_score")
            st.metric(
                "Human score",
                f"{score:.1f}" if isinstance(score, (int, float)) else "?",
            )
        with cols[2]:
            st.metric("Approved by", str(ex.get("approved_by", "?")))

        if ex.get("ref_id"):
            st.caption(f"Derived from reference case `{ex.get('ref_id')}`")
        st.markdown("**Prompt**")
        st.code(ex.get("prompt", ""), language="markdown")
        st.markdown("**Answer being scored**")
        st.code(ex.get("actual_answer", ""), language="markdown")
        if ex.get("expected_behaviour"):
            st.markdown("**Expected behavior**")
            st.markdown(ex.get("expected_behaviour", ""))
        if ex.get("human_reason"):
            st.markdown("**Human reason for the score**")
            st.markdown(ex.get("human_reason", ""))
        meta_cols = st.columns(3)
        with meta_cols[0]:
            fc = ex.get("failure_category")
            if fc:
                st.markdown(f"**Failure category:** `{fc}`")
        with meta_cols[1]:
            created = ex.get("created_at", "")
            if created:
                st.markdown(f"**Created at:** {created}")
        with meta_cols[2]:
            last_used = ex.get("last_used_in_run", "")
            if last_used:
                st.markdown(f"**Last used in run:** {last_used}")


def _filter_options(examples: list[Mapping[str, Any]], field: str) -> list[str]:
    seen: list[str] = []
    for ex in examples:
        v = str(ex.get(field, "")) if ex.get(field) else ""
        if v and v not in seen:
            seen.append(v)
    return ["any"] + seen


def _plain_option(value: str) -> str:
    if value == "any":
        return "Any"
    return str(value).replace("_", " ")


def main() -> None:
    st.title("Judge Memory")
    st.caption(
        "See the approved examples that help the LLM judge score new answers "
        "consistently. These examples act like precedents: similar future "
        "cases can be judged against them."
    )

    pack = load_judge_calibration_examples()
    examples = list(pack.get("examples", []) or [])
    total = len(examples)
    coverage = _coverage_summary(examples)
    rubrics = load_all_rubric_packs()
    rubric_metric_names = sorted(rubrics.keys())
    coverage_str = ", ".join(
        f"{m}: {coverage.get(m, 0)}" for m in rubric_metric_names
    ) or "—"
    st.info(
        "**Judge memory is in its starter state.** The judge can retrieve "
        f"**{total}** approved example(s) today "
        f"(coverage: {coverage_str}). It becomes stronger as more human "
        "reviews are promoted into the memory pack.",
        icon="ℹ️",
    )
    st.sidebar.header("Filter Examples")
    metric_filter = st.sidebar.selectbox(
        "Metric",
        ["any"] + rubric_metric_names,
        index=0,
        format_func=_plain_option,
    )
    source_filter = st.sidebar.selectbox(
        "Source",
        ["any", "seed", "hitl_promoted"],
        index=0,
        format_func=_plain_option,
    )
    failure_options = _filter_options(examples, "failure_category")
    failure_filter = st.sidebar.selectbox(
        "Failure category",
        failure_options,
        index=0,
        format_func=_plain_option,
    )
    rubric_version_filter = st.sidebar.selectbox(
        "Rubric version",
        _filter_options(examples, "rubric_version"),
        index=0,
        format_func=_plain_option,
    )

    filtered: list[Mapping[str, Any]] = []
    for ex in examples:
        if metric_filter != "any" and str(ex.get("metric", "")) != metric_filter:
            continue
        if source_filter != "any" and str(ex.get("source", "")) != source_filter:
            continue
        if (
            failure_filter != "any"
            and str(ex.get("failure_category", "")) != failure_filter
        ):
            continue
        if (
            rubric_version_filter != "any"
            and str(ex.get("rubric_version", "")) != rubric_version_filter
        ):
            continue
        filtered.append(ex)

    st.markdown(
        f"### {len(filtered)} of {total} judge-memory examples match"
    )

    if not filtered:
        st.warning(
            "No examples match the current filters. Widen the filters in the sidebar.",
            icon="ℹ️",
        )
        return

    # Stable order: seed first, then HITL-promoted; within each, by id.
    filtered_sorted = sorted(
        filtered,
        key=lambda e: (
            0 if str(e.get("source", "")) == "seed" else 1,
            str(e.get("id", "")),
        ),
    )
    for i, ex in enumerate(filtered_sorted):
        _example_card(ex, i)


main()
