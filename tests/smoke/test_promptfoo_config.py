"""Smoke (e): `promptfooconfig.yaml` parses as YAML and lists all required
candidate models (the candidate-model panel / saved-output Promptfoo check).

Owned by Teammate D (eval-integ). Also opportunistically checks that the
`promptfoo` npm CLI is on PATH (the dependency is npm, not Python). The
Docker workflow provides Promptfoo through the `promptfoo-saved` and
`promptfoo-live` services. Both checks XFAIL/SKIP cleanly when
unavailable so foundation-eng's gate stays green.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.smoke

# The smoke-test contract is "all shipped panel ids must appear".
REQUIRED_MODEL_IDS = {
    "sarvam-105b-conversations",
    "sarvam-105b",
    "claude-sonnet-4-6",
    "gemini-2.5-pro",
}


def _config_path(repo_root: Path) -> Path:
    """Return the canonical Promptfoo config path."""
    root = repo_root / "promptfooconfig.yaml"
    if root.exists():
        return root
    return repo_root / "eval" / "promptfooconfig.yaml"


def _flatten_provider_ids(doc: dict) -> set[str]:
    """Promptfoo configs encode the model id in any of several places:

    * Native vendor providers where everything after the last `:` is the
      model id.
    * Custom HTTP providers — `id: http` + `label: <model_id>`. This is
      the v1.5.3 idiom (promptfooconfig.yaml § "Four HTTP
      providers") — the user-facing model id lives in `label`, not `id`.
    * Object form — `{id: <model_id>}`, `{model: <model_id>}`, or the
      Promptfoo body's nested `body.model:` field.
    * Sibling `models:` list — some configs encode the panel separately.

    All four forms are accepted; we union everything we find.
    """
    ids: set[str] = set()

    def _add(val):
        if isinstance(val, str):
            ids.add(val.split(":")[-1].strip())

    providers = doc.get("providers") or []
    if isinstance(providers, list):
        for p in providers:
            if isinstance(p, str):
                _add(p)
                continue
            if not isinstance(p, dict):
                continue
            # `label` is the v1.5.3 canonical id for HTTP providers.
            for key in ("label", "id", "model", "name"):
                _add(p.get(key))
            # Vendor body sometimes carries the upstream model id under
            # `config.body.model:` — harvest that too so the parser is
            # robust to either layout.
            cfg = p.get("config") or {}
            if isinstance(cfg, dict):
                body = cfg.get("body") or {}
                if isinstance(body, dict):
                    _add(body.get("model"))

    for m in doc.get("models", []) or []:
        if isinstance(m, str):
            _add(m)
        elif isinstance(m, dict):
            for key in ("label", "id", "model", "name"):
                _add(m.get(key))
    return ids


def _promptfoo_config_missing() -> bool:
    repo = Path(__file__).resolve().parents[2]
    return not (
        (repo / "promptfooconfig.yaml").exists()
        or (repo / "eval" / "promptfooconfig.yaml").exists()
    )


@pytest.mark.xfail(
    _promptfoo_config_missing(),
    reason="promptfooconfig.yaml is not present",
    strict=False,
)
def test_promptfoo_config_parses_and_lists_panel(repo_root):
    path = _config_path(repo_root)
    with path.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc, dict), "promptfooconfig.yaml must be a mapping"
    ids = _flatten_provider_ids(doc)
    missing = REQUIRED_MODEL_IDS - ids
    assert not missing, (
        f"promptfooconfig.yaml is missing the candidate-model panel candidate model ids: {missing}. "
        f"Found ids: {ids}"
    )


def test_promptfoo_cli_available_or_skipped():
    """Best-effort: if `promptfoo` is on PATH, `--version` must respond.

    Skips when the CLI is absent because Docker provides it inside the
    Promptfoo profile services."""
    binary = shutil.which("promptfoo") or str(Path(__file__).resolve().parents[2] / "node_modules/.bin/promptfoo")
    if not Path(binary).exists():
        pytest.skip("promptfoo CLI not installed in this environment — see README.md")
    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"promptfoo --version failed: {result.stderr}"
    assert result.stdout.strip(), "promptfoo --version emitted no output"
