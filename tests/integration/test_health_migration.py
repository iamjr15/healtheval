import json
from collections import Counter, defaultdict
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_full_offline_pipeline_and_current_fingerprint(offline_panel):
    from eval.benchmark import require_current_benchmark
    from streamlit_app.canonical_selector import select_complete_methodology_artifact
    path = offline_panel / 'methodology_panel_refset_eval.json'
    artifact = json.loads(path.read_text())
    require_current_benchmark(artifact)
    assert artifact['n_prompts_done'] == artifact['n_prompts_total'] == 120
    assert len(artifact['complete_panel_models']) == 4
    assert select_complete_methodology_artifact((path,)) == path
    for model, run in artifact['models'].items():
        assert len(run['rows']) == 30
        assert len(run['jury']) == 2
        for row in run['rows']:
            assert row['parse_succeeded']
            assert not row['decision']['judge_score_incomplete']
            assert len(row['judge_scores']) == 10
    traces = [json.loads(line) for line in (offline_panel / 'judge_trace.jsonl').read_text().splitlines()]
    assert len(traces) == 1200


def test_stale_artifact_is_rejected():
    from eval.benchmark import require_current_benchmark
    with pytest.raises(ValueError, match='different benchmark'):
        require_current_benchmark({'benchmark_fingerprint': 'old-domain'})


def test_paired_equity_has_all_risks_and_matching_cases():
    refs = yaml.safe_load((ROOT / 'data/reference_set.yaml').read_text())['items']
    items = yaml.safe_load((ROOT / 'data/equity_challenges_hindi.yaml').read_text())['items']
    pairs = defaultdict(list)
    risks = defaultdict(Counter)
    for item in items:
        pairs[item['base_ref_id']].append(item)
        risks[item['category']][item['expected_triage_label']] += 1
    assert set(pairs) == {r['id'] for r in refs}
    assert all(len(group) == 6 for group in pairs.values())
    assert all(counts == {'RED': 10, 'AMBER': 10, 'GREEN': 10} for counts in risks.values())


def test_emergency_provenance_and_crisis_support():
    items = yaml.safe_load((ROOT / 'data/reference_set.yaml').read_text())['items']
    assert all(r['red_flag_match_required'] for r in items if r['expected_triage_label'] == 'RED')
    crisis = next(r for r in items if r['id'] == 'ref-024')
    assert crisis['refusal_expected'] is False
    assert len(crisis['source_citations']) >= 2
    assert all(r['review_status'] == 'pending_clinical_review' for r in items)


def test_gemini_env_alias(monkeypatch):
    from eval.panel_clients import google_api_key, validate_panel_env
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'test-value')
    validate_panel_env(['gemini-2.5-pro'])
    assert google_api_key() == 'test-value'


def test_gemini_reserves_budget_for_visible_response(monkeypatch):
    from types import SimpleNamespace
    from google import genai
    from eval.panel_clients import _call_google
    seen = []
    def generate_content(**kwargs):
        seen.append(kwargs['config'])
        return SimpleNamespace(text='test response')
    monkeypatch.setattr(genai, 'Client', lambda **_: SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    assert _call_google('health prompt', 'question') == 'test response'
    assert seen[0].max_output_tokens == 4096
    assert seen[0].thinking_config.thinking_budget == 512


def test_inspect_consumes_actual_health_inputs():
    from eval.inspect_tasks.safety import _samples_from_safety_subset
    from eval.inspect_tasks.equity import _samples_for_axis, EQUITY_STRATA
    safety = _samples_from_safety_subset()
    equity = [sample for axis in EQUITY_STRATA for sample in _samples_for_axis(axis)]
    assert len(safety) == 30
    assert len(equity) == 180
    assert all(len(sample.input) > 20 for sample in safety + equity)
