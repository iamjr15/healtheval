"""Required benchmark YAML validates against the current Pydantic schemas."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.smoke


def _get_attr(name: str):
    try:
        mod = importlib.import_module("data.schemas")
    except ModuleNotFoundError:
        return None
    return getattr(mod, name, None)


def _yaml_exists(repo_root: Path, name: str) -> bool:
    return (repo_root / "data" / name).exists()


def _load_yaml(repo_root: Path, name: str) -> dict:
    with (repo_root / "data" / name).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _prompt_schema_blocked(repo_root: Path) -> bool:
    return _get_attr("Prompts") is None or not _yaml_exists(repo_root, "prompts.yaml")


def _model_panel_blocked(repo_root: Path) -> bool:
    return _get_attr("ModelPanel") is None or not _yaml_exists(repo_root, "model_panel.yaml")


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_prompts_yaml_validates_against_schema(repo_root):
    Prompts = _get_attr("Prompts")
    assert Prompts is not None
    doc = _load_yaml(repo_root, "prompts.yaml")
    obj = Prompts(**doc)
    # the prompt-set contract: ≥30 health-written prompts (`health-NNN`) — schema enforces
    # this, but we re-assert the count here so the smoke gate diagnostic
    # is one line, not a buried Pydantic error.
    hand = [p for p in obj.prompts if p.id.startswith("health-")]
    assert len(hand) >= 30, f"expected ≥30 health-written prompts, got {len(hand)}"


def test_model_panel_yaml_validates_against_schema(repo_root):
    ModelPanel = _get_attr("ModelPanel")
    assert ModelPanel is not None
    doc = _load_yaml(repo_root, "model_panel.yaml")
    obj = ModelPanel(**doc)
    n = len(obj.panel)
    assert n == 4, f"expected 4 current candidates; got {n}"
    candidate_ids = {
        m.model_id
        for m in obj.panel
        if getattr(m.dispatch_type, "value", str(m.dispatch_type)) == "API"
    }
    required_current = {
        "sarvam-105b-conversations", "sarvam-105b", "claude-sonnet-4-6", "gemini-2.5-pro",
    }
    # Accept hyphen/period drift in the Claude/Gemini ids — the canonical
    # token set is what matters for the smoke gate.
    normalized = {cid.replace(".", "-") for cid in candidate_ids}
    required_norm = {e.replace(".", "-") for e in required_current}
    missing = required_norm - normalized
    assert not missing, (
        f"model_panel.yaml missing required candidate ids: {missing} "
        f"(got {candidate_ids})"
    )
    # Reject any ids outside required ∪ optional — drift like a brand-new
    # vendor sneaking in should fail the gate.
    extras = normalized - required_norm
    assert not extras, (
        f"model_panel.yaml has unexpected candidate ids: {extras} "
        "(allowed: shipped 4-model panel)"
    )
    n_judges = len(obj.judge_panel)
    assert n_judges == 3, f"need 3 judges (the judge-panel contract); got {n_judges}"
