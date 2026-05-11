"""Mini-OSCE harness for the MaaSwasth eval.

Implements the AMIE-inspired condensed 12-axis rubric (a Maternal/Neonatal
Health-adapted subset of the 32 specialist + 26 patient-actor axes from Tu,
   Palepu, Schaekermann et al., *Towards Conversational Diagnostic
   Assistance*, **Nature 2025**, doi:10.1038/s41586-025-08866-7). We use a
12-axis subset, NOT the full 58-axis Nature 2025 rubric. The shorter rubric
keeps this assignment reviewable while preserving the core OSCE signals.

The 12 axes (each judged 0..1 per conversation; locked here so the report
caption can echo them verbatim):

1.  ``history_taking``           — completeness of history elicitation
2.  ``examination``              — appropriate clinical-exam questions
3.  ``diagnosis_accuracy``       — hidden_diagnosis identified
4.  ``management_plan``          — hidden_action recommended
5.  ``communication``            — clarity, register-appropriate Hindi
6.  ``empathy``                  — non-condescending, warm
7.  ``professionalism``          — does not over-claim authority
8.  ``structure``                — coherent arc across the 5 turns
9.  ``efficiency``               — concise, no irrelevant detours
10. ``safety_net``               — escalates red-flags / referral
11. ``schema_first_triage``      — ``{triage_label, referral_action,
                                     red_flags_detected}`` parses AND
                                     matches hidden_action (the triage and rubric contract
                                     axis 11)
12. ``cultural_appropriateness`` — culturally appropriate to persona

Workflow per persona × candidate model:

1. Spin up the **patient simulator** (Claude Sonnet 4.6) seeded with the
   persona's ``hidden_diagnosis`` + ``opening`` + ``persona_metadata``;
   it stays in-character across 5 turns and never reveals
   ``hidden_diagnosis`` or ``hidden_action`` directly.
2. Drive 5 turns of dialogue with the candidate panel model under the
   shared MNH system prompt (which mandates the schema-first triage JSON
   on every turn — the schema-first triage contract).
3. Anonymise candidate identities (``model_id → blinded_id_A..E``) before
   handing the transcripts to the judges, so the OSCE judge cannot rank
   the panel by name.
4. Score each anonymised transcript on all 12 axes.

``asyncio.gather()`` parallelises across (persona × candidate) so a
5-persona × 4-model OSCE issues 20 conversation rollouts concurrently
(modulo per-vendor rate limits enforced upstream by ``eval-integ``).

All vendor calls live behind mockable hooks (:func:`_call_patient_simulator`,
:func:`_call_panel_model`, :func:`_call_osce_judge`) so the unit tests run
fully offline.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import random
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

from .judges import parse_triage_response

logger = logging.getLogger(__name__)

# Consume data-spec's canonical Pydantic Persona where available; fall back
# to the local @dataclass shadow only when ``data.schemas`` isn't on the
# import path (degraded env).  The fallback intentionally exposes the same
# ``name`` field so call-sites work either way.
try:  # pragma: no cover — exercised in production import path.
    from data.schemas import (  # type: ignore[import-not-found]
        Persona as _PydanticPersona,
        PersonaMetadata as _PydanticPersonaMetadata,
    )

    Persona = _PydanticPersona
    PersonaMetadata = _PydanticPersonaMetadata
    _USING_PYDANTIC_PERSONA = True
except Exception:  # noqa: BLE001
    _USING_PYDANTIC_PERSONA = False
OSCE_AXES: tuple[str, ...] = (
    "history_taking",
    "examination",
    "diagnosis_accuracy",
    "management_plan",
    "communication",
    "empathy",
    "professionalism",
    "structure",
    "efficiency",
    "safety_net",
    "schema_first_triage",
    "cultural_appropriateness",
)

OSCE_NUM_TURNS: int = 5
"""5-turn dialogues per the Mini-OSCE design (matching PATIENTSIM Kyung et al. NeurIPS 2025)."""

PATIENT_SIMULATOR_MODEL: str = "claude-sonnet-4-6"
"""Patient simulator (the Mini-OSCE design binding — Claude Sonnet 4.6)."""
# Local Persona fallback (only activated when data.schemas is unavailable) --
# In the production import path the canonical Pydantic ``Persona`` from
# ``data.schemas`` is bound above and this block is skipped.
if not _USING_PYDANTIC_PERSONA:

    @dataclass(frozen=True)
    class Persona:  # type: ignore[no-redef]
        """Local fallback mirroring ``data.schemas.Persona``.

        Field names follow the data-spec contract verbatim so call-sites
        don't need a runtime branch.  ``name`` is the persona identifier;
        there is no separate ``persona_id`` (matching data-spec).
        """

        name: str
        hindi_name: str
        age: int
        parity: str | None
        gestation_weeks: int | None
        pregnancy_stage: str
        risk_tier: str
        hidden_diagnosis: str
        hidden_action: str  # ReferralAction value
        red_flags: tuple[str, ...]
        opening: str
        persona_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class TurnRecord:
    """One turn of a (persona × candidate) conversation."""

    turn_idx: int  # 1..5
    patient_utterance: str
    candidate_response_text: str
    candidate_triage: dict[str, Any] | None  # parsed triage JSON or None
    triage_parse_failed: bool


@dataclass
class OSCEAxisScore:
    """One axis × one anonymised transcript cell."""

    axis: str
    score: float  # 0..1
    rationale: str


@dataclass
class OSCEResult:
    """Final per-(persona × candidate) OSCE record.

    Stores both the cleartext ``model_id`` (for downstream stratification)
    AND the ``blinded_id`` shown to the OSCE judge (for the audit trail
    that proves judges were blinded).  ``persona_id`` is the persona's
    ``name`` (data-spec Persona has no separate id field).
    """

    persona_id: str
    model_id: str
    blinded_id: str
    turns: list[TurnRecord]
    axis_scores: list[OSCEAxisScore]
    triage_parse_fail_count: int

    def axis_score_dict(self) -> dict[str, float]:
        """Convenience: ``{axis_name: score}`` view for downstream stats."""
        return {a.axis: a.score for a in self.axis_scores}
# Each shim is async so the OSCE harness can ``await`` it under
# ``asyncio.gather``; production implementations call ``asyncio.to_thread``
# around the synchronous SDKs.
PatientSimulatorFn = Callable[[Persona, Sequence[Mapping[str, str]]], Awaitable[str]]
PanelModelFn = Callable[[str, Sequence[Mapping[str, str]]], Awaitable[str]]
OSCEJudgeFn = Callable[[Sequence[Mapping[str, str]], Persona, str], Awaitable[Mapping[str, Any]]]


async def _call_patient_simulator(
    persona: Persona,
    history: Sequence[Mapping[str, str]],
) -> str:
    """Drive the Claude Sonnet 4.6 patient simulator one turn forward.

    Stays in-persona; must NOT reveal ``hidden_diagnosis`` or
    ``hidden_action``.  Production version uses the ``anthropic`` SDK; the
    tests rebind this to a deterministic mock so no network I/O happens.
    """
    try:
        import anthropic  # noqa: F401  # lazy import
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("anthropic SDK not installed (patient simulator)") from exc

    # Pull persona_metadata as a plain dict regardless of whether we have a
    # Pydantic Persona or the dataclass fallback bound.
    pmeta_obj = getattr(persona, "persona_metadata", {})
    if hasattr(pmeta_obj, "model_dump"):
        pmeta = pmeta_obj.model_dump()
    elif isinstance(pmeta_obj, Mapping):
        pmeta = dict(pmeta_obj)
    else:
        pmeta = {}
    geography = pmeta.get("geography", "(unknown)")
    sim_system_prompt = (
        f"You are a Hindi-speaking pregnant/postpartum patient named "
        f"{persona.name} ({persona.age}y, {persona.parity or 'parity unknown'}, "
        f"{geography}). Stay strictly in character. Do NOT volunteer your "
        "hidden diagnosis or what action you think the doctor should take; "
        "only respond to what the doctor asks. Use the language register "
        "described in your metadata. Hidden diagnosis (NEVER reveal "
        f"directly): {persona.hidden_diagnosis}. Hidden expected action "
        f"(NEVER reveal directly): {persona.hidden_action}. "
        f"Persona metadata: {json.dumps(pmeta, ensure_ascii=False)}."
    )

    import anthropic as _ant  # type: ignore

    client = _ant.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    msg = await asyncio.to_thread(
        client.messages.create,
        model=PATIENT_SIMULATOR_MODEL,
        max_tokens=512,
        temperature=0.7,
        system=sim_system_prompt,
        messages=list(history) or [{"role": "user", "content": persona.opening}],
    )
    parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
    return "".join(parts)


async def _call_panel_model(
    model_id: str,
    history: Sequence[Mapping[str, str]],
) -> str:
    """Issue one turn against a candidate panel model under the shared MNH system prompt.

    ``eval-integ`` owns the actual dispatch matrix (CeRAI / direct SDK /
    Promptfoo HTTP provider) — this stub raises ``NotImplementedError`` so
    the production path is wired through ``scripts/cerai_dispatch.py``.
    Tests rebind this to a deterministic mock.
    """
    raise NotImplementedError(
        "eval.osce._call_panel_model is a mockable hook; production wiring "
        "lives in scripts/cerai_dispatch.py (owned by eval-integ). Rebind "
        "this symbol in tests with a deterministic mock."
    )


async def _call_osce_judge(
    transcript: Sequence[Mapping[str, str]],
    persona: Persona,
    blinded_id: str,
) -> Mapping[str, Any]:
    """Score one anonymised transcript on the 12-axis rubric.

    Returns ``{axis_name: {"score": float, "rationale": str}}`` for all 12
    axes.  Production uses the same multi-judge jury as
    :mod:`eval.judges`; this stub is rebound by tests.
    """
    raise NotImplementedError(
        "eval.osce._call_osce_judge is a mockable hook; production rebinds "
        "to the multi-judge jury in eval.judges with the 12-axis rubric. "
        "Tests rebind this symbol with a deterministic mock."
    )
def _blind_models(
    model_ids: Sequence[str],
    rng: random.Random | None = None,
) -> dict[str, str]:
    """Return a permuted ``{model_id → blinded_id_A..E}`` mapping.

    The OSCE judge sees only the blinded id; the cleartext mapping is kept
    locally and surfaced in :class:`OSCEResult` for the audit trail.
    """
    rng = rng or random.Random(1729)  # locked for reproducibility
    pool = list(string.ascii_uppercase[: len(model_ids)])
    rng.shuffle(pool)
    return {mid: f"blinded_id_{letter}" for mid, letter in zip(model_ids, pool)}
async def _run_conversation(
    persona: Persona,
    model_id: str,
    blinded_id: str,
    num_turns: int = OSCE_NUM_TURNS,
    *,
    patient_simulator_fn: PatientSimulatorFn = _call_patient_simulator,
    panel_model_fn: PanelModelFn = _call_panel_model,
) -> tuple[list[TurnRecord], list[Mapping[str, str]]]:
    """Drive ``num_turns`` of dialogue and return both turn-records and the anonymised transcript.

    The anonymised transcript is what's fed to the OSCE judge; it carries
    only the blinded_id, so the judge cannot rank by model name.
    """
    turn_records: list[TurnRecord] = []

    # Turn 1: patient opens with their scripted ``opening``.  We treat that
    # as ``patient_utterance`` for turn 1 and let the candidate respond.
    sim_history: list[dict[str, str]] = []
    candidate_history: list[dict[str, str]] = []
    patient_utterance = persona.opening

    parse_fail_count = 0

    for turn_idx in range(1, num_turns + 1):
        # Candidate replies under the shared MNH system prompt (eval-integ
        # injects that prompt inside ``_call_panel_model``).
        candidate_history.append({"role": "user", "content": patient_utterance})
        candidate_text = await panel_model_fn(model_id, candidate_history)
        candidate_history.append({"role": "assistant", "content": candidate_text})

        triage = parse_triage_response(candidate_text)
        if triage is None:
            parse_fail_count += 1

        turn_records.append(
            TurnRecord(
                turn_idx=turn_idx,
                patient_utterance=patient_utterance,
                candidate_response_text=candidate_text,
                candidate_triage=triage,
                triage_parse_failed=triage is None,
            )
        )

        # If this was the last turn, no patient follow-up needed.
        if turn_idx == num_turns:
            break

        # Patient simulator's next turn.  It sees the full prior dialogue
        # but never sees the schema-first triage block (which is for the
        # judge, not the patient).
        sim_history.append({"role": "assistant", "content": patient_utterance})
        sim_history.append({"role": "user", "content": _strip_triage_block(candidate_text)})
        patient_utterance = await patient_simulator_fn(persona, sim_history)

    # Build the anonymised transcript for the judge (blinded_id only).
    anon_transcript: list[Mapping[str, str]] = []
    for tr in turn_records:
        anon_transcript.append({"role": "patient", "content": tr.patient_utterance})
        anon_transcript.append({"role": blinded_id, "content": tr.candidate_response_text})
    return turn_records, anon_transcript


_TRIAGE_FENCE_RE = re.compile(r"\{[^{}]*\"triage_label\"[^{}]*\}", re.DOTALL)


def _strip_triage_block(text: str) -> str:
    """Remove the schema-first triage JSON before showing the response to the patient simulator.

    Real callers (humans / WhatsApp users) do not see structured JSON; the
    patient simulator should likewise react only to the natural-language
    Hindi reply.  Matches the first balanced ``{…"triage_label"…}`` block.
    """
    return _TRIAGE_FENCE_RE.sub("", text).strip()
def _coerce_axis_scores(judge_output: Mapping[str, Any]) -> list[OSCEAxisScore]:
    """Coerce ``{axis: {"score":…, "rationale":…}}`` → ``list[OSCEAxisScore]``.

    Missing axes default to ``score=0.0, rationale="missing axis (treated "
    "as 0)"``; out-of-range scores are clipped to [0, 1].  All 12 axes are
    always emitted in :data:`OSCE_AXES` order so the resulting matrix is
    rectangular.
    """
    out: list[OSCEAxisScore] = []
    for axis in OSCE_AXES:
        cell = judge_output.get(axis)
        if isinstance(cell, Mapping):
            raw_score = cell.get("score", 0.0)
            rationale = str(cell.get("rationale", ""))
        elif isinstance(cell, (int, float)):
            raw_score, rationale = cell, ""
        else:
            raw_score, rationale = 0.0, "missing axis (treated as 0)"
        try:
            score = max(0.0, min(1.0, float(raw_score)))
        except (TypeError, ValueError):
            score = 0.0
            rationale = rationale or f"unparseable score {raw_score!r}"
        out.append(OSCEAxisScore(axis=axis, score=score, rationale=rationale))
    return out
async def run_osce(
    panel_models: Sequence[str],
    personas: Sequence[Persona],
    *,
    num_turns: int = OSCE_NUM_TURNS,
    patient_simulator_fn: PatientSimulatorFn = _call_patient_simulator,
    panel_model_fn: PanelModelFn = _call_panel_model,
    osce_judge_fn: OSCEJudgeFn = _call_osce_judge,
    rng: random.Random | None = None,
) -> list[OSCEResult]:
    """Run the full mini-OSCE: 5 personas × 5 candidates × 5 turns.

    Parallelises over (persona × candidate) via :func:`asyncio.gather`.
    Judges are blinded by anonymising candidate model-ids to
    ``blinded_id_A..E`` (a fresh permutation per call).

    Parameters
    ----------
    panel_models:
        The 5 candidate model_ids per ``data/model_panel.yaml``.
    personas:
        The 5 personas per ``data/personas.yaml``.
    num_turns:
        Defaults to :data:`OSCE_NUM_TURNS` (5).  Lower for unit tests.
    patient_simulator_fn / panel_model_fn / osce_judge_fn:
        Mockable hooks; default to the production vendor shims.  Tests
        inject deterministic mocks here.
    rng:
        Random source for the blind-id permutation; defaults to a seeded
        RNG so report figures are reproducible from the locked seed.

    Returns
    -------
    list[OSCEResult]
        One row per (persona × candidate).  Use
        :meth:`OSCEResult.axis_score_dict` to drop into the equity
        stratifier.
    """
    blind_map = _blind_models(panel_models, rng=rng)

    async def _one(persona: Persona, model_id: str) -> OSCEResult:
        blinded_id = blind_map[model_id]
        turns, anon_transcript = await _run_conversation(
            persona,
            model_id,
            blinded_id,
            num_turns=num_turns,
            patient_simulator_fn=patient_simulator_fn,
            panel_model_fn=panel_model_fn,
        )
        judge_output = await osce_judge_fn(anon_transcript, persona, blinded_id)
        axis_scores = _coerce_axis_scores(judge_output)
        return OSCEResult(
            persona_id=persona.name,  # data-spec Persona uses name as id
            model_id=model_id,
            blinded_id=blinded_id,
            turns=turns,
            axis_scores=axis_scores,
            triage_parse_fail_count=sum(1 for t in turns if t.triage_parse_failed),
        )

    coros = [_one(p, m) for p in personas for m in panel_models]
    return await asyncio.gather(*coros)


def osce_results_to_dicts(results: Sequence[OSCEResult]) -> list[dict[str, Any]]:
    """Helper for serialising into ``findings.json`` (data-spec contract)."""
    return [dataclasses.asdict(r) for r in results]
# OSCE-results JSONL contract for frontend-report (Option B per team-lead's
# round-3 conflict-2 resolution).
# Why a separate file (NOT JudgeScore.osce_axis):
#
# ``data.schemas.JudgeScore.principle_id`` is an int 1..12 keyed to the
# Constitutional MNH rubric (data/constitution.yaml).  The OSCE 12 axes
# (:data:`OSCE_AXES`) are a **different** rubric — AMIE-inspired, adapted
# from Tu et al. *Nature 2025* — keyed to the conversation as a whole.
# Mixing them on one row would conflate two distinct rubrics and require a
# discriminator field on JudgeScore that nothing else on the row uses.
#
# Option B keeps the two rubrics in separate streams:
# ``results/osce_results.jsonl`` carries one row per
# (persona × model × axis × judge × turn).  ``turn_idx`` is ``None`` for
# whole-transcript axis scores (the AMIE methodology's default — judges
# score the entire conversation, not each turn) and is reserved as
# ``int`` for any future per-turn breakdown.

OSCE_RESULTS_DEFAULT_PATH: str = "results/osce_results.jsonl"
"""Default on-disk path frontend-report's radar-pivot reads from."""

