"""Server-side regressions for review submission and threshold/filter interactions."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "streamlit_app" / "workbench_pages"
FORM_SCRIPT = """
import streamlit as st
from streamlit_app.components.hitl_form import render_hitl_form
record = render_hitl_form(
    prompt_id="qa-only", healtheval_decision={"flagged": True, "jury_safety_mean": 3.6},
    cerai_decision={"flagged": None}, inspect_decision={},
    panel_response_excerpt="QA fixture only. This is not a clinical review.",
)
if record is not None:
    st.session_state["record"] = record
"""


def test_review_requires_explicit_verdict():
    app = AppTest.from_string(FORM_SCRIPT).run()
    assert not app.exception
    assert app.selectbox(key="hitl_form__qa-only__decision").value is None
    app.button[0].click().run()
    assert app.error
    assert "record" not in app.session_state


@pytest.mark.parametrize("verdict,expected_safe", [("safe", True), ("unsafe", False)])
def test_explicit_safety_verdict_wins_and_missing_comparators_are_omitted(
    verdict, expected_safe
):
    app = AppTest.from_string(FORM_SCRIPT).run()
    app.selectbox(key="hitl_form__qa-only__decision").select(verdict)
    app.checkbox(key="hitl_form__qa-only__safe").set_value(not expected_safe)
    app.button[0].click().run()
    assert not app.exception
    record = app.session_state["record"]
    assert record["model_response_safe"] is expected_safe
    assert record["original_evaluators"] == {"healtheval_safety_method": "unsafe"}
    assert record["human_decision_targets"] == ["healtheval_safety_method"]
    assert record["failure_category"] == ""
    assert record["persistence_mode"] == "session_local"


def test_escalation_and_scoring_example_reason_are_respected():
    app = AppTest.from_string(FORM_SCRIPT).run()
    app.selectbox(key="hitl_form__qa-only__decision").select("escalate")
    app.checkbox(key="hitl_form__qa-only__promote").check()
    app.button[0].click().run()
    assert app.error
    assert "record" not in app.session_state
    app.text_area(key="hitl_form__qa-only__promote_reason").input("QA-only reason")
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["record"]["needs_clinician_review"] is True
    assert app.session_state["record"]["promote_reasoning"] == "QA-only reason"


def test_case_filter_shows_only_two_flagged_sarvam_answers():
    app = AppTest.from_file(str(PAGES / "3_Case_Explorer.py"), default_timeout=30).run()
    app.sidebar.selectbox[0].select("sarvam-105b").run()
    app.sidebar.selectbox[1].select("true").run()
    assert not app.exception
    assert app.subheader[0].value == "2 matching cases"
    assert [
        option.split(" · ")[0]
        for option in app.selectbox(key="case_explorer_choice").options
    ] == ["ref-015", "ref-029"]
    app.sidebar.selectbox[0].select("sarvam-105b-conversations").run()
    assert not app.exception
    assert app.subheader[0].value == "0 matching cases"


def test_threshold_slider_lower_boundary_does_not_create_invalid_range():
    app = AppTest.from_file(
        str(PAGES / "5_Safety_Thresholds.py"), default_timeout=30
    ).run()
    assert not app.exception
    app.sidebar.slider[0].set_value(1.1).run()
    assert not app.exception
    app.sidebar.slider[0].set_value(5.0).run()
    assert not app.exception


@pytest.mark.parametrize(
    "rubric",
    [
        "health_safety_v1",
        "factuality_v1",
        "limitation_awareness_v1",
        "triage_schema_v1",
    ],
)
def test_each_rubric_renders_all_evidence_tabs(rubric):
    app = AppTest.from_file(
        str(PAGES / "7_Scoring_Rubrics.py"), default_timeout=30
    ).run()
    app.sidebar.selectbox[0].select(rubric).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Scoring guide",
        "Principles",
        "References",
        "Judge examples",
    ]


def test_manually_added_routine_case_reaches_the_review_queue():
    app = AppTest.from_file(
        str(PAGES / "4_Human_Review_Queue.py"), default_timeout=30
    ).run()
    assert not any("ref-001" in expander.label for expander in app.expander)
    app.session_state["hitl_queue_target"] = ["ref-001"]
    app.run()
    assert not app.exception
    assert any("ref-001" in expander.label for expander in app.expander)
    assert (
        "manual_review" in app.sidebar.multiselect[0].value
        or "Added from Cases" in app.sidebar.multiselect[0].options
    )
