"""Promptfoo test generator for the HealthEval reference set."""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.reference_risk import reference_risk_tier

REFERENCE_SET_PATH = REPO_ROOT / "data" / "reference_set.yaml"


def generate_reference_set_tests(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or {}
    path = Path(cfg.get("referenceSetPath") or REFERENCE_SET_PATH)
    if not path.is_absolute():
        path = REPO_ROOT / path

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = list(raw.get("items") or [])
    model_ids = list(cfg.get("modelIds") or [])

    limit_raw = os.getenv("HEALTHEVAL_PROMPTFOO_LIMIT") or cfg.get("limit")
    if limit_raw:
        items = items[: int(limit_raw)]

    tests: list[dict[str, Any]] = []
    for item in items:
        prompt_id = str(item.get("id"))
        model_var: str | list[str] | None = model_ids if model_ids else None
        vars_payload = {
            "prompt_id": prompt_id,
            "prompt": item.get("prompt") or item.get("hindi_text") or "",
            "expected_safety_action": item.get("expected_safety_action"),
            "reference_risk_tier": reference_risk_tier(item),
            "source_paragraph": item.get("source_paragraph") or "",
            "source_url": item.get("source_url") or "",
            # Promptfoo treats array-valued vars as a cartesian expansion.
            # Keep checklist metadata as JSON strings so each reference item
            # remains one test case unless modelIds intentionally expands it.
            "factual_checklist": json.dumps(
                item.get("factual_checklist") or [],
                ensure_ascii=False,
            ),
            "refusal_expected": bool(item.get("refusal_expected", False)),
            "required_safety_signs": json.dumps(
                item.get("red_flag_match_required") or [],
                ensure_ascii=False,
            ),
        }
        if model_var:
            vars_payload["model_id"] = model_var
        tests.append(
            {
                "vars": vars_payload,
                "metadata": {
                    "prompt_id": prompt_id,
                    "category": item.get("category"),
                },
            }
        )
    return tests
