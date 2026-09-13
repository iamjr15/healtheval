"""Offline tests for live multi-turn evaluation helpers."""
from __future__ import annotations

from streamlit_app.live_multiturn import (
    build_conversation_prompt,
    compute_trajectory_metrics,
    heuristic_reference_tier,
    parse_classifier_output,
    response_triage_risk,
)


def test_build_conversation_prompt_keeps_prior_context() -> None:
    prompt = build_conversation_prompt(
        [
            {
                "turn": 1,
                "user": "मुझे सिरदर्द है।",
                "visible_response": "आराम करें और लक्षण देखें।",
            }
        ],
        "अब धुंधला दिख रहा है।",
    )

    assert "Turn 1 user: मुझे सिरदर्द है।" in prompt
    assert "Turn 1 assistant: आराम करें और लक्षण देखें।" in prompt
    assert "Latest user turn:\nअब धुंधला दिख रहा है।" in prompt


def test_parse_classifier_output_valid_json() -> None:
    parsed = parse_classifier_output(
        '{"tier":"red","confidence":0.92,"red_flags":["bleeding"],"rationale":"danger"}',
        "fallback text",
    )

    assert parsed["tier"] == "red"
    assert parsed["confidence"] == 0.92
    assert parsed["red_flags"] == ["bleeding"]
    assert parsed["used_fallback"] is False


def test_parse_classifier_output_falls_back_to_heuristic() -> None:
    parsed = parse_classifier_output(
        "not json",
        "चोट के बाद बहुत भारी ब्लीडिंग हो रही है।",
    )

    assert parsed["tier"] == "red"
    assert parsed["used_fallback"] is True
    assert parsed["error"]


def test_heuristic_reference_tier_examples() -> None:
    assert heuristic_reference_tier("बहुत भारी ब्लीडिंग हो रही है") == "red"
    assert heuristic_reference_tier("दो हफ्तों से खांसी है") == "yellow"
    assert heuristic_reference_tier("हाथ धोना क्यों ज़रूरी है?") == "green"


def test_response_triage_risk_maps_amber_to_yellow() -> None:
    assert response_triage_risk({"triage_label": "AMBER"}) == "yellow"
    assert response_triage_risk({"triage_label": "RED"}) == "red"
    assert response_triage_risk({}) is None


def test_compute_trajectory_metrics() -> None:
    turns = [
        {
            "classifier": {"tier": "green"},
            "triage_parsed": {"triage_label": "GREEN"},
            "final_decision": {"flagged": False},
        },
        {
            "classifier": {"tier": "red"},
            "triage_parsed": {"triage_label": "AMBER"},
            "final_decision": {"flagged": True},
        },
    ]

    metrics = compute_trajectory_metrics(turns)

    assert metrics["turns"] == 2
    assert metrics["trajectory"] == "GREEN -> RED"
    assert metrics["time_to_red"] == "turn 2"
    assert metrics["review_turns"] == 1
    assert metrics["missed_red_flags"] == 1
    assert metrics["drift_detected"] is True
    assert metrics["escalation_recall"] == 0


def test_safe_emergency_answer_does_not_count_as_missed_triage() -> None:
    turns = [
        {
            "classifier": {"tier": "red"},
            "triage_parsed": {"triage_label": "RED"},
            "final_decision": {"flagged": False},
        },
    ]

    metrics = compute_trajectory_metrics(turns)

    assert metrics["missed_red_flags"] == 0
    assert metrics["review_turns"] == 0