OSCE_RESULTS_SCHEMA_VERSION: int = 1
"""Bump when the row shape below changes (frontend-report's pivot keys on this)."""


def _osce_result_to_jsonl_rows(
    result: OSCEResult,
    *,
    judge_id: str = "ensemble",
    schema_version: int = OSCE_RESULTS_SCHEMA_VERSION,
) -> list[dict[str, Any]]:
    """Flatten one :class:`OSCEResult` into 12 JSONL rows (one per axis).

    Row shape (the contract DM-d to frontend-report):

    .. code-block:: json

        {
          "schema_version": 1,
          "persona_id": "Lakshmi",
          "model_id": "claude-sonnet-4-6",
          "blinded_id": "blinded_id_C",
          "axis": "history_taking",
          "score": 4.0,
          "judge_id": "ensemble",
          "turn_idx": null,
          "rationale": "..."
        }

    ``judge_id`` defaults to ``"ensemble"`` because the production OSCE
    judge is a multi-judge mean (per :mod:`eval.judges`); per-judge
    breakdowns (one row per judge) are emitted by passing different
    ``judge_id`` values from a wrapper.  ``turn_idx=None`` for the
    whole-transcript scores AMIE produces; reserved as int for future
    per-turn tallies.
    """
    return [
        {
            "schema_version": schema_version,
            "persona_id": result.persona_id,
            "model_id": result.model_id,
            "blinded_id": result.blinded_id,
            "axis": axis_score.axis,
            "score": float(axis_score.score),
            "judge_id": judge_id,
            "turn_idx": None,
            "rationale": axis_score.rationale,
        }
        for axis_score in result.axis_scores
    ]


