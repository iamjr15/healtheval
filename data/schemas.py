"""Pydantic schemas for data files, result files, and triage JSON."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Optional

from datetime import datetime

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)
class _Base(BaseModel):
    """Strict base — forbid unknown keys so YAML drift surfaces immediately."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
        validate_assignment=True,
    )
class Datasheet(_Base):
    """Per-artefact Datasheet for Datasets stub (Gebru et al. CACM 2021).

    Kept intentionally small — the report carries the full prose datasheet;
    this struct is the machine-readable handle so the harness can dump a
    provenance footer alongside results.

    ``purpose`` remains an alias for ``intended_use`` when reading older
    artifacts. Optional package metadata supplements the explicit description,
    intended use, limitations and sources.
    """
    description: str = Field(..., description="What the dataset contains.")
    intended_use: str = Field(
        ...,
        description="The eval-harness consumption pattern.",
        validation_alias=AliasChoices("intended_use", "purpose"),
    )
    limitations: str = Field(..., description="Known gaps, biases, scope cuts.")
    version: int = Field(default=1, ge=1)
    sources: list["SourceCitation"] = Field(default_factory=list)
    name: Optional[str] = Field(
        default=None, description="Optional short identifier for the artefact."
    )
    maintainer: Optional[str] = Field(default=None)
    license: Optional[str] = Field(default=None, description="e.g. 'Apache-2.0', 'CC-BY-4.0'.")
    created_at: Optional[datetime] = Field(default=None)


class SourceCitation(_Base):
    """A WHO / MoHFW / ICMR citation grounding a prompt, principle, or persona."""

    name: str
    url: Optional[HttpUrl] = None
    paragraph_id: Optional[str] = Field(
        default=None,
        description="Human-readable paragraph anchor (e.g., 'WHO diabetes fact sheet: symptoms').",
    )
class TriageLabel(str, Enum):
    RED = "RED"
    AMBER = "AMBER"
    GREEN = "GREEN"


class ReferralAction(str, Enum):
    """Closed set of structured referral actions every panel model must choose from.

    Mapped to Track 1 risk-stratification semantics:
      * continue              — no escalation, routine health education
      * refer_health_worker             — refer to community-level ASHA/ANM
      * refer_phc             — refer to Primary Health Centre (same-day or scheduled)
      * refer_emergency   — medical emergency, dial India 112 / nearest emergency department
    """

    CONTINUE = "continue"
    REFER_HEALTH_WORKER = "refer_health_worker"
    REFER_PHC = "refer_phc"
    REFER_EMERGENCY = "refer_emergency"


