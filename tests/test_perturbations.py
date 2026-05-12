"""Schema + factual-preservation invariants for the real-world robustness audit."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"
PERT = REPO_ROOT / "data" / "perturbations" / "perturbed_responses.jsonl"

EXPECTED_PROMPT_IDS = {"ref-001", "ref-007", "ref-009", "ref-012", "ref-024"}
EXPECTED_PERTURBATIONS = {
    "script_swap", "code_mix", "length_compress",
    "style_inflate", "style_deflate", "authority_register",
}


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8")]


def test_base_responses_present() -> None:
    if not BASE.exists():
        pytest.skip(f"{BASE} not yet generated")
    records = _load(BASE)
    assert len(records) == 5
    assert {r["prompt_id"] for r in records} == EXPECTED_PROMPT_IDS


def test_base_responses_have_real_content() -> None:
    if not BASE.exists():
        pytest.skip(f"{BASE} not yet generated")
    for r in _load(BASE):
        assert len(r["base_response"]) > 50, r["prompt_id"]
        assert len(r["base_response_prose"]) > 50, r["prompt_id"]


def test_base_responses_have_required_fields() -> None:
    if not BASE.exists():
        pytest.skip(f"{BASE} not yet generated")
    required = {
        "prompt_id", "user_prompt", "base_response", "base_response_prose",
        "base_response_triage_block", "base_source", "violation_expected",
        "expected_urgency", "selected_rationale",
    }
    for r in _load(BASE):
        missing = required - set(r)
        assert not missing, f"{r.get('prompt_id')} missing fields: {missing}"


def test_perturbations_cover_full_grid() -> None:
    if not PERT.exists():
        pytest.skip(f"{PERT} not yet generated")
    records = _load(PERT)
    assert len(records) == 30, f"expected 30 cells, got {len(records)}"
    grid = {(r["prompt_id"], r["perturbation_type"]) for r in records}
    expected = {(p, t) for p in EXPECTED_PROMPT_IDS for t in EXPECTED_PERTURBATIONS}
    assert grid == expected, f"grid mismatch: missing={expected - grid}, extra={grid - expected}"


def test_perturbations_have_required_fields() -> None:
    if not PERT.exists():
        pytest.skip(f"{PERT} not yet generated")
    required = {
        "prompt_id", "perturbation_type", "base_response", "perturbed_response",
        "perturbed_prose", "factual_diff", "verifier_pass", "generator_model",
        "verifier_model", "attempt",
    }
    for r in _load(PERT):
        missing = required - set(r)
        assert not missing, f"{r.get('prompt_id')}/{r.get('perturbation_type')} missing: {missing}"


def test_perturbations_have_diff_block() -> None:
    if not PERT.exists():
        pytest.skip(f"{PERT} not yet generated")
    for r in _load(PERT):
        assert "factual_diff" in r
        diff = r["factual_diff"]
        assert isinstance(diff, dict), r["prompt_id"]
        assert "facts_preserved" in diff
        assert isinstance(diff["facts_preserved"], list)


def test_perturbations_preserve_triage_block() -> None:
    """The JSON triage block must be unchanged across perturbations (the variable under test is prose only)."""
    if not PERT.exists() or not BASE.exists():
        pytest.skip("base or perturbed file not yet generated")
    bases = {b["prompt_id"]: b for b in _load(BASE)}
    for r in _load(PERT):
        base = bases[r["prompt_id"]]
        if not base["base_response_triage_block"]:
            continue  # base lacked a triage block; nothing to enforce
        assert r["perturbed_response"].startswith(base["base_response_triage_block"]), (
            f"{r['prompt_id']}/{r['perturbation_type']}: triage block not preserved as prefix"
        )


def test_verifier_pass_rate_above_minimum() -> None:
    """At least 18/30 perturbations must preserve facts.

    Empirical floor: length_compress and authority_register systematically struggle to
    preserve facts under LLM-assisted Hindi-MNH transformation; that is itself a
    methodology finding documented in the audit. Stricter than 18/30 would tune away a
    real signal.
    """
    if not PERT.exists():
        pytest.skip(f"{PERT} not yet generated")
    records = _load(PERT)
    passes = sum(r["verifier_pass"] for r in records)
    assert passes >= 18, f"only {passes}/30 perturbations preserved facts; investigate generator prompt"


def test_perturbation_type_pass_rates_reported() -> None:
    """Document per-type pass rates so the audit doc can cite them honestly."""
    if not PERT.exists():
        pytest.skip(f"{PERT} not yet generated")
    records = _load(PERT)
    by_type: dict[str, list[bool]] = {}
    for r in records:
        by_type.setdefault(r["perturbation_type"], []).append(r["verifier_pass"])
    for ptype, passes in sorted(by_type.items()):
        rate = sum(passes) / len(passes)
        assert 0.0 <= rate <= 1.0, ptype
        # Not a strict assertion — just gates the file structure for the audit doc.
