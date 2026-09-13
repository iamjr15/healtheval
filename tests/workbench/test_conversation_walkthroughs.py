"""Saved example views never invent current model responses or scores."""
from streamlit_app import conversation_walkthroughs as view

def test_no_results_yields_no_examples(monkeypatch):
    monkeypatch.setattr(view, 'load_methodology_artifact', lambda: ({'rows': []}, None, ''))
    assert view.walkthrough_summary_rows() == []

def test_saved_response_and_score_are_preserved(monkeypatch):
    row = {'prompt_id': 'ref-001', 'model_id': 'test-model', 'prompt': 'test prompt', 'response': 'test response', 'decision': {'triage_label': 'AMBER', 'flagged': True, 'jury_safety_mean': 3.7}}
    monkeypatch.setattr(view, 'load_methodology_artifact', lambda: ({'rows': [row]}, None, ''))
    shown = view.walkthrough_summary_rows()[0]
    assert shown['Response'] == row['response']
    assert shown['Jury mean'] == 3.7
    assert shown['Needs review'] is True
