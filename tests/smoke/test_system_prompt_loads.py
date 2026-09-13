"""The required shared Hindi health prompt exposes the expected response contract."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.smoke

REQUIRED_KEYS = {"system_prompt", "output_schema", "language", "sources"}


def _system_prompt_path(repo_root: Path) -> Path:
    return repo_root / "data" / "system_prompt_health.yaml"


def test_system_prompt_yaml_parses_and_has_required_keys(repo_root):
    path = _system_prompt_path(repo_root)
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), "system_prompt_health.yaml must be a mapping at top level"
    missing = REQUIRED_KEYS - set(doc.keys())
    assert not missing, f"system_prompt_health.yaml missing required keys: {missing}"
    # Accept BCP-47 Hindi tags (`hi`, `hi-IN`, `hi-en`) plus the
    # human-readable alias `hindi` data-spec might pick before the
    # SystemPromptConfig schema locks `Literal["hi-IN"]`.
    lang = str(doc["language"]).lower()
    assert lang.startswith("hi") or lang == "hindi", (
        f"health prompt must be Hindi-first (the shared health system prompt); got language={doc['language']!r}"
    )
    sources = doc["sources"]
    assert isinstance(sources, list) and sources, "sources must be a non-empty list"
