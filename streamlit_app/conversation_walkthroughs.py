"""Saved current-benchmark examples; no authored model scores or trajectories."""
from __future__ import annotations
from streamlit_app.data_loaders import load_methodology_artifact, load_reference_items


def walkthrough_summary_rows() -> list[dict]:
    artifact, _, _ = load_methodology_artifact()
    refs = {r['id']: r for r in load_reference_items()}
    rows = []
    for row in artifact.get('rows', []):
        ref = refs.get(row.get('prompt_id'), {})
        decision = row.get('decision') or {}
        rows.append({'Case': row.get('prompt_id'), 'Model': row.get('model_id'),
                     'Topic': ref.get('health_topic'), 'Reference risk': ref.get('expected_triage_label'),
                     'Prompt': row.get('prompt'), 'Response': row.get('response'),
                     'Response band': decision.get('triage_label'),
                     'Needs review': decision.get('flagged'),
                     'Jury mean': decision.get('jury_safety_mean')})
    return rows
