"""Reusable case-detail drill-down for the Case Explorer page."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

import streamlit as st
from streamlit_app.presentation import model_name, plain_name, risk_name, readable_table

from eval.reference_risk import (
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
    st.markdown("**Expected care**")
    st.write(plain_name(item.get("expected_referral_action")))
    factual = item.get("factual_checklist") or []
    if factual:
        st.markdown("**What a good answer should include**")
        for fact in factual:
            st.markdown(f"- {fact}")
    red_flags = item.get("red_flag_match_required") or []
    if red_flags:
        st.markdown("**Required warning signs**")
        st.write(", ".join(plain_name(flag) for flag in red_flags))
    if item.get("source_paragraph"):
        st.markdown("**Source context**")
        st.write(item["source_paragraph"])
    if item.get("source_url"):
        st.markdown(f"[Read the source ↗]({item['source_url']})")
    st.caption(
        "Synthetic reference; source context is paraphrased. Clinical and Hindi-language review is pending."
    )


def _render_panel_response(row: Mapping[str, Any]) -> None:
    if not row:
        st.info("No saved model answer for this case.")
        return
    st.markdown("**Model answer**")
    st.write(_visible_response_text(str(row.get("response", ""))))
    triage = row.get("triage_parsed")
    if isinstance(triage, Mapping) and triage:
        st.caption(
            f"Model triage: {triage.get('triage_label', 'Not recorded')} · {plain_name(triage.get('referral_action'))}"
        )
    else:
        st.warning("The model’s structured triage could not be read.")
    with st.expander("Raw response and timing"):
        st.code(str(row.get("response", "")), language="text", wrap_lines=True)
        st.json(triage or {})
        latency = row.get("latency_sec")
        if isinstance(latency, (int, float)):
            st.caption(f"Response time: {latency:.1f} seconds")


def _render_jury(
    row: Mapping[str, Any],
    principles: Sequence[Mapping[str, Any]] | None,
    *,
    key_prefix: str,
) -> None:
    names = {int(p["id"]): plain_name(p.get("name")) for p in principles or []}
    scores = row.get("judge_scores") or []
    if not scores:
        st.info("No judge scores recorded.")
        return
    readable_table(
        [
            {
                "Principle": f"P{cell.get('principle_id')} · {names.get(int(cell.get('principle_id', 0)), '')}",
                "Judge": model_name(cell.get("judge_model_id")),
                "Score / 5": _format_score(cell.get("score"))
                if cell.get("judge_parse_succeeded", True)
                else "Failed",
            }
            for cell in scores
        ],
        label="Scores by principle",
    )
    st.caption(
        "Each usable score contributes equally to the mean. Read the exact reasoning in Judge trace."
    )
    with st.expander("Score heatmap"):
        render_judge_heatmap(scores, principles=principles, key=f"{key_prefix}_heatmap")
    for cell in scores:
        reason = cell.get("rationale") or cell.get("reason")
        if reason:
            with st.expander(
                f"P{cell.get('principle_id')} · {model_name(cell.get('judge_model_id'))} reasoning"
            ):
                st.write(reason)


def _render_final_method_decision(row: Mapping[str, Any]) -> None:
    decision = row.get("decision") or {}
    if not decision:
        st.info("No automated answer decision recorded.")
        return
    score = _format_score(decision.get("jury_safety_mean"))
    st.markdown(
        f"**Answer review: {'Flagged' if decision.get('flagged') else 'Unflagged'}** · {score} / 5 · {decision.get('triage_label', '?')} score band"
    )
    if decision.get("judge_score_incomplete"):
        st.warning("Incomplete judge scores require human review.")
    else:
        st.caption(
            "The answer is flagged below 4 / 5. This score evaluates the answer, not the patient’s urgency."
        )


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
    if st.button("Add to human review", key=key):
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

    st.caption(
        f"{prompt_id} · {risk_name(reference_risk_tier(reference_item))} patient urgency"
    )
    st.markdown("**Patient prompt**")
    st.write(reference_item.get("hindi_text", ""))
    answer_tab, reference_tab, scores_tab = st.tabs(["Answer", "Reference", "Scores"])
    with answer_tab:
        _render_final_method_decision(methodology_row or {})
        _render_panel_response(methodology_row or {})
    with reference_tab:
        _render_ground_truth(reference_item)
    with scores_tab:
        _render_jury(
            methodology_row or {},
            constitution_principles,
            key_prefix=f"{key_prefix}_{prompt_id}",
        )
        if cerai_scores:
            with st.expander("CeRAI comparison"):
                _render_cerai_verdict(cerai_scores)
        with st.expander("Human review history"):
            _render_hitl_history(prompt_id, hitl_reviews, session_reviews)
    _render_send_to_hitl(prompt_id, key=f"{key_prefix}_hitl_btn_{prompt_id}")


__all__ = ["render_case_detail"]
