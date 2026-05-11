"""Case Explorer page."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from streamlit_app.components.case_detail_modal import render_case_detail
from streamlit_app.data_loaders import (
    load_cerai_metrics,
    load_constitution,
    load_hitl_reviews,
    load_inspect_safety,
    load_methodology_artifact,
    load_reference_set,
    methodology_for_model,
    methodology_model_ids,
)


_LOW_JUDGE_SCORE_CUTOFF: int = 2


def _index_rows(rows: list[dict]) -> dict[str, dict]:
    """Index methodology rows by ``prompt_id`` for O(1) lookup."""
    return {str(r.get("prompt_id")): r for r in rows if r.get("prompt_id")}


def _index_outputs(outputs: Mapping[str, dict]) -> dict[str, dict]:
    return {str(k): dict(v) for k, v in outputs.items()}


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
    cerai_outputs: Mapping[str, Any],
    inspect_outputs: Mapping[str, Any],
    hitl_by_prompt: Mapping[str, list],
) -> dict[str, Any]:
    pid = item.get("id", "")
    m_out = methodology_outputs.get(pid, {})
    cerai_out = cerai_outputs.get(pid, {})
    inspect_out = inspect_outputs.get(pid, {})

    return {
        "ref_id": pid,
        "hindi_text": (
            (item.get("hindi_text", "") or "")[:80]
            + ("…" if len(item.get("hindi_text", "") or "") > 80 else "")
        ),
        "expected_triage_label": item.get("expected_triage_label", "?"),
        "parse_ok": bool(m_out.get("parse_succeeded", methodology_row.get("parse_succeeded") if methodology_row else False)),
        "maaswasth_flagged": bool(m_out.get("flagged")),
        "cerai_flagged": bool(cerai_out.get("flagged")),
        "inspect_flagged": bool(inspect_out.get("flagged")),
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
    cerai_out: Mapping[str, Any],
    inspect_out: Mapping[str, Any],
    *,
    parse_failed: str,
    maaswasth_flagged: str,
    cerai_disagrees: str,
    inspect_disagrees: str,
    expected_urgent: bool,
    triage_green_but_expected_refer: bool,
    low_judge_score: bool,
    hitl_status_filter: str,
    persona_caste: str,
    persona_geo: str,
    persona_edu: str,
) -> bool:
    if parse_failed != "all":
        want = parse_failed == "true"
        if (not table_row["parse_ok"]) != want:
            return False
    if maaswasth_flagged != "all":
        want = maaswasth_flagged == "true"
        if bool(table_row["maaswasth_flagged"]) != want:
            return False
    if cerai_disagrees != "all":
        disagrees = (
            bool(table_row["cerai_flagged"])
            != bool(table_row["maaswasth_flagged"])
        )
        want = cerai_disagrees == "true"
        if disagrees != want:
            return False
    if inspect_disagrees != "all":
        disagrees = (
            bool(table_row["inspect_flagged"])
            != bool(table_row["maaswasth_flagged"])
        )
        want = inspect_disagrees == "true"
        if disagrees != want:
            return False
    if expected_urgent and item.get("expected_safety_action") != "urgent":
        return False
    if triage_green_but_expected_refer:
        triage = (methodology_row or {}).get("triage_parsed") or {}
        if not (
            triage.get("triage_label") == "GREEN"
            and item.get("expected_safety_action") in ("refer", "urgent")
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
            cerai_row=ctx["cerai_rows_by_id"].get(prompt_id),
            inspect_row=ctx["inspect_rows_by_id"].get(prompt_id),
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
            help="Choose which model's saved n=30 results to inspect.",
        )
    elif model_ids:
        selected_model = model_ids[0]
    artefact = methodology_for_model(raw_artefact, selected_model)
    methodology_rows = artefact.get("rows", []) or []
    methodology_outputs = artefact.get("evaluator_outputs", {}) or {}
    methodology_rows_by_id = _index_rows(list(methodology_rows))

    cerai = load_cerai_metrics()
    inspect = load_inspect_safety()
    cerai_outputs = _index_outputs(cerai.get("evaluator_outputs", {}) or {})
    inspect_outputs = _index_outputs(inspect.get("evaluator_outputs", {}) or {})
    cerai_rows_by_id = _index_rows(list(cerai.get("rows", []) or []))
    inspect_rows_by_id = _index_rows(list(inspect.get("rows", []) or []))

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
    parse_failed = st.sidebar.selectbox(
        "Triage JSON failed to parse",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    maaswasth_flagged = st.sidebar.selectbox(
        "MaaSwasth Safety Method flagged risk",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    cerai_disagrees = st.sidebar.selectbox(
        "CeRAI disagrees with MaaSwasth Safety Method",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    inspect_disagrees = st.sidebar.selectbox(
        "Inspect scorer disagrees with MaaSwasth Safety Method",
        ["all", "true", "false"],
        index=0,
        format_func=_yes_no_any_label,
    )
    expected_urgent = st.sidebar.checkbox("Expected urgent referral")
    triage_green_but_expected_refer = st.sidebar.checkbox(
        "Model said GREEN, but reference expected referral"
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
            cerai_outputs,
            inspect_outputs,
            hitl_by_prompt,
        )
        if not _filter_passes(
            it,
            row,
            m_row,
            cerai_outputs.get(pid, {}),
            inspect_outputs.get(pid, {}),
            parse_failed=parse_failed,
            maaswasth_flagged=maaswasth_flagged,
            cerai_disagrees=cerai_disagrees,
            inspect_disagrees=inspect_disagrees,
            expected_urgent=expected_urgent,
            triage_green_but_expected_refer=triage_green_but_expected_refer,
            low_judge_score=low_judge_score,
            hitl_status_filter=hitl_status_filter,
            persona_caste=persona_caste,
            persona_geo=persona_geo,
            persona_edu=persona_edu,
        ):
            continue
        table_rows.append(row)

    st.markdown(f"### {len(table_rows)} of {len(items)} cases match")

    if table_rows:
        import pandas as pd  # noqa: PLC0415

        df = pd.DataFrame(table_rows)
        st.dataframe(
            df,
            width="stretch",
            hide_index=True,
            column_config={
                "ref_id": "Ref id",
                "hindi_text": "Hindi prompt (truncated)",
                "expected_triage_label": "Expected triage",
                "parse_ok": "Triage JSON parsed",
                "maaswasth_flagged": "MaaSwasth Safety Method flagged",
                "cerai_flagged": "CeRAI flagged",
                "inspect_flagged": "Inspect flagged",
                "hitl_status": "Human review",
            },
        )

        choice = st.selectbox(
            "Select a case to inspect",
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
                "cerai_rows_by_id": cerai_rows_by_id,
                "inspect_rows_by_id": inspect_rows_by_id,
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
