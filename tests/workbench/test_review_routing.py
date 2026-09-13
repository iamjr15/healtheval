"""Missing comparisons cannot clear an answer or create a disagreement."""
import pytest

from streamlit_app.review_routing import comparison_disagrees, comparison_review_flag, decision_review_reasons


@pytest.mark.parametrize(
    "methodology,cerai,inspect,expected",
    [
        ({"flagged": True}, {}, {}, ["answer_flagged"]),
        ({"flagged": True}, {"flagged": None}, {}, ["answer_flagged"]),
        ({"flagged": True}, {"flagged": True}, {"flagged": True}, ["answer_flagged"]),
        ({"flagged": False}, {}, {}, []),
        ({"flagged": False}, {"flagged": True}, {}, ["cerai_vs_methodology_disagree"]),
        ({"flagged": True}, {}, {"flagged": False}, ["answer_flagged", "inspect_vs_methodology_disagree"]),
        ({}, {"flagged": True}, {}, []),
    ],
)
def test_review_decisions_respect_evidence_availability(methodology, cerai, inspect, expected):
    assert decision_review_reasons(methodology, cerai, inspect) == expected


@pytest.mark.parametrize("score", [None, "not-a-score", float("nan"), float("inf")])
def test_missing_comparator_cannot_pass_or_create_filter_agreement(score):
    flag = comparison_review_flag(score, 0.5)
    assert flag is None
    assert comparison_disagrees(True, flag) is None
    assert comparison_disagrees(False, flag) is None


@pytest.mark.parametrize("score,expected", [(0.2, True), (0.5, False), (0.8, False)])
def test_available_comparator_keeps_threshold_semantics(score, expected):
    flag = comparison_review_flag(score, 0.5)
    assert flag is expected
    assert comparison_disagrees(expected, flag) is False
    assert comparison_disagrees(not expected, flag) is True
