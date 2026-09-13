"""Workbench paths, limits, and method defaults."""
from __future__ import annotations

import os
from pathlib import Path

from eval.final_method import final_safety_method_config

_FINAL_METHOD_CONFIG = final_safety_method_config()
SAFETY_PRINCIPLE_IDS: tuple[int, ...] = tuple(
    int(pid) for pid in _FINAL_METHOD_CONFIG["principle_ids"]
)
EVALUATOR_TRIAGE_GREEN_THRESHOLD: float = float(
    _FINAL_METHOD_CONFIG["green_threshold"]
)
EVALUATOR_TRIAGE_AMBER_THRESHOLD: float = float(
    _FINAL_METHOD_CONFIG["amber_threshold"]
)
CERAI_DB_SCORE_CUTOFF: float = float(os.getenv("CERAI_DB_SCORE_CUTOFF", "0.5"))
"""Default CeRAI Docker-DB comparator cutoff; scores below this route answers."""
# Resolve from this file so local and container runs share paths.
PACKAGE_DIR: Path = Path(__file__).resolve().parent
REPO_ROOT: Path = PACKAGE_DIR.parent

DATA_DIR: Path = REPO_ROOT / "data"
RESULTS_DIR: Path = REPO_ROOT / "results"
DOCS_DIR: Path = REPO_ROOT / "docs"
RUBRICS_DIR: Path = DATA_DIR / "rubrics"
PATH_TOOL_META: Path = RESULTS_DIR / "tool_meta_evaluation.json"
PATH_CERAI_DB_SCORES: Path = RESULTS_DIR / "cerai_db_scores_refset.json"
PATH_INSPECT: Path = RESULTS_DIR / "inspect_safety_refset_eval.json"
PATH_PROMPTFOO_SAVED_HTML: Path = RESULTS_DIR / "promptfoo_saved.html"
PATH_REFERENCE_SET: Path = DATA_DIR / "reference_set.yaml"
PATH_CONSTITUTION: Path = DATA_DIR / "constitution.yaml"
PATH_CALIBRATION_EXAMPLES: Path = DATA_DIR / "judge_calibration_examples.yaml"

# Append-only overlays; persistent mode writes through the server endpoint.
PATH_HITL_REVIEWS_JSONL: Path = RESULTS_DIR / "hitl_reviews.jsonl"
PATH_THRESHOLD_SWEEPS_JSONL: Path = RESULTS_DIR / "threshold_sweeps.jsonl"
PATH_JUDGE_TRACE_JSONL: Path = RESULTS_DIR / "judge_trace.jsonl"
PATH_BUDGET_TODAY_JSONL: Path = RESULTS_DIR / "budget_today.jsonl"

HITL_REVIEWS_PATH: Path = PATH_HITL_REVIEWS_JSONL
THRESHOLD_SWEEPS_PATH: Path = PATH_THRESHOLD_SWEEPS_JSONL
JUDGE_TRACE_PATH: Path = PATH_JUDGE_TRACE_JSONL
BUDGET_TODAY_PATH: Path = PATH_BUDGET_TODAY_JSONL
PROJECT_ID: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")


def _float_env(name: str, default: float) -> float:
    """Read ``name`` from env / Streamlit secrets, falling back to default."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


DAILY_BUDGET_USD: float = _float_env("DAILY_BUDGET_USD", 5.00)
"""Hard daily ceiling on Live Demo dispatch spend across the whole service."""

RATE_LIMIT_PER_SESSION: int = int(os.getenv("LIVE_DEMO_RATE_LIMIT_PER_SESSION", "5"))
"""Max Live Demo dispatches per browser session (session_state counter)."""

MAX_PROMPT_CHARS: int = int(os.getenv("LIVE_DEMO_MAX_PROMPT_CHARS", "1000"))
"""Reject Live Demo dispatches whose prompt exceeds this length."""

HITL_REVIEW_RATE_LIMIT_PER_SESSION: int = int(
    os.getenv("HITL_REVIEW_RATE_LIMIT_PER_SESSION", "30")
)
"""Per the shipped workbench design the HITL persistence contract Codex r2 #1: HITL form rate limit."""

HITL_RATE_LIMIT_PER_SESSION: int = HITL_REVIEW_RATE_LIMIT_PER_SESSION

HITL_COMMENT_MAX_CHARS: int = 2000
HITL_PROMOTE_REASONING_MAX_CHARS: int = 1000
HITL_PROMOTE_REASON_MAX_CHARS: int = HITL_PROMOTE_REASONING_MAX_CHARS

# If unset, HITL reviews stay session-local and downloadable.
CLOUDFLARE_HITL_ENDPOINT_URL: str | None = (
    os.getenv("CLOUDFLARE_HITL_ENDPOINT_URL") or None
)

JSONL_CACHE_TTL_SECONDS: int = 60

CANONICAL_FAILURE_CATEGORIES: tuple[str, ...] = (
    "missed_red_flag",
    "unsafe_reassurance",
    "wrong_referral_level",
    "unsupported_medication_advice",
    "incomplete_answer",
    "hallucinated_policy",
    "schema_parse_failure",
    "over_refusal",
)

RUBRIC_PACKS_V1: tuple[str, ...] = (
    "health_safety_v1",
    "factuality_v1",
    "limitation_awareness_v1",
    "triage_schema_v1",
)

GITHUB_REPO_URL: str = os.getenv(
    "GITHUB_REPO_URL", "https://github.com/iamjr15/healtheval"
)
CLOUDFLARE_LIVE_DEMO_URL: str = os.getenv("CLOUDFLARE_LIVE_DEMO_URL", "")
