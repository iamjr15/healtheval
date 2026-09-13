"""Case Explorer page."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from eval.reference_risk import (
    REFERENCE_RISK_ORDER,
    reference_risk_label,
    reference_risk_tier,
)
from streamlit_app.components.case_detail_modal import render_case_detail
from streamlit_app.config import CERAI_DB_SCORE_CUTOFF
from streamlit_app.review_routing import comparison_disagrees, comparison_review_flag
from streamlit_app.data_loaders import (
    load_cerai_db_scores,
    load_constitution,
    load_hitl_reviews,
    load_methodology_artifact,
    load_reference_set,
    methodology_for_model,
    methodology_model_ids,
)


_LOW_JUDGE_SCORE_CUTOFF: int = 2


def _cerai_routes_from_scores(scores: Mapping[str, Any] | None) -> bool | None:
    return comparison_review_flag((scores or {}).get("mean"), CERAI_DB_SCORE_CUTOFF)


def _index_rows(rows: list[dict]) -> dict[str, dict]:
    """Index methodology rows by ``prompt_id`` for O(1) lookup."""
    return {str(r.get("prompt_id")): r for r in rows if r.get("prompt_id")}


def _row_low_judge_score(row: Mapping[str, Any], cutoff: float) -> bool:
    for cell in row.get("judge_scores", []) or []:
        try:
            if float(cell.get("score", 5)) <= cutoff:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _build_table_row(
    item: Mapping[str, Any],
    methodology_outputs: Mapping[str, Any],
    methodology_row: Mapping[str, Any] | None,
    cerai_scores_by_prompt: Mapping[str, Any],
    hitl_by_prompt: Mapping[str, list],
) -> dict[str, Any]:
    pid = item.get("id", "")
    m_out = methodology_outputs.get(pid, {})
    cerai_scores = cerai_scores_by_prompt.get(pid, {})
    decision = (methodology_row or {}).get("decision", {}) if methodology_row else {}
    tier = reference_risk_tier(item)

    return {
        "ref_id": pid,
        "reference_risk_tier": tier,
        "reference_risk": reference_risk_label(tier),
        "hindi_text": (
            (item.get("hindi_text", "") or "")[:80]
            + ("…" if len(item.get("hindi_text", "") or "") > 80 else "")
        ),
        "healtheval_flagged": bool(m_out.get("flagged")),
        "judge_failures": int(
            decision.get(
                "n_failed_judge_cells",
                m_out.get("n_failed_judge_cells", 0),
        )
        or 0
    ),
        "cerai_db_mean": cerai_scores.get("mean"),
        "cerai_flagged": _cerai_routes_from_scores(cerai_scores),
        "hitl_status": (
            f"{len(hitl_by_prompt.get(pid, []))} review(s)"
            if hitl_by_prompt.get(pid)
            else "not reviewed"
        ),
    }


def _filter_passes(
    item: Mapping[str, Any],
    table_row: Mapping[str, Any],
    methodology_row: Mapping[str, Any] | None,
    *,
    healtheval_flagged: str,
    cerai_disagrees: str,
    expected_urgent: bool,
    low_judge_score: bool,
    hitl_status_filter: str,
    persona_caste: str,
    persona_geo: str,
    persona_edu: str,
    reference_risk_filter: str,
) -> bool:
    if healtheval_flagged != "all":
        want = healtheval_flagged == "true"
        if bool(table_row["healtheval_flagged"]) != want:
            return False
    if cerai_disagrees != "all":
        disagrees = comparison_disagrees(
            table_row["healtheval_flagged"], table_row["cerai_flagged"]
        )
        want = cerai_disagrees == "true"
        if disagrees is None or disagrees != want:
            return False
    if expected_urgent and item.get("expected_safety_action") != "urgent":
        return False
    if (
        reference_risk_filter != "any"
        and table_row["reference_risk_tier"] != reference_risk_filter
    ):
        return False
    if low_judge_score and not _row_low_judge_score(
        methodology_row or {}, _LOW_JUDGE_SCORE_CUTOFF
    ):
        return False
    if hitl_status_filter == "human_reviewed" and table_row["hitl_status"] == "not reviewed":
        return False
    if hitl_status_filter == "not_reviewed" and table_row["hitl_status"] != "not reviewed":
        return False
    persona = item.get("persona_metadata") or {}
    if persona_caste != "any" and str(persona.get("caste", "")).lower() != persona_caste.lower():
        return False
    if persona_geo != "any" and str(persona.get("geography", "")).lower() != persona_geo.lower():
        return False
    if persona_edu != "any" and str(persona.get("education_level", "")).lower() != persona_edu.lower():
        return False
    return True


def _persona_options(items: list[dict], field: str) -> list[str]:
    seen: list[str] = []
    for it in items:
        v = (it.get("persona_metadata") or {}).get(field, "")
        if v and v not in seen:
            seen.append(str(v))
    return ["any"] + seen


def _yes_no_any_label(value: str) -> str:
    return {"all": "Any", "true": "Yes", "false": "No"}.get(value, value)


def _human_review_label(value: str) -> str:
    return {
        "all": "Any",
        "human_reviewed": "Human-reviewed",
        "not_reviewed": "Not reviewed",
    }.get(value, value)


def _any_label(value: str) -> str:
    return "Any" if value == "any" else value


def _open_modal(prompt_id: str, ctx: dict) -> None:
    """Render the case detail dialog, falling back to inline content."""

    def _body() -> None:
        render_case_detail(
            prompt_id=prompt_id,
            reference_item=ctx["ref_by_id"].get(prompt_id),
            methodology_row=ctx["methodology_rows_by_id"].get(prompt_id),
            cerai_scores=ctx["cerai_scores_by_prompt"].get(prompt_id),
            constitution_principles=ctx["principles"],
            hitl_reviews=ctx["hitl_reviews"],
            session_reviews=st.session_state.get("hitl_reviews", []),
        )

    dialog = getattr(st, "dialog", None)
    if dialog is not None:
        @st.dialog(f"Case detail — {prompt_id}", width="large")  # type: ignore[misc]
        def _show() -> None:
            _body()

        _show()
    else:
        st.divider()
        _body()


def main() -> None:
    st.title("Reference Case Explorer")
    st.caption(
        "Browse the 30 fixed test cases. Open a case to compare the expected "
        "answer, the model response, evaluator decisions, judge scores, and "
        "any human reviews."
    )

    refset = load_reference_set()
    items = list(refset.get("items", []) or [])

    raw_artefact, selected_path, _calibration_suffix = load_methodology_artifact()
    model_ids = methodology_model_ids(raw_artefact)
    selected_model = None
    if len(model_ids) > 1:
        selected_model = st.sidebar.selectbox(
            "Panel model",
            model_ids,
            index=0,
            help="Choose which model's saved n=30 results to review.",
        )
    elif model_ids:
        selected_model = model_ids[0]
    artefact = methodology_for_model(raw_artefact, selected_model)
    methodology_rows = artefact.get("rows", []) or []
    methodology_outputs = artefact.get("evaluator_outputs", {}) or {}
    methodology_rows_by_id = _index_rows(list(methodology_rows))

    cerai_scores_by_prompt = load_cerai_db_scores().get("scores_by_prompt", {})

    principles = list(load_constitution().get("principles", []) or [])

    hitl_repo = load_hitl_reviews()
    hitl_session = st.session_state.get("hitl_reviews", [])
    hitl_by_prompt: dict[str, list] = {}
    for r in list(hitl_repo) + list(hitl_session):
        hitl_by_prompt.setdefault(str(r.get("prompt_id", "")), []).append(r)

    ref_by_id = {str(it.get("id")): it for it in items}
    st.sidebar.header("Show Cases Where")
    st.sidebar.caption(
        f"Complete result file: `{selected_path.name}` "
        f"(model `{selected_model or 'single target'}`)."
    )
    healtheval_flagged = st.sidebar.selectbox(
        "HealthEval flags response",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    cerai_disagrees = st.sidebar.selectbox(
        "CeRAI DB decision disagrees with HealthEval Safety Method",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    expected_urgent = st.sidebar.checkbox("Expected urgent referral")
    reference_risk_filter = st.sidebar.selectbox(
        "Reference risk tier",
        ["any"] + list(REFERENCE_RISK_ORDER),
        index=0,
        format_func=lambda v: "Any" if v == "any" else reference_risk_label(v),
    )
    low_judge_score = st.sidebar.checkbox(
        f"Any judge score ≤ {_LOW_JUDGE_SCORE_CUTOFF:g}"
    )
    hitl_status_filter = st.sidebar.selectbox(
        "Human review status",
        ["all", "human_reviewed", "not_reviewed"],
        index=0,
        format_func=_human_review_label,
    )
    persona_caste = st.sidebar.selectbox(
        "Persona caste", _persona_options(items, "caste"), index=0, format_func=_any_label
    )
    persona_geo = st.sidebar.selectbox(
        "Persona geography",
        _persona_options(items, "geography"),
        index=0,
        format_func=_any_label,
    )
    persona_edu = st.sidebar.selectbox(
        "Persona education",
        _persona_options(items, "education_level"),
        index=0,
        format_func=_any_label,
    )
    table_rows: list[dict] = []
    for it in items:
        pid = str(it.get("id", ""))
        m_row = methodology_rows_by_id.get(pid)
        row = _build_table_row(
            it,
            methodology_outputs,
            m_row,
            cerai_scores_by_prompt,
            hitl_by_prompt,
        )
        if not _filter_passes(
            it,
            row,
            m_row,
            healtheval_flagged=healtheval_flagged,
            cerai_disagrees=cerai_disagrees,
            expected_urgent=expected_urgent,
            low_judge_score=low_judge_score,
            hitl_status_filter=hitl_status_filter,
            persona_caste=persona_caste,
            persona_geo=persona_geo,
            persona_edu=persona_edu,
            reference_risk_filter=reference_risk_filter,
        ):
            continue
        table_rows.append(row)

    st.markdown(f"### {len(table_rows)} of {len(items)} cases match")
    st.caption(
        "`Reference risk` describes the prompt. `Flags response = true` means "
        "that evaluator judged the saved model answer as needing human review; "
        "`false` means it passed that evaluator. CeRAI uses the Docker DB mean "
        "of Accuracy, Relevance, and Hallucination scores."
    )

    if table_rows:
        import pandas as pd  # noqa: PLC0415

        df = pd.DataFrame(table_rows)
        st.dataframe(
            df[
                [
                    "ref_id",
                    "reference_risk",
                    "hindi_text",
                    "healtheval_flagged",
                    "cerai_db_mean",
                    "cerai_flagged",
                ]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "ref_id": "Ref id",
                "reference_risk": "Reference risk",
                "hindi_text": "Hindi prompt (truncated)",
                "healtheval_flagged": "HealthEval flags response",
                "cerai_db_mean": "CeRAI DB mean",
                "cerai_flagged": "CeRAI routes response",
            },
        )

        choice = st.selectbox(
            "Select a case to open",
            options=[r["ref_id"] for r in table_rows],
            key="case_explorer_choice",
        )
        cols = st.columns([1, 5])
        with cols[0]:
            open_modal = st.button("Open Case Detail", type="primary")
        if open_modal and choice:
            ctx = {
                "ref_by_id": ref_by_id,
                "methodology_rows_by_id": methodology_rows_by_id,
                "cerai_scores_by_prompt": cerai_scores_by_prompt,
                "principles": principles,
                "hitl_reviews": hitl_repo,
            }
            _open_modal(choice, ctx)
    else:
        st.info(
            "No cases match the current filters. Widen the filters in the sidebar.",
            icon="ℹ️",
        )


main()
