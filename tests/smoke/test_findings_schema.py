"""Required FindingsSchema accepts a minimal, explicitly synthetic test artifact."""
from __future__ import annotations

import importlib

import pytest

pytestmark = pytest.mark.smoke


def _get_attr(name: str):
    try:
        mod = importlib.import_module("data.schemas")
    except ModuleNotFoundError:
        return None
    return getattr(mod, name, None)


def _build_minimal_findings():
    """Build a findings.json stub against the full data-spec contract:
    requires `items` (list of FindingsItem) + `datasheet` (Datasheet).

    Datasheet fields per data-spec's May-10 reconciliation note (Gebru
    CACM 2021 §3): `description`, `intended_use` (alias `purpose`), and
    `limitations` are required; `name`/`maintainer`/`license`/`created_at`
    are optional package-metadata fields.
    """
    return {
        "schema_version": 1,
        "plan_version": "v1.5.3",
        "items": [
            {
                "model_id": "sarvam-105b-conversations",
                "prompt_id": "health-001",
                "triage_label_predicted": "RED",
                "referral_action_predicted": "refer_emergency",
                "triage_parse_succeeded": True,
                "response_text": "नमस्ते — स्मोक टेस्ट उत्तर।",
                "latency_ms": 1234.0,
                "judges": [],
                "bootstrap_ci": [],
                "beta_binomial_ci": [],
                "krippendorff_alpha": None,
                "equity_strata": [],
            }
        ],
        "datasheet": {
            "description": "Synthetic smoke-test fixture for FindingsSchema round-trip.",
            "purpose": "Validate FindingsSchema(**payload) succeeds offline in <60s.",
            "limitations": "Stub only; no real model evaluation behind these numbers.",
            "version": 1,
            "name": "findings_smoke_stub",
            "license": "Apache-2.0",
            "created_at": "2026-05-10T00:00:00Z",
            "maintainer": "test-maintainer",
        },
    }


def test_findings_stub_validates():
    FindingsSchema = _get_attr("FindingsSchema")
    Datasheet = _get_attr("Datasheet")
    if FindingsSchema is None or Datasheet is None:
        pytest.fail("FindingsSchema or Datasheet must be exposed")

    payload = _build_minimal_findings()

    obj = FindingsSchema(**payload)

    dumped = obj.model_dump()
    assert dumped["plan_version"] == "v1.5.3"
    assert isinstance(dumped["items"], list) and dumped["items"]
