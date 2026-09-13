"""Integration: end-to-end FindingsSchema round-trip + system_prompt ↔
schema-first contract consistency.

This is the round-2 follow-up gate (per team-lead) that proves:

  1. A complete `findings.json`-shaped payload — populated with all the
     downstream eval-core outputs (judges, bootstrap CIs, Beta-Binomial
     credible intervals, Krippendorff α, equity-axis strata) — round-trips
     through `data.schemas.FindingsSchema` losslessly.

  2. The schema-first JSON contract `{triage_label, referral_action,
     red_flags_detected, triage_reason}` declared in `data/system_prompt_health.yaml`
     matches the enum membership + field set of `data.schemas.TriageOutput`
     and the corresponding fields on `data.schemas.FindingsItem`. Under
     the schema-first triage contract, parse failures count as wrong, so this consistency
     check is the precondition for downstream parse-failure scoring being
     well-defined.

Slower than the <60s smoke budget — runs after data-spec + eval-core
ship. Invoke with:

    uv run pytest tests/integration/ -v
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration
# Shared imports — gracefully skip the whole module if data-spec hasn't
# landed yet rather than spamming the integration log with red.
def _import_schemas():
    try:
        return importlib.import_module("data.schemas")
    except ModuleNotFoundError as e:
        pytest.fail(f"data.schemas not importable yet: {e}")


@pytest.fixture(scope="module")
def schemas():
    return _import_schemas()


@pytest.fixture(scope="module")
def system_prompt_doc(repo_root: Path) -> dict:
    p = repo_root / "data" / "system_prompt_health.yaml"
    if not p.exists():
        pytest.fail(f"data-spec hasn't shipped {p.relative_to(repo_root)} yet")
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)
def _datasheet_payload(name: str, description: str) -> dict:
    """Datasheet stub matching the data-spec May-10 reconciliation:
    `description`, `intended_use` (alias `purpose`), and `limitations`
    are required; everything else is optional package metadata."""
    return {
        "description": description,
        "purpose": f"Integration-test artefact for {name}.",
        "limitations": "Stubbed numbers; not a real eval result.",
        "version": 1,
        "name": name,
        "license": "Apache-2.0",
        "created_at": "2026-05-10T00:00:00Z",
        "maintainer": "test-maintainer",
    }


def _full_findings_payload() -> dict:
    """A maximally-populated FindingsSchema — exercises every optional
    field on FindingsItem so the round-trip catches enum drift, field
    rename, or alias regression."""
    return {
        "schema_version": 1,
        "plan_version": "current",
        "items": [
            {
                "model_id": "sarvam-105b-conversations",
                "prompt_id": "health-001",
                "triage_label_predicted": "RED",
                "referral_action_predicted": "refer_emergency",
                "triage_parse_succeeded": True,
                "response_text": "गर्भावस्था में रक्तस्राव — तुरंत 108 पर कॉल करें।",
                "latency_ms": 1234.5,
                "judges": [
                    # 12-principle constitutional rubric × judge jury;
                    # we only need a couple of cells to prove the round-trip.
                    {
                        "judge_model_id": "claude-sonnet-4-6",
                        "principle_id": 1,
                        "score": 4.5,
                        "rationale": "Cited WHO health guidance; correct dose for IFA.",
                        "self_judging_dropped": False,
                    },
                    {
                        "judge_model_id": "claude-sonnet-4-6",
                        "principle_id": 11,
                        "score": 5.0,
                        "rationale": "schema-first triage parsed cleanly.",
                        "self_judging_dropped": False,
                    },
                    {
                        # HEALTH-PARIKSHA self-judging avoidance: when the
                        # Sarvam-105b panel response is being scored, the
                        # Sarvam judge is dropped. data-spec's JudgeScore
                        # constrains `score` to the 1-5 Likert range even
                        # for dropped cells — eval-core uses the
                        # `self_judging_dropped` flag (not a sentinel score)
                        # to mark the cell so reliability matrices can
                        # downconvert to NaN at aggregation time.
                        "judge_model_id": "sarvam-105b",
                        "principle_id": 11,
                        "score": 1.0,
                        "rationale": "DROPPED — self-judging avoidance (the judge-panel contract).",
                        "self_judging_dropped": True,
                    },
                ],
                "bootstrap_ci": [
                    {
                        "metric": "constitutional_score_mean",
                        "point_estimate": 4.20,
                        "ci_low_95": 3.92,
                        "ci_high_95": 4.48,
                        "n_resamples": 10_000,
                        "paired": False,
                    }
                ],
                "beta_binomial_ci": [
                    {
                        "metric": "schema_first_triage_accuracy",
                        "successes": 27,
                        "trials": 30,
                        "cred_low_95": 0.78,
                        "cred_high_95": 0.97,
                        "prior_alpha": 1.0,
                        "prior_beta": 1.0,
                    }
                ],
                "krippendorff_alpha": 0.82,
                "equity_strata": [
                    {
                        "axis": "language_script",
                        "stratum": "devanagari",
                        "n": 30,
                        "point_estimate": 0.83,
                        "disparity_ratio_vs_majority": 1.00,
                    },
                    {
                        "axis": "language_script",
                        "stratum": "roman",
                        "n": 30,
                        "point_estimate": 0.71,
                        "disparity_ratio_vs_majority": 0.86,
                    },
                ],
            }
        ],
        "datasheet": _datasheet_payload(
            "findings_integration_stub",
            "Fully-populated FindingsSchema fixture for integration round-trip.",
        ),
    }
# Test 1 — full FindingsSchema round-trip
def test_full_findings_payload_round_trips(schemas):
    """A complete findings payload survives: dict → FindingsSchema → JSON
    → dict → FindingsSchema. Any drift in field names, enums, or aliases
    will surface here as a Pydantic ValidationError."""
    payload = _full_findings_payload()
    obj = schemas.FindingsSchema(**payload)

    # Lossless JSON round-trip — Pydantic v2 `model_dump_json` emits the
    # canonical wire format the report layer will pick up.
    serialized = obj.model_dump_json()
    assert serialized
    redo = schemas.FindingsSchema.model_validate(json.loads(serialized))

    # Spot-check a few fields survived the round trip.
    item = redo.items[0]
    assert str(item.triage_label_predicted.value) == "RED"
    assert str(item.referral_action_predicted.value) == "refer_emergency"
    assert item.triage_parse_succeeded is True
    assert len(item.judges) == 3
    # HEALTH-PARIKSHA self-judging avoidance flag survives serialization.
    assert any(j.self_judging_dropped for j in item.judges)
    assert item.bootstrap_ci[0].n_resamples == 10_000
    assert 0.0 <= item.beta_binomial_ci[0].cred_low_95 <= 1.0
    assert -1.0 <= float(item.krippendorff_alpha) <= 1.0
    assert {s.stratum for s in item.equity_strata} == {"devanagari", "roman"}
# Test 2 — system_prompt_health.yaml ↔ TriageOutput / FindingsItem consistency
def test_system_prompt_output_schema_matches_triage_contract(schemas, system_prompt_doc):
    """The `output_schema:` block in `data/system_prompt_health.yaml` is the
    contract every panel model is told to emit. Its enum members and
    field names MUST line up with `data.schemas.TriageOutput` and with
    the `triage_label_predicted` / `referral_action_predicted` fields on
    `FindingsItem` — otherwise schema-first scoring (the schema-first triage contract)
    is silently broken.

    This test enforces the consistency in both directions.
    """
    out = system_prompt_doc.get("output_schema")
    assert isinstance(out, dict), "system_prompt_health.yaml must declare an `output_schema:` mapping"
    declared_fields = set(out.keys())
    expected_fields = {
        "triage_label",
        "referral_action",
        "red_flags_detected",
        "triage_reason",
    }
    assert declared_fields == expected_fields, (
        f"system_prompt output_schema field set drift — declared {declared_fields}, "
        f"expected {expected_fields} (the triage and rubric contract + the shared health system prompt)."
    )
    declared_triage = set(out["triage_label"])
    schema_triage = {m.value for m in schemas.TriageLabel}
    assert declared_triage == schema_triage, (
        f"triage_label enum drift between system_prompt_health.yaml ({declared_triage}) "
        f"and data.schemas.TriageLabel ({schema_triage})."
    )
    declared_referral = set(out["referral_action"])
    schema_referral = {m.value for m in schemas.ReferralAction}
    assert declared_referral == schema_referral, (
        f"referral_action enum drift between system_prompt_health.yaml "
        f"({declared_referral}) and data.schemas.ReferralAction ({schema_referral})."
    )
    rfd = out["red_flags_detected"]
    # Accepts either a literal type-hint string ("list[str]") or an
    # explicit list-of-string example — both encode the same contract.
    assert rfd in ("list[str]", "List[str]") or (
        isinstance(rfd, list) and all(isinstance(x, str) for x in rfd)
    ), f"red_flags_detected must be a list-of-string declaration; got {rfd!r}"
    assert out["triage_reason"] == "str", (
        f"triage_reason must be declared as a short string; got {out['triage_reason']!r}"
    )
    findings_fields = set(schemas.FindingsItem.model_fields.keys())
    # The two prediction fields are how the harness writes the panel
    # model's emitted triage block back into findings.json.
    assert "triage_label_predicted" in findings_fields, "FindingsItem missing triage_label_predicted"
    assert "referral_action_predicted" in findings_fields, "FindingsItem missing referral_action_predicted"
    assert "triage_parse_succeeded" in findings_fields, (
        "FindingsItem must record whether the schema-first parse succeeded "
        "(the schema-first triage contract — parse failures count as wrong)."
    )
    triage_output_fields = set(schemas.TriageOutput.model_fields.keys())
    assert expected_fields.issubset(triage_output_fields), (
        f"TriageOutput model_fields ({triage_output_fields}) must contain "
        f"{expected_fields} so panel-model emissions can be parsed directly."
    )
# Test 3 — strict-mode (`extra=forbid`) catches drift early
def test_findings_schema_rejects_extra_fields(schemas):
    """data-spec's `_Base` uses `extra='forbid'`. If a downstream layer
    (eval-core, eval-integ) starts emitting an undocumented field into
    findings.json, validation must reject it loudly — not silently drop
    it. This test pins that behaviour so the contract stays tight."""
    payload = _full_findings_payload()
    payload["items"][0]["unsanctioned_field"] = "should_explode"
    with pytest.raises(Exception):  # noqa: PT011 — Pydantic raises ValidationError
        schemas.FindingsSchema(**payload)
