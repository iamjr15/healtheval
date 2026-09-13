"""Isolated full-pipeline fixtures: synthetic outputs never become shipped evidence."""
import json
from pathlib import Path
import pytest


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return Path(__file__).resolve().parent


@pytest.fixture(scope="session")
def offline_panel(tmp_path_factory):
    from scripts import run_panel_refset_eval as runner
    from scripts import compute_panel_tool_meta as aggregate
    from eval import judges
    from eval.panel_clients import PanelResponse

    target = tmp_path_factory.mktemp("healtheval-offline-e2e")
    refs = {row['hindi_text']: row for row in runner._load_reference_set()}

    def panel_call(model_id, system, prompt):
        ref = refs[prompt]
        triage = {'triage_label': ref['expected_triage_label'],
                  'referral_action': ref['expected_referral_action'],
                  'red_flags_detected': ref['red_flag_match_required'],
                  'triage_reason': 'Synthetic test fixture'}
        return PanelResponse(model_id, json.dumps(triage, ensure_ascii=False) + '\nSynthetic test answer', 0.01)

    def judge_call(*args, **kwargs):
        return json.dumps({'score': 5, 'confidence': 0.9, 'rubric_breakdown': {},
                           'failure_type': None, 'evidence': [], 'reason': 'Synthetic test fixture'})

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, 'validate_panel_env', lambda _: None)
        patch.setattr(runner, 'call_panel_model', panel_call)
        patch.setattr(judges, '_safe_call_judge', judge_call)
        for name in ('PANEL_DIR', 'OUT_PANEL', 'TRACE_PATH'):
            patch.setattr(runner, name, getattr(runner, name))
        assert runner.main(['--output-dir', str(target), '--judges', 'claude-sonnet-4-6,gemini-2.5-pro,sarvam-105b', '--model-workers', '2']) == 0
        assert aggregate.main(['--panel', str(target / 'methodology_panel_refset_eval.json'), '--output', str(target / 'tool_meta_evaluation.json')]) == 0
    return target
