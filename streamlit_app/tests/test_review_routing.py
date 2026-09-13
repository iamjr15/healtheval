"""Missing comparisons cannot clear an answer or create a disagreement."""
import pytest

from streamlit_app.review_routing import decision_review_reasons


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
