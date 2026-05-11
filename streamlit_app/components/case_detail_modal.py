"""Reusable case-detail drill-down for the Case Explorer page."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st

from .judge_score_heatmap import render_judge_heatmap
from .triage_card import render_triage_card


def _safe_get(d: Mapping[str, Any] | None, *keys: str, default: Any = None) -> Any:
    """Walk a chain of ``.get()`` calls tolerantly."""
    cur: Any = d or {}
    for k in keys:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(k, default)
    return cur


def _render_ground_truth(item: Mapping[str, Any]) -> None:
    st.markdown("### Reference Answer")
    cols = st.columns(3)
    with cols[0]:
        st.metric("Expected triage", str(item.get("expected_triage_label", "?")))
    with cols[1]:
        st.metric(
            "Expected safety action", str(item.get("expected_safety_action", "?"))
        )
    with cols[2]:
        rf = item.get("red_flag_match_required") or []
        st.metric("Required red flags", f"{len(rf)}")

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
        with st.expander("Source paragraph (verbatim guideline)", expanded=False):
            st.markdown(src_para)

    src_url = item.get("source_url", "")
    if src_url:
        st.markdown(f"[Source URL →]({src_url})")


def _render_panel_response(row: Mapping[str, Any]) -> None:
    st.markdown("### Model Response")
    if not row:
        st.warning("No MaaSwasth Safety Method row found for this prompt.", icon="⚠️")
        return

    parse_ok = bool(row.get("parse_succeeded"))
    cols = st.columns(3)
    with cols[0]:
        st.metric("Triage JSON parsed", "✅" if parse_ok else "❌")
    with cols[1]:
        latency = row.get("latency_sec")
        st.metric("Panel latency", f"{latency:.1f}s" if isinstance(latency, (int, float)) else "?")
    with cols[2]:
        st.metric("Response length", f"{len(row.get('response', ''))} chars")

    with st.expander("Full Hindi response", expanded=False):
        st.write(row.get("response", ""))

    st.markdown("**Parsed triage JSON**")
    render_triage_card(row.get("triage_parsed"))


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
                help="Decision from the judge-score band before the model triage union is applied.",
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


def _render_final_method_decision(row: Mapping[str, Any]) -> None:
    """Show model triage, judge band, and final routing separately."""
    st.markdown("### MaaSwasth Safety Method Decision")
    decision = row.get("decision") or {}
    triage = row.get("triage_parsed") or {}
    if decision:
        cols = st.columns(5)
        with cols[0]:
            st.metric("Model triage", triage.get("triage_label", "?"))
        with cols[1]:
            st.metric("Judge score band", decision.get("triage_label", "?"))
        with cols[2]:
            st.metric(
                "Final routing",
                "🚩 YES" if decision.get("flagged") else "✅ NO",
            )
        with cols[3]:
            mean = decision.get("jury_safety_mean")
            st.metric(
                "Judge safety mean",
                f"{mean:.2f}" if isinstance(mean, (int, float)) else "?",
            )
        with cols[4]:
            st.metric(
                "Uses model triage",
                "Yes" if decision.get("union_with_response_triage") else "No",
            )
        st.caption(
            "Final routing flags a case if either the judge score band or the "
            "model's parsed triage label indicates risk."
        )
    else:
        st.warning("MaaSwasth Safety Method decision is missing for this case.", icon="⚠️")


def _render_cerai_inspect(
    cerai_row: Mapping[str, Any] | None, inspect_row: Mapping[str, Any] | None
) -> None:
    cols = st.columns(2)
    with cols[0]:
        st.markdown("### CeRAI Verdict")
        if not cerai_row:
            st.caption("(no CeRAI row for this prompt)")
        else:
            bleu = cerai_row.get("bleu_vs_source")
            flagged = cerai_row.get("flagged")
            st.metric(
                "BLEU vs source",
                f"{bleu:.4f}" if isinstance(bleu, (int, float)) else "?",
            )
            st.metric(
                "CeRAI flagged risk?",
                "🚩 YES" if flagged else "✅ NO",
            )
            with st.expander("Full CeRAI row", expanded=False):
                st.json(cerai_row)
    with cols[1]:
        st.markdown("### Inspect Verdict")
        if not inspect_row:
            st.caption("(no Inspect row for this prompt)")
        else:
            comp = inspect_row.get("composite_score")
            flagged = inspect_row.get("flagged")
            st.metric(
                "Composite score",
                f"{comp:.3f}" if isinstance(comp, (int, float)) else "?",
            )
            st.metric(
                "Inspect flagged risk?",
                "🚩 YES" if flagged else "✅ NO",
            )
            with st.expander("Full Inspect row", expanded=False):
                st.json(inspect_row)


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
    cerai_row: Mapping[str, Any] | None,
    inspect_row: Mapping[str, Any] | None,
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
    _render_cerai_inspect(cerai_row, inspect_row)
    st.divider()
    _render_hitl_history(prompt_id, hitl_reviews, session_reviews)
    st.divider()
    _render_send_to_hitl(prompt_id, key=f"{key_prefix}_hitl_btn_{prompt_id}")


__all__ = ["render_case_detail"]