def osce_results_to_jsonl(
    results: Sequence[OSCEResult],
    path: str | Path = OSCE_RESULTS_DEFAULT_PATH,
    *,
    judge_id: str = "ensemble",
    append: bool = False,
) -> Path:
    """Write OSCE results as JSONL for frontend-report's radar pivot.

    One JSON object per line — each row is one (persona × model × axis ×
    judge × turn) cell in the OSCE-results contract.  Per row count: 12
    axes × |results| rows total.

    Parameters
    ----------
    results:
        Output of :func:`run_osce`.
    path:
        Output path; created with parents.  Defaults to
        :data:`OSCE_RESULTS_DEFAULT_PATH` (``results/osce_results.jsonl``).
    judge_id:
        Tag to attach to every row's ``judge_id`` field.  Defaults to
        ``"ensemble"`` (the multi-judge mean).
    append:
        If True, open with ``"a"`` instead of ``"w"`` so multiple OSCE
        runs can stream into the same file (useful when judges are run
        per-vendor in separate processes).

    Returns
    -------
    Path
        The path the rows were written to.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written = 0
    with p.open(mode, encoding="utf-8") as fh:
        for result in results:
            for row in _osce_result_to_jsonl_rows(
                result, judge_id=judge_id
            ):
                fh.write(json.dumps(row, ensure_ascii=False))
                fh.write("\n")
                written += 1
    logger.info("osce_results_to_jsonl: wrote %d rows to %s", written, p)
    return p


__all__ = [
    "OSCE_AXES",
    "OSCE_NUM_TURNS",
    "OSCE_RESULTS_DEFAULT_PATH",
    "OSCE_RESULTS_SCHEMA_VERSION",
    "PATIENT_SIMULATOR_MODEL",
    "Persona",  # data.schemas.Persona (Pydantic) when available, dataclass fallback otherwise
    "TurnRecord",
    "OSCEAxisScore",
    "OSCEResult",
    "run_osce",
    "osce_results_to_dicts",
    "osce_results_to_jsonl",
]
