"""Promptfoo provider over the saved MaaSwasth reference-set responses.

Promptfoo expects provider functions to accept ``(prompt, options, context)``
and return ``{"output": ...}``.  This provider avoids re-calling the panel
model: it returns the already-saved response for ``context["vars"]["prompt_id"]``.
The DeepEval assertion in ``promptfoo_deepeval_assert.py`` then grades that
output with the same prompt metadata.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_PATH = REPO_ROOT / "results" / "methodology_panel_refset_eval.json"

_CACHE: dict[Path, dict[str, Mapping[str, Any]]] = {}


def _load_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    if path not in _CACHE:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(artifact.get("models"), dict):
            rows_by_key: dict[str, Mapping[str, Any]] = {}
            for model_id, model_artifact in artifact["models"].items():
                for row in model_artifact.get("rows") or []:
                    prompt_id = row.get("prompt_id")
                    if prompt_id:
                        rows_by_key[f"{model_id}:{prompt_id}"] = row
            _CACHE[path] = rows_by_key
            return _CACHE[path]
        rows = artifact.get("rows") or []
        _CACHE[path] = {
            str(row.get("prompt_id")): row
            for row in rows
            if row.get("prompt_id")
        }
    return _CACHE[path]


def call_api(prompt: str, options: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    config = options.get("config") or {}
    path = Path(config.get("resultsPath") or DEFAULT_RESULTS_PATH)
    if not path.is_absolute():
        path = REPO_ROOT / path

    vars_ = context.get("vars") or {}
    prompt_id = str(vars_.get("prompt_id") or "")
    model_id = str(vars_.get("model_id") or config.get("modelId") or "")
    rows_by_id = _load_rows(path)
    row = rows_by_id.get(f"{model_id}:{prompt_id}") if model_id else None
    if row is None:
        row = rows_by_id.get(prompt_id)
    if row is None:
        return {
            "output": "",
            "error": f"prompt_id {prompt_id!r} model_id {model_id!r} not found in {path}",
        }

    return {
        "output": str(row.get("response") or ""),
        "metadata": {
            "prompt_id": prompt_id,
            "model_id": model_id or row.get("model_id"),
            "parse_succeeded": bool(row.get("parse_succeeded")),
            "decision": row.get("decision") or {},
            "source_results_path": str(path.relative_to(REPO_ROOT)),
        },
    }
