"""Reusable case-detail drill-down for the Case Explorer page."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import streamlit as st

from eval.reference_risk import (
    reference_risk_description,
    reference_risk_label,
    reference_risk_tier,
)
from streamlit_app.config import CERAI_DB_SCORE_CUTOFF
from .judge_score_heatmap import render_judge_heatmap


_LEADING_THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_TRIAGE_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\{.*?\"triage_label\".*?\}\s*```\s*",
    re.DOTALL,
)


def _visible_response_text(response: str) -> str:
    text = _LEADING_THINK_RE.sub("", response or "", count=1)
    return _TRIAGE_BLOCK_RE.sub("", text, count=1).strip()


def _format_score(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _cerai_routes_from_scores(scores: Mapping[str, Any] | None) -> bool:
    mean_score = (scores or {}).get("mean")
    try:
        return float(mean_score) < CERAI_DB_SCORE_CUTOFF
    except (TypeError, ValueError):
        return False


def _render_ground_truth(item: Mapping[str, Any]) -> None:
    st.markdown("### Reference Answer")
    tier = reference_risk_tier(item)
    cols = st.columns(3)
    with cols[0]:
        st.metric(
            "Expected safety action", str(item.get("expected_safety_action", "?"))
        )
    with cols[1]:
        st.metric("Reference risk", reference_risk_label(tier).split(" - ", 1)[0])
    with cols[2]:
        rf = item.get("red_flag_match_required") or []
        st.metric("Required red flags", f"{len(rf)}")
    st.caption(
        "Reference risk is test-case context for scoring the answer: "
        + reference_risk_description(tier)
    )

    st.markdown("**Hindi prompt**")
    st.code(item.get("hindi_text", ""), language="markdown")

    factual = item.get("factual_checklist") or []
    if factual:
        st.markdown("**Factual checklist**")
        for f in factual:
            st.markdown(f"- {f}")

    rf = item.get("red_flag_match_required") or []
    if rf:
        st.markdown("**Required red flags**")
        for r in rf:
            st.markdown(f"- `{r}`")

    src_para = item.get("source_paragraph", "")
    if src_para:
        with st.expander("Source context (paraphrased; clinical review pending)", expanded=False):
            st.markdown(src_para)

    src_url = item.get("source_url", "")
    if src_url:
        st.markdown(f"[Source URL →]({src_url})")


def _render_panel_response(row: Mapping[str, Any]) -> None:
    st.markdown("### Model Response")
    if not row:
        st.warning("No HealthEval Safety Method row found for this prompt.", icon="⚠️")
        return

    response_text = _visible_response_text(str(row.get("response", "")))
    cols = st.columns(2)
    with cols[0]:
        latency = row.get("latency_sec")
        st.metric("Panel latency", f"{latency:.1f}s" if isinstance(latency, (int, float)) else "?")
    with cols[1]:
        st.metric("Response length", f"{len(response_text)} chars")

    with st.expander("Full Hindi response", expanded=False):
        st.write(response_text)

    st.markdown("**Model-emitted triage JSON**")
    st.caption(
        "This is the structured block at the start of the raw model answer. "
        "It is shown for transparency; the final HealthEval routing below comes "
        "from judge scores."
    )
    triage = row.get("triage_parsed")
    if isinstance(triage, Mapping) and triage:
        st.json(triage)
    else:
        st.warning("No parseable triage JSON was found in the model output.", icon="⚠️")


def _render_jury(
    row: Mapping[str, Any],
    principles: Sequence[Mapping[str, Any]] | None,
    *,
    key_prefix: str,
) -> None:
    st.markdown("### Judge Score Grid")
    judge_scores = row.get("judge_scores") or []
    render_judge_heatmap(
        judge_scores, principles=principles, key=f"{key_prefix}_heatmap"
    )

    decision = row.get("decision") or {}
    if decision:
        cols = st.columns(3)
        with cols[0]:
            st.metric(
                "Judge score band",
                str(decision.get("triage_label", "?")),
                help="Decision from judge scores for the model response.",
            )
        with cols[1]:
            sm = decision.get("jury_safety_mean")
            st.metric(
                "Jury safety mean",
                f"{sm:.2f}" if isinstance(sm, (int, float)) else "?",
            )
        with cols[2]:
            st.metric(
                "Judge-band flagged?",
                "🚩 YES" if decision.get("flagged") else "✅ NO",
            )
        if decision.get("judge_score_incomplete"):
            st.warning(
                "This case needs review because too few usable judge scores "
                "were available, not because the response score alone failed.",
                icon="⚠️",
            )


def _render_final_method_decision(row: Mapping[str, Any]) -> None:
    st.markdown("### HealthEval Response Evaluation")
    decision = row.get("decision") or {}
    if decision:
        cols = st.columns(4)
        with cols[0]:
            st.metric("Response score band", decision.get("triage_label", "?"))
        with cols[1]:
            st.metric(
                "Needs review",
                "🚩 YES" if decision.get("flagged") else "✅ NO",
            )
        with cols[2]:
            mean = decision.get("jury_safety_mean")
            st.metric(
                "Judge safety mean",
                f"{mean:.2f}" if isinstance(mean, (int, float)) else "?",
            )
        with cols[3]:
            st.metric("Usable judge cells", decision.get("n_cells", "?"))
    else:
        st.warning("HealthEval Safety Method decision is missing for this case.", icon="⚠️")


def _render_cerai_verdict(cerai_scores: Mapping[str, Any] | None) -> None:
    st.markdown("### CeRAI Comparator")
    scores = dict(cerai_scores or {})
    if not scores:
        st.caption("(no CeRAI Docker DB scores for this prompt)")
        return

    flagged = _cerai_routes_from_scores(scores)
    cols = st.columns(2)
    with cols[0]:
        st.metric("CeRAI DB mean", _format_score(scores.get("mean")))
    with cols[1]:
        st.metric("Routes response?", "🚩 YES" if flagged else "✅ NO")
    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric("Accuracy", _format_score(scores.get("accuracy")))
    with metric_cols[1]:
        st.metric("Relevance", _format_score(scores.get("relevance")))
    with metric_cols[2]:
        st.metric("Hallucination", _format_score(scores.get("hallucination")))
    st.caption(
        "CeRAI comparator uses the saved Docker DB score export. "
        f"Scores below {CERAI_DB_SCORE_CUTOFF:.2f} route the response."
    )
    with st.expander("CeRAI Docker DB scores", expanded=False):
        st.json(scores)


def _render_hitl_history(
    prompt_id: str,
    hitl_reviews: Sequence[Mapping[str, Any]],
    session_reviews: Sequence[Mapping[str, Any]],
) -> None:
    st.markdown("### Human Review History")
    matching = [
        r
        for r in list(hitl_reviews) + list(session_reviews)
        if r.get("prompt_id") == prompt_id
    ]
    if not matching:
        st.caption("No human reviews on file for this prompt yet.")
        return
    for r in matching:
        with st.expander(
            f"{r.get('review_id', '?')}  ·  {r.get('reviewer_role', '?')}  ·  "
            f"{r.get('human_decision', '?')}",
            expanded=False,
        ):
            st.json(r)


def _render_send_to_hitl(prompt_id: str, *, key: str) -> None:
    if st.button("Send To Human Review Queue", key=key):
        queue: list[str] = list(st.session_state.get("hitl_queue_target", []))
        if prompt_id not in queue:
            queue.append(prompt_id)
        st.session_state["hitl_queue_target"] = queue
        st.success(
            f"Queued `{prompt_id}` for human review. Open the Human Review "
            "Queue page in the sidebar to adjudicate."
        )


def render_case_detail(
    *,
    prompt_id: str,
    reference_item: Mapping[str, Any] | None,
    methodology_row: Mapping[str, Any] | None,
    cerai_scores: Mapping[str, Any] | None,
    constitution_principles: Sequence[Mapping[str, Any]] | None = None,
    hitl_reviews: Sequence[Mapping[str, Any]] = (),
    session_reviews: Sequence[Mapping[str, Any]] = (),
    key_prefix: str = "case_detail",
) -> None:
    """Render the full case drill-down from already-loaded evidence."""
    if reference_item is None:
        st.error(f"Reference item `{prompt_id}` not found.", icon="🚫")
        return

    st.subheader(f"Case Detail · `{prompt_id}`")
    _render_ground_truth(reference_item)
    st.divider()
    _render_panel_response(methodology_row or {})
    st.divider()
    _render_jury(
        methodology_row or {},
        constitution_principles,
        key_prefix=f"{key_prefix}_{prompt_id}",
    )
    st.divider()
    _render_final_method_decision(methodology_row or {})
    st.divider()
    _render_cerai_verdict(cerai_scores)
    st.divider()
    _render_hitl_history(prompt_id, hitl_reviews, session_reviews)
    st.divider()
    _render_send_to_hitl(prompt_id, key=f"{key_prefix}_hitl_btn_{prompt_id}")


__all__ = ["render_case_detail"]
