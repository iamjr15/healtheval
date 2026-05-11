"""Typed shapes for the JSON / YAML evidence files the workbench reads.

These are ``TypedDict``s, not Pydantic models — the workbench never
*writes* canonical evidence, so we don't need runtime validation here
(``evidence_validator.py`` does that).  The TypedDicts exist so the
page builders get autocomplete + type-checker support, and so any
schema drift between ``eval/`` outputs and the dashboard surfaces in
review rather than at render time.

If a field is optional in the source artefact, the TypedDict marks it
``NotRequired[...]``.  Per Codex r2 #3 + the audit-trace design of the shipped workbench design: existing
``JudgeScore`` shape is preserved across v1/v2/v3 — v3-only fields land
in ``judge_trace.jsonl`` rather than on this row.
"""
from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict
# results/methodology_panel_refset_eval.json — selected via canonical_selector.
class JudgeScoreRow(TypedDict, total=False):
    """One cell in the (judge × principle) grid for a single prompt.

    ``score`` is the 1..5 Likert; ``rationale`` may be absent on legacy
    rows (added by v3).  ``rubric_version`` + ``calibration_example_ids``
    are also v3-only — pages that consume them must guard with ``.get()``.
    """

    judge_model_id: str
    principle_id: int
    score: float
    rationale: NotRequired[str]
    rubric_version: NotRequired[str]
    calibration_example_ids: NotRequired[list[str]]


class TriageDecision(TypedDict, total=False):
    """The collapsed methodology decision per row (six-principle native band)."""

    triage_label: Literal["RED", "AMBER", "GREEN"]
    flagged: bool
    jury_safety_mean: float
    n_cells: int
    principle_ids: list[int]


class MethodologyRow(TypedDict, total=False):
    prompt_id: str
    prompt: str
    response: str
    response_len: int
    latency_sec: float
    parse_succeeded: bool
    triage_parsed: NotRequired[dict[str, Any]]
    judge_scores: list[JudgeScoreRow]
    judge_mean: float
    decision: TriageDecision


class EvaluatorOutput(TypedDict, total=False):
    """Per-prompt collapsed output stored under ``evaluator_outputs[ref-id]``."""

    flagged: bool
    triage_label: NotRequired[Literal["RED", "AMBER", "GREEN"]]
    jury_safety_mean: NotRequired[float]
    n_cells: NotRequired[int]
    judge_mean_all_principles: NotRequired[float]
    parse_succeeded: NotRequired[bool]
    n_judge_scores: NotRequired[int]


class MethodologyArtifact(TypedDict, total=False):
    """The full ``methodology_panel_refset_eval.json`` shape."""

    export_ts: str
    n_prompts_done: int
    n_prompts_total: int
    evaluator_name: str
    panel_target: str
    jury: list[str]
    evaluator_outputs: dict[str, EvaluatorOutput]
    rows: list[MethodologyRow]
# results/tool_meta_evaluation.json (and _v1 / _v3 variants).
class SensSpecCell(TypedDict, total=False):
    rate: float
    k: int
    n: int
    bootstrap_95ci: list[float]
    beta_binomial_95ci: list[float]


class NativeRow(TypedDict, total=False):
    evaluator: str
    n: int
    sensitivity: SensSpecCell
    specificity: SensSpecCell


class ToolMetaArtifact(TypedDict, total=False):
    ref_section: str
    reference_set: str
    panel_target: str
    n_evaluators_native: int
    evaluators_native: list[str]
    table_native: list[NativeRow]
    table_response_triage: NotRequired[list[NativeRow]]
    calibration_metadata: NotRequired[dict[str, Any]]
    semantic_notes: NotRequired[list[str] | dict[str, Any]]
# CeRAI + Inspect — same envelope; differ in row payloads.
class CeRaiOrInspectArtifact(TypedDict, total=False):
    export_ts: str
    evaluator_name: str
    n_prompts: int
    panel_target: str
    evaluator_outputs: dict[str, dict[str, Any]]
    rows: list[dict[str, Any]]
    notes: NotRequired[str | list[str] | dict[str, Any]]
# data/reference_set.yaml.
class PersonaMetadata(TypedDict, total=False):
    caste: str
    geography: str
    education_level: str
    language_proficiency: dict[str, str]
    frontline_worker_proxy: bool


