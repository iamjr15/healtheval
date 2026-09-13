"""Exercise perturbation generation with isolated synthetic provider outputs."""
import json
import pytest
from eval.benchmark import benchmark_metadata
from scripts import generate_perturbations as generator
from scripts.build_base_responses import _split_response


def test_split_preserves_triage_exactly():
    block = '```json\n{"triage_label":"RED"}\n```\n'
    assert _split_response(block + 'अभी मदद लें।') == (block, 'अभी मदद लें।')
    assert _split_response('plain response') == ('', 'plain response')


@pytest.fixture
def generation_paths(tmp_path, monkeypatch):
    block = '```json\n{"triage_label":"RED"}\n```\n'
    base = {**benchmark_metadata(), 'prompt_id': 'ref-003', 'base_response': block + 'अभी 112 से मदद लें।', 'base_response_prose': 'अभी 112 से मदद लें।', 'base_response_triage_block': block}
    source = tmp_path / 'base.jsonl'
    source.write_text(json.dumps(base) + '\n')
    output = tmp_path / 'perturbed.jsonl'
    monkeypatch.setattr(generator, 'BASE_PATH', source)
    monkeypatch.setattr(generator, 'OUT_PATH', output)
    monkeypatch.setattr(generator, '_load_dotenv', lambda: None)
    monkeypatch.setattr(generator.time, 'sleep', lambda _: None)
    return base, output


def test_failed_verifier_parse_is_retried_not_accepted(generation_paths, monkeypatch):
    base, output = generation_paths
    monkeypatch.setattr(generator, '_generate', lambda text, _: text)
    attempts = []
    def verify(*args):
        attempts.append(1)
        if len(attempts) % 2:
            return {'facts_dropped': [], 'facts_added': [], 'parse_error': 'invalid'}
        return {'facts_dropped': [], 'facts_added': [], 'facts_preserved': ['112']}
    monkeypatch.setattr(generator, '_gemini_verify', verify)
    assert generator.main() == 0
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert {r['perturbation_type'] for r in rows} == set(generator.PERTURBATION_INSTRUCTIONS)
    assert all(r['attempt'] == 1 and r['verifier_pass'] for r in rows)
    assert all(r['perturbed_response'].startswith(base['base_response_triage_block']) for r in rows)
    assert all(r['benchmark_fingerprint'] == base['benchmark_fingerprint'] for r in rows)


def test_generation_outage_is_nonzero(generation_paths, monkeypatch):
    monkeypatch.setattr(generator, '_generate', lambda *_: '')
    assert generator.main() == 1


def test_changed_medical_meaning_stays_failed(generation_paths, monkeypatch):
    _, output = generation_paths
    monkeypatch.setattr(generator, '_generate', lambda *_: 'wait until tomorrow')
    monkeypatch.setattr(generator, '_gemini_verify', lambda *_: {'facts_dropped': ['112 emergency help'], 'facts_added': ['delay'], 'facts_preserved': []})
    generator.main()
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert rows and all(not row['verifier_pass'] for row in rows)