class TriageOutput(_Base):
    """The schema-first JSON envelope every panel model emits.

    Parse failures count as incorrect (the schema-first triage contract). Validators are
    intentionally lenient on whitespace and strict on enum membership so
    judges can distinguish hallucinated labels from valid-but-wrong labels.
    """

    triage_label: TriageLabel
    referral_action: ReferralAction
    red_flags_detected: list[str] = Field(
        default_factory=list,
        description=(
            "Source-grounded health danger signs the model recognised in "
            "the user message. Empty list ↔ no red flag detected."
        ),
    )
    triage_reason: Optional[str] = Field(
        default=None,
        description="Short human-readable reason for the triage label.",
    )

    @field_validator("red_flags_detected")
    @classmethod
    def _strip_red_flags(cls, v: list[str]) -> list[str]:
        return [s.strip() for s in v if s and s.strip()]

    @field_validator("triage_reason")
    @classmethod
    def _strip_triage_reason(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class SystemPromptOutputSchema(_Base):
    """YAML mirror of `TriageOutput` so YAML readers don't need to import Python."""

    triage_label: list[Literal["RED", "AMBER", "GREEN"]]
    referral_action: list[
        Literal[
            "continue",
            "refer_health_worker",
            "refer_phc",
            "refer_emergency",
        ]
    ]
    red_flags_detected: Literal["list[str]"]
    triage_reason: Literal["str"]


class SystemPromptConfig(_Base):
    """Shared health system prompt applied uniformly across all configured panel models."""

    name: str
    version: int = Field(default=1, ge=1)
    language: Literal["hi-IN"] = "hi-IN"
    system_prompt: Annotated[str, StringConstraints(min_length=200)] = Field(
        ..., description="Hindi-first health assistant instruction (~300 tokens)."
    )
    output_schema: SystemPromptOutputSchema
    sources: list[SourceCitation]
    datasheet: Datasheet
    notes: Optional[str] = None
class DispatchType(str, Enum):
    API = "API"


class ProviderName(str, Enum):
    ANTHROPIC = "ANTHROPIC"
    GOOGLE = "GOOGLE"
    SARVAM = "SARVAM"
    LOCAL = "LOCAL"  # CeRAI's umbrella for externally hosted/local endpoints


class ModelPanelEntry(_Base):
    """One candidate model under the shared health system prompt."""

    model_id: str
    provider: ProviderName
    base_url: Optional[HttpUrl] = None
    api_key_env: str = Field(
        ...,
        description="Env var name holding the API key (never inline a key).",
    )
    rate_limit_rpm: int = Field(..., gt=0)
    dispatch_type: DispatchType = DispatchType.API
    application_type: Optional[Literal["API"]] = None
    cerai_provider: Optional[Literal["GEMINI", "LOCAL"]] = (
        Field(
            default=None,
            description=(
                "How the CeRAI AIEvaluationTool dispatches this entry "
                "(see the judge-panel contract)."
            ),
        )
    )
    notes: Optional[str] = None


class JudgePanelEntry(_Base):
    """One judge in the current 3-judge cross-family jury."""

    model_id: str
    provider: ProviderName
    family: Literal["anthropic", "google", "sarvam"]
    role: Literal["judge"] = "judge"
    self_judging_avoidance: bool = Field(
        ...,
        description=(
            "If true and this judge model is also a panel target, drop this "
            "judge from the jury for that prompt (HEALTH-PARIKSHA pattern, "
            "the judge-panel contract)."
        ),
    )


class ModelPanel(_Base):
    panel: list[ModelPanelEntry] = Field(..., min_length=1)
    judge_panel: list[JudgePanelEntry] = Field(..., min_length=3)
    datasheet: Datasheet

    @model_validator(mode="after")
    def _check_unique_model_ids(self) -> "ModelPanel":
        ids = [m.model_id for m in self.panel]
        if len(set(ids)) != len(ids):
            raise ValueError("model_panel.panel contains duplicate model_id values")
        return self
class ScoringRubric(_Base):
    """1-5 Likert scoring rubric for a constitution principle."""

    score_1: str
    score_2: str
    score_3: str
    score_4: str
    score_5: str


class ConstitutionPrinciple(_Base):
    """One health judge-rubric principle.

    Field aliases (eval-core integration, May 10 2026):
      * `id` accepts `principle_id` (eval-core's loader name).
      * `source_citation` accepts `source` (shorter eval-core name).
    Either spelling validates; canonical names are `id` / `source_citation`.
    """

    id: int = Field(
        ...,
        ge=1,
        le=12,
        validation_alias=AliasChoices("id", "principle_id"),
    )
    name: str
    description: str
    source_citation: str = Field(
        ...,
        validation_alias=AliasChoices("source_citation", "source"),
    )
    example_violation: str
    scoring_rubric: ScoringRubric


class Constitution(_Base):
    principles: list[ConstitutionPrinciple] = Field(..., min_length=12, max_length=12)
    datasheet: Datasheet

    @model_validator(mode="after")
    def _ids_are_1_through_12(self) -> "Constitution":
        ids = sorted(p.id for p in self.principles)
        if ids != list(range(1, 13)):
            raise ValueError(
                f"Constitution principles must have ids 1..12, got {ids}"
            )
        return self
class RiskTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AgeGroup(str, Enum):
    CHILD = "child"
    ADOLESCENT = "adolescent"
    ADULT = "adult"
    OLDER_ADULT = "older_adult"
    UNSPECIFIED = "unspecified"


class LanguageProficiency(_Base):
    devanagari: Literal["none", "basic", "fluent"]
    roman: Literal["none", "basic", "fluent"]
    hinglish: Literal["none", "basic", "fluent"]


class PersonaMetadata(_Base):
    """Equity-stratification axes health-tagged on each persona (the equity-axis schema)."""

    caste: Literal["SC", "ST", "OBC", "General", "unspecified"]
    geography: Literal["urban", "peri_urban", "rural", "aspirational_district", "unspecified"]
    education_level: Literal[
        "none", "primary", "secondary", "higher", "unspecified"
    ]
    language_proficiency: LanguageProficiency
    age_group: AgeGroup = AgeGroup.UNSPECIFIED
    frontline_worker_proxy: bool = Field(
        default=False,
        description="True if persona phrases as ASHA/ANM, False if end-beneficiary.",
    )


class Persona(_Base):
    name: str
    hindi_name: str
    age: int = Field(..., ge=0, le=120)
    age_group: AgeGroup
    risk_tier: RiskTier
    hidden_diagnosis: str
    hidden_action: ReferralAction
    red_flags: list[str] = Field(default_factory=list)
    opening: Annotated[str, StringConstraints(min_length=10)] = Field(
        ..., description="Hindi text initiating the dialogue."
    )
    persona_metadata: PersonaMetadata


class Personas(_Base):
    personas: list[Persona] = Field(..., min_length=5, max_length=5)
    turns_per_dialogue: int = Field(default=5, ge=1)
    datasheet: Datasheet
class PromptCategory(str, Enum):
    FACTUALITY = "factuality"
    SAFETY = "safety"
    TRIAGE = "triage"
    REFUSAL = "refusal"
    EQUITY = "equity"


class CrisisFlag(str, Enum):
    NONE = "none"
    SUICIDAL_IDEATION = "suicidal_ideation"
    DOMESTIC_VIOLENCE = "domestic_violence"
    MEDICAL_EMERGENCY = "medical_emergency"


class Prompt(_Base):
    id: Annotated[str, StringConstraints(pattern=r"^(health|rt)-\d{3}$")]
    hindi_text: str
    devanagari_text: str = Field(
        ..., description="Devanagari equivalent of the Hindi, Roman-Hindi or Hinglish prompt."
    )
    category: PromptCategory
    expected_triage_label: TriageLabel
    expected_referral_action: ReferralAction
    refusal_expected: bool = False
    citation_expected: bool = False
    crisis_flags: list[CrisisFlag] = Field(default_factory=list)
    source_paragraph_url: Optional[HttpUrl] = None
    source_paragraph_id: Optional[str] = None
    persona_metadata: PersonaMetadata
    notes: Optional[str] = None
    health_topic: str = "general_health"

    @model_validator(mode="after")
    def _requires_devanagari(self) -> "Prompt":
        if not any("\u0900" <= c <= "\u097f" for c in self.devanagari_text):
            raise ValueError("devanagari_text must contain a Devanagari equivalent")
        return self


class Prompts(_Base):
    prompts: list[Prompt] = Field(..., min_length=30)
    datasheet: Datasheet

    @model_validator(mode="after")
    def _curated_count_at_least_30(self) -> "Prompts":
        hand = [p for p in self.prompts if p.id.startswith("health-")]
        if len(hand) < 30:
            raise ValueError(
                f"need ≥30 health-* prompts (got {len(hand)}); "
                "redteam rt-* prompts are added later by Promptfoo medical:* plugins"
            )
        return self
class ReferenceItem(_Base):
    """A source-grounded reference prompt (the source-grounded reference-set contract PRIMARY ground truth)."""

    id: Annotated[str, StringConstraints(pattern=r"^ref-\d{3}$")]
    hindi_text: str
    devanagari_text: str
    expected_safety_action: Literal["continue", "refer", "urgent"]
    expected_referral_action: ReferralAction
    expected_triage_label: TriageLabel
    factual_checklist: list[str] = Field(..., min_length=1)
    refusal_expected: bool = False
    citation_expected: bool = False
    red_flag_match_required: list[str] = Field(default_factory=list)
    wrong_answer_examples: list[str] = Field(default_factory=list)
    source_url: HttpUrl
    source_paragraph: str
    source_citations: list[dict] = Field(default_factory=list)
    persona_metadata: PersonaMetadata
    health_topic: str = "general_health"
    review_status: Literal["pending_clinical_review", "clinician_reviewed"] = "pending_clinical_review"
    script_variant_required: list[
        Literal["devanagari", "roman", "hinglish"]
    ] = Field(
        default_factory=list,
        description=(
            "Scripts that the cross-language battery (eval/cross_language.py, "
            "the script-variance check) MUST run on this prompt. Empty list (default) means "
            "the prompt is Devanagari-only. Cross-language sentinel rows "
            "(ref-026..ref-030 in the canonical reference_set.yaml) typically "
            "set this to ['devanagari', 'roman', 'hinglish'] so the script-"
            "gap probe (Khullar 2025 replication) picks them up "
            "programmatically rather than via id-range convention."
        ),
    )


class ReferenceSet(_Base):
    items: list[ReferenceItem] = Field(..., min_length=20, max_length=30)
    datasheet: Datasheet
class EquityCategory(str, Enum):
    """Lead-defined 6-category taxonomy for health-translated EquityMedQA Hindi prompts.

    Replaces the prior `EquitySubcategory` enum (May 10 2026 round 2). Maps
    each prompt to ONE primary equity dimension; multi-axis prompts use
    `EQUITY_INTERSECTIONAL`.
    """

    CASTE = "equity_caste"
    DISABILITY = "equity_disability"
    LITERACY = "equity_literacy"
    GEOGRAPHY = "equity_geography"
    LANGUAGE = "equity_language"
    INTERSECTIONAL = "equity_intersectional"


class TranslationMethod(str, Enum):
    """Provenance of the Hindi translation per the translated-subset provenance check / Codex R6."""

    CLAUDE_LLM_DRAFT = "claude_llm_draft"
    AI_AUTHORED_DRAFT = "ai_authored_draft"
    HUMAN_NATIVE_SPEAKER = "human_native_speaker"
    HUMAN_BILINGUAL_REVIEWER = "human_bilingual_reviewer"


class QualityGateStatus(str, Enum):
    """Translation quality gate per the translated-subset provenance check / Codex R6.

    Lifecycle:
      1. `LLM_DRAFT_PENDING_BILINGUAL_REVIEW` — Claude Sonnet 4.6 LLM-drafted,
         awaiting bilingual review.
      2. After binding bilingual review (2026-05-10 per user instruction,
         replacing the originally-planned candidate manual review) one of:
           * `CODEX_BILINGUAL_REVIEW_PASSED_AS_IS` — review verdict OK with
             no edits required.
           * `CODEX_BILINGUAL_REVIEW_PASSED_WITH_FIXES_APPLIED` — review
             flagged HIGH/MEDIUM issues; data-spec applied the recommended
             re-translation; final text reflects the reviewer's binding
             verdict.
      3. `BILINGUAL_REVIEW_PASSED` / `BILINGUAL_REVIEW_FAILED` — generic
         human-bilingual-reviewer terminal states (kept for v2 / future
         reviewer dispatches; not used in v1).
    """

    LLM_DRAFT_PENDING_BILINGUAL_REVIEW = "llm_draft_pending_bilingual_review"
    CODEX_BILINGUAL_REVIEW_PASSED_AS_IS = "codex_bilingual_review_passed_as_is"
    CODEX_BILINGUAL_REVIEW_PASSED_WITH_FIXES_APPLIED = (
        "codex_bilingual_review_passed_with_fixes_applied"
    )
    BILINGUAL_REVIEW_PASSED = "bilingual_review_passed"
    BILINGUAL_REVIEW_FAILED = "bilingual_review_failed"


class EquityItem(_Base):
    """One health-translated EquityMedQA TRINDS Hindi prompt (the translated-subset provenance check)."""

    id: Annotated[str, StringConstraints(pattern=r"^eq-\d{3}$")]
    base_ref_id: Optional[str] = None
    english_source: str = Field(
        ...,
        description="English prompt or description; provenance identifies translated or AI-authored data.",
        validation_alias=AliasChoices("english_source", "source_english_text"),
    )
    hindi_text: str
    devanagari_text: str
    translation_method: TranslationMethod = TranslationMethod.CLAUDE_LLM_DRAFT
    review_required: bool = True
    back_translation_bleu: Optional[float] = Field(default=None, ge=0, le=100)
    category: EquityCategory
    expected_triage_label: Optional[TriageLabel] = None
    expected_referral_action: Optional[ReferralAction] = None
    equity_axis_tag: "EquityAxis"  # forward ref to Literal defined below
    source_url: HttpUrl
    dataset_version: str = Field(
        ...,
        description=(
            "e.g. 'katielink/EquityMedQA TRINDS @ <commit-sha> (<fetch-date>)'."
        ),
    )
    quality_gate_status: QualityGateStatus = (
        QualityGateStatus.LLM_DRAFT_PENDING_BILINGUAL_REVIEW
    )
    persona_metadata: PersonaMetadata


class EquitySubset(_Base):
    items: list[EquityItem] = Field(..., min_length=30, max_length=180)
    datasheet: Datasheet


class SafetyCategory(str, Enum):
    """Lead-defined 6-category taxonomy for health-translated MedSafetyBench Hindi.

    Replaces the prior `SafetyAMACategory` enum (May 10 2026 round 2). Maps
    each prompt to ONE primary safety failure mode the prompt is probing for.
    """

    REFUSAL_REQUIRED = "safety_refusal_required"
    DRUG_INTERACTION = "safety_drug_interaction"
    DOSAGE_CORRECTNESS = "safety_dosage_correctness"
    DIAGNOSTIC_CAUTION = "safety_diagnostic_caution"
    WHEN_NOT_TO_HELP = "safety_when_not_to_help"
    SELF_HARM = "safety_self_harm"


class SafetyItem(_Base):
    """One health-translated MedSafetyBench Hindi prompt (the translated-subset provenance check)."""

    id: Annotated[str, StringConstraints(pattern=r"^sf-\d{3}$")]
    english_source: str = Field(
        ...,
        description="English prompt or description; provenance identifies translated or AI-authored data.",
        validation_alias=AliasChoices("english_source", "source_english_text"),
    )
    hindi_text: str
    devanagari_text: str
    translation_method: TranslationMethod = TranslationMethod.CLAUDE_LLM_DRAFT
    review_required: bool = True
    back_translation_bleu: Optional[float] = Field(default=None, ge=0, le=100)
    category: SafetyCategory
    expected_refusal: bool
    expected_triage_label: Optional[TriageLabel] = None
    expected_red_flags: list[str] = Field(default_factory=list)
    source_url: HttpUrl
    dataset_version: str = Field(
        ...,
        description=(
            "e.g. 'AI4LIFE-GROUP/med-safety-bench@<commit-sha> "
            "category_<n> (<fetch-date>)'."
        ),
    )
    quality_gate_status: QualityGateStatus = (
        QualityGateStatus.LLM_DRAFT_PENDING_BILINGUAL_REVIEW
    )
    us_context_excluded: bool = Field(
        default=True,
        description="True if this item passed the US-context filter (the translated-subset provenance check).",
    )
    persona_metadata: PersonaMetadata


class SafetySubset(_Base):
    items: list[SafetyItem] = Field(..., min_length=20, max_length=30)
    datasheet: Datasheet
class JudgeScore(_Base):
    judge_model_id: str
    principle_id: int = Field(..., ge=1, le=12)
    score: float = Field(..., ge=1, le=5)
    rationale: Optional[str] = None
    self_judging_dropped: bool = False
    judge_parse_succeeded: bool = True
    judge_error_type: Optional[str] = None


class BootstrapCI(_Base):
    """scipy.stats.bootstrap output (the statistical-rigor contract)."""

    metric: str
    point_estimate: float
    ci_low_95: float
    ci_high_95: float
    n_resamples: int = Field(default=10_000, ge=1_000)
    paired: bool = False


class BetaBinomialCI(_Base):
    """Beta-Binomial conjugate-prior 95% credible interval (Qu NeurIPS 2025)."""

    metric: str
    successes: int = Field(..., ge=0)
    trials: int = Field(..., gt=0)
    cred_low_95: float = Field(..., ge=0, le=1)
    cred_high_95: float = Field(..., ge=0, le=1)
    prior_alpha: float = Field(default=1.0, gt=0)
    prior_beta: float = Field(default=1.0, gt=0)
EquityAxis = Literal[
    "age_group",
    "risk_tier",
    "language_script",
    "frontline_worker_proxy",
    "crisis_flag_overlap",
    "geography",
    "caste_community",
    "education_disability_combined",
]
"""Canonical 8 equity axes (the equity-axis schema). Mirrors eval-core EQUITY_AXES tuple."""


OSCEAxis = Literal[
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
]
"""Canonical 12 mini-OSCE axes (the Mini-OSCE design). Mirrors eval-core OSCE_AXES.

Maps to the triage and rubric contract's 12 axes as follows (Tu et al. Nature 2025 sub-axes adapted
to health context):
  history_taking          ↔ History-taking completeness + Information sufficiency
  examination             ↔ (clinical exam axis — N/A for chat; scored 1.0)
  diagnosis_accuracy      ↔ Diagnostic accuracy (hidden_diagnosis identified)
  management_plan         ↔ Management plan correctness (hidden_action recommended)
  communication           ↔ Communication clarity (Hindi register)
  empathy                 ↔ Empathy
  professionalism         ↔ Citation-grounding + Patient safety
  structure               ↔ Multi-turn conversational coherence
  efficiency              ↔ Information sufficiency (no excessive turns)
  safety_net              ↔ Escalation/referral correctness
  schema_first_triage     ↔ Risk-stratification correctness (the schema-first triage contract)
  cultural_appropriateness ↔ Cultural appropriateness + Equity sensitivity
"""


class EquityStratumResult(_Base):
    axis: EquityAxis
    stratum: str
    n: int = Field(..., gt=0)
    point_estimate: float
    disparity_ratio_vs_majority: Optional[float] = None


class BiasReport(_Base):
    """Per-judge self-preference bias estimate (Wataoka et al. 2024,
    arXiv:2410.21819) for the cross-family jury. Surfaces in
    the source-corpus bundle0 (failure-mode taxonomy) and the reproducibility appendix
    as evidence that judge bias was measured, not assumed away.

    Persisted at the top-level of `FindingsSchema.bias_reports` (one row
    per judge). Promoted from eval-core's intermediate dataclass on
    request (May 10 round 2) so findings.json round-trips include it
    without an extra dataclass→dict step.
    """

    judge_id: str = Field(..., description="Judge model_id matching JudgePanelEntry.model_id.")
    self_family: Literal["anthropic", "google", "sarvam"] = Field(
        ...,
        description=(
            "Family this judge belongs to; the 'self' set are panel responses "
            "produced by models in this same family (e.g., when judge is "
            "claude-sonnet-4-6 and the panel target was claude-sonnet-4-6 — "
            "though that case is normally dropped via self_judging_avoidance)."
        ),
    )
    self_family_mean: float = Field(
        ...,
        description="Mean Likert score this judge gave to panel responses from its own family.",
    )
    other_family_mean: float = Field(
        ...,
        description="Mean Likert score this judge gave to panel responses from other families.",
    )
    self_preference: float = Field(
        ...,
        description=(
            "Signed bias estimate: self_family_mean − other_family_mean. "
            "Positive = judge preferred its own family; negative = anti-self-"
            "preference; ~0 = no detectable bias."
        ),
    )
    n_self: int = Field(..., ge=0, description="Number of panel responses scored from the self family.")
    n_other: int = Field(..., ge=0, description="Number of panel responses scored from other families.")


class FindingsItem(_Base):
    """One row in findings.json: model × prompt × judges × stats × strata."""

    model_id: str
    prompt_id: str
    triage_label_predicted: Optional[TriageLabel] = None
    referral_action_predicted: Optional[ReferralAction] = None
    triage_parse_succeeded: bool
    response_text: str
    latency_ms: float = Field(..., ge=0)
    judges: list[JudgeScore] = Field(default_factory=list)
    bootstrap_ci: list[BootstrapCI] = Field(default_factory=list)
    beta_binomial_ci: list[BetaBinomialCI] = Field(default_factory=list)
    krippendorff_alpha: Optional[float] = Field(default=None, ge=-1, le=1)
    equity_strata: list[EquityStratumResult] = Field(default_factory=list)


class FindingsSchema(_Base):
    """The machine-readable findings dump (the machine-readable findings contract + the reproducibility finding item)."""

    schema_version: int = Field(default=1, ge=1)
    plan_version: str = Field(default="v1.5.3")
    items: list[FindingsItem]
    bias_reports: list[BiasReport] = Field(
        default_factory=list,
        description=(
            "Per-judge self-preference bias estimates (Wataoka 2024). One row "
            "per judge in the jury. Empty list = bias not yet computed."
        ),
    )
    datasheet: Datasheet
__all__ = [
    "Datasheet",
    "SourceCitation",
    "TriageLabel",
    "ReferralAction",
    "TriageOutput",
    "SystemPromptOutputSchema",
    "SystemPromptConfig",
    "DispatchType",
    "ProviderName",
    "ModelPanelEntry",
    "JudgePanelEntry",
    "ModelPanel",
    "ScoringRubric",
    "ConstitutionPrinciple",
    "Constitution",
    "RiskTier",
    "AgeGroup",
    "LanguageProficiency",
    "PersonaMetadata",
    "Persona",
    "Personas",
    "PromptCategory",
    "CrisisFlag",
    "Prompt",
    "Prompts",
    "ReferenceItem",
    "ReferenceSet",
    "EquityCategory",
    "EquityItem",
    "EquitySubset",
    "SafetyCategory",
    "SafetyItem",
    "SafetySubset",
    "TranslationMethod",
    "QualityGateStatus",
    "JudgeScore",
    "BootstrapCI",
    "BetaBinomialCI",
    "BiasReport",
    "EquityAxis",
    "OSCEAxis",
    "EquityStratumResult",
    "FindingsItem",
    "FindingsSchema",
]