class ReferenceItem(TypedDict, total=False):
    id: str
    hindi_text: str
    devanagari_text: NotRequired[str]
    expected_safety_action: Literal["continue", "refer", "urgent"]
    expected_referral_action: str
    expected_triage_label: Literal["RED", "AMBER", "GREEN"]
    factual_checklist: list[str]
    refusal_expected: bool
    citation_expected: bool
    red_flag_match_required: list[str]
    wrong_answer_examples: NotRequired[list[str]]
    source_url: str
    source_paragraph: str
    persona_metadata: NotRequired[PersonaMetadata]
    script_variant_required: NotRequired[list[str]]


class ReferenceSet(TypedDict, total=False):
    datasheet: dict[str, Any]
    items: list[ReferenceItem]
# data/constitution.yaml.
class ConstitutionPrinciple(TypedDict, total=False):
    id: int
    name: str
    description: str
    source_citation: str
    example_violation: str
    scoring_rubric: dict[str, str]


class Constitution(TypedDict, total=False):
    principles: list[ConstitutionPrinciple]
    datasheet: dict[str, Any]
# data/rubrics/{metric}_v{N}.yaml — versioned rubric packs (Phase 0).
class RubricScoreExample(TypedDict, total=False):
    score: int
    example_response: str
    why: str


class RubricPack(TypedDict, total=False):
    metric: str
    version: str
    constitution_principle_ids: list[int]
    description: str
    scoring_scale: dict[str, str]
    pass_fail_threshold: float
    score_examples: list[RubricScoreExample]
    common_false_positives: list[str]
    common_false_negatives: list[str]
    domain_specific_rules: list[str]
    language_specific_rules: list[str]
    safety_policy: str
    failure_categories: list[str]
# data/judge_calibration_examples.yaml — seed pack (Phase 0) + HITL-promoted
# entries (offline-bumped from data/judge_calibration_candidates.jsonl).
class CalibrationExample(TypedDict, total=False):
    id: str
    metric: str
    rubric_version: str
    source: Literal["seed", "hitl_promoted"]
    ref_id: str
    prompt: str
    actual_answer: str
    expected_behaviour: str
    human_score: float
    human_reason: str
    failure_category: NotRequired[str]
    approved_by: str
    created_at: str


class CalibrationPack(TypedDict, total=False):
    schema_version: str
    examples: list[CalibrationExample]
# results/hitl_reviews.jsonl — append-only governance record (one JSON per
# line).  Schema mirrors the shipped workbench design the HITL persistence contract.
class HITLOriginalEvaluators(TypedDict, total=False):
    maaswasth_safety_method: Literal["safe", "unsafe"]
    cerai: Literal["safe", "unsafe"]
    inspect: Literal["safe", "unsafe"]


class HITLReview(TypedDict, total=False):
    review_id: str
    prompt_id: str
    reviewer_role: Literal["developer", "clinician", "panel", "other"]
    original_evaluators: HITLOriginalEvaluators
    human_decision: Literal["correct", "incorrect", "safe", "unsafe", "escalate"]
    human_decision_targets: list[str]
    model_response_safe: bool
    needs_clinician_review: bool
    failure_category: str
    promote_to_calibration: bool
    promote_reasoning: NotRequired[str | None]
    comment: str
    rubric_version_at_review: str
    calibration_example_ids_at_review: list[str]
    created_at: str
    client_session_id: str
    persistence_mode: Literal["session_local", "github_api"]
# results/threshold_sweeps.jsonl — append-only experiment configs.
class ThresholdSweep(TypedDict, total=False):
    sweep_id: str
    config: dict[str, Any]
    results: dict[str, dict[str, float]]
    cases_changed_vs_baseline: list[str]
    created_at: str
# results/judge_trace.jsonl — per-call trace (STRETCH; populated by v3 run).
class JudgeTraceRow(TypedDict, total=False):
    cache_key: str
    prompt_id: str
    judge_model: str
    principle_id: int
    temperature: float
    seed: int
    rubric_version: str
    prompt_template_version: str
    dataset_version: str
    strategy_version: str
    calibration_example_ids: list[str]
    rendered_judge_prompt: str
    raw_judge_output: str
    parser_version: Literal["v3", "v1_fallback"]
    score: float
    rationale: str
    timestamp: str
    duration_sec: float
# results/budget_today.jsonl — Live Demo dispatch ledger (per plan_delta Δ2).
class BudgetEntry(TypedDict, total=False):
    ts: str  # ISO 8601
    cost_usd: float
    ip_or_session_id: str
    prompt_id: NotRequired[str]
    model: NotRequired[str]
