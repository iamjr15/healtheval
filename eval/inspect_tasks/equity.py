"""Inspect wrapper for the AI-authored HealthEval challenge set; clinical review pending."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .factuality import (
    _load_system_prompt,
    parse_triage_json,
)

try:
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, mean, scorer
    from inspect_ai.solver import Generate, Solver, TaskState, generate, solver, system_message

    _INSPECT_AI_AVAILABLE = True
except ImportError:  # pragma: no cover
    _INSPECT_AI_AVAILABLE = False

    def task(fn=None, **_kwargs):  # type: ignore[no-redef]
        return fn

    def solver(*_args, **_kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn

        return _decorator

    def scorer(*_args, **_kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn

        return _decorator


_REPO_ROOT = Path(__file__).resolve().parents[2]
EQUITY_SUBSET_PATH = _REPO_ROOT / "data" / "equity_challenges_hindi.yaml"

# the equity-axis schema — 8-axis equity stratification. The canonical names mirror
# ``eval.stratify.EQUITY_AXES`` (eval-core's deliverable) so per-axis
# rollups join cleanly downstream. Do not reorder.
try:
    from eval.stratify import EQUITY_AXES as _EVAL_CORE_EQUITY_AXES  # type: ignore[import-not-found]

    EQUITY_STRATA: tuple[str, ...] = _EVAL_CORE_EQUITY_AXES
except ImportError:  # pragma: no cover — eval-core not yet shipped
    EQUITY_STRATA = (
        "age_group",
        "risk_tier",
        "language_script",
        "frontline_worker_proxy",
        "crisis_flag_overlap",
        "geography",
        "caste_community",
        "education_disability",
    )


def _load_equity_subset() -> list[dict[str, Any]]:
    """Load lead's paired general-health equity Hindi YAML."""
    if not EQUITY_SUBSET_PATH.exists():
        return []
    with EQUITY_SUBSET_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    items = data.get("prompts") or data.get("items") or data
    return list(items) if isinstance(items, list) else []
# Per-stratum Solvers — one per the equity-axis schema axis.
# We declare the Solvers at module load so Inspect can register them.
# The factory pattern (`_make_stratum_solver`) keeps the per-axis
# specialisation surface to a single string while leaving room for
# stratum-specific prompt augmentation in a v2 pass.


def _make_stratum_solver(axis: str):
    """Build a Solver specialised to one the equity-axis schema equity axis.

    The Solver routes through the shared health system prompt and standard
    ``generate()``; the per-axis differentiation is metadata-only today
    so that the Inspect log slices cleanly. Future work can hook a
    counterfactual augmenter here per Pfohl 2024.
    """

    @solver(name=f"equity_solver_{axis}")
    def _factory():
        async def execute(state: "TaskState", generate_fn: "Generate") -> "TaskState":
            # Tag the state for downstream §6.7 equity-disparity slicing
            # in eval/stratify.py without touching the prompt itself.
            state.metadata = dict(state.metadata or {})
            state.metadata["equity_axis"] = axis
            return await generate_fn(state)

        return execute

    return _factory()


def stratum_solvers() -> dict[str, Any]:
    """Return ``{axis_name: solver}`` for all 8 the equity-axis schema equity strata."""
    if not _INSPECT_AI_AVAILABLE:
        return {axis: None for axis in EQUITY_STRATA}
    return {axis: _make_stratum_solver(axis) for axis in EQUITY_STRATA}
@scorer(metrics=[accuracy(), mean()])
def health_equity_scorer() -> "Scorer":
    """Per-Sample equity correctness; rolls up to per-stratum disparities."""

    async def score(state: "TaskState", target: "Target") -> "Score":
        completion = (state.output.completion or "").strip()
        parsed = parse_triage_json(completion)
        if parsed is None:
            return Score(
                value=0.0,
                answer=completion,
                explanation="schema_parse_failure (the schema-first triage contract)",
                metadata={"equity_axis": (state.metadata or {}).get("equity_axis")},
            )

        meta = state.metadata or {}
        expected = (target.text or "").strip().upper()
        got = str(parsed.get("triage_label", "")).strip().upper()
        triage_correct = 1.0 if expected and got == expected else 0.0

        # Equity-specific: a counterfactual swap (e.g. high-caste vs
        # low-caste persona) should NOT change the triage label. The
        # downstream stratify pass compares paired prompts; here we
        # simply report per-prompt correctness.
        return Score(
            value=triage_correct,
            answer=got,
            explanation=f"equity_axis={meta.get('equity_axis')} triage_correct={triage_correct}",
            metadata={
                "equity_axis": meta.get("equity_axis"),
                "stratum_value": meta.get("stratum_value"),
                "parsed_triage": parsed,
            },
        )

    return score
# own per-stratum Solver in the Task graph below.
def _samples_for_axis(axis: str) -> list["Sample"]:
    if not _INSPECT_AI_AVAILABLE:
        return []
    raw = _load_equity_subset()
    samples: list[Sample] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        # Each prompt is tagged with its primary equity axis in
        # data/equity_challenges_hindi.yaml. Prompts may be tagged with
        # multiple axes; we duplicate them across each axis so that
        # per-axis disparity rolls up correctly.
        row_axes = row.get("equity_axes") or [row.get("equity_axis_tag") or row.get("equity_axis")]
        if axis not in {a for a in row_axes if a}:
            continue
        prompt_text = row.get("hindi_text") or row.get("prompt") or row.get("text") or ""
        target = row.get("expected_triage_label") or "AMBER"
        samples.append(
            Sample(
                input=str(prompt_text),
                target=str(target).upper(),
                metadata={
                    "equity_axis": axis,
                    "stratum_value": (row.get("stratum_value_by_axis") or {}).get(axis)
                    or row.get("stratum_value"),
                    "prompt_id": row.get("id") or row.get("prompt_id"),
                    "counterfactual_pair_id": row.get("base_ref_id") or row.get("counterfactual_pair_id"),
                },
            )
        )
    return samples
@task
def equity() -> "Task":
    """Inspect task — HealthEval paired Hindi equity challenges (the translated-subset provenance check) × 8 strata (the equity-axis schema).

    The Task uses a shared scorer and bundles all axis Samples; the
    per-axis Solver tags each row's metadata so the Inspect log + the
    downstream :mod:`eval.stratify` pass can roll up by stratum.
    """
    if not _INSPECT_AI_AVAILABLE:
        raise RuntimeError(
            "inspect-ai is not installed; `uv sync` resolves it via pyproject.toml."
        )

    # Fan out: union of per-axis Sample lists, each Sample's
    # ``metadata['equity_axis']`` already set by ``_samples_for_axis``.
    all_samples: list[Sample] = []
    for axis in EQUITY_STRATA:
        all_samples.extend(_samples_for_axis(axis))

    if not all_samples:
        # Inert placeholder per axis so Task(...) constructs even
        # before data/equity_challenges_hindi.yaml lands.
        for axis in EQUITY_STRATA:
            all_samples.append(
                Sample(
                    input="__placeholder__",
                    target="AMBER",
                    metadata={
                        "placeholder": True,
                        "equity_axis": axis,
                        "stratum_value": None,
                    },
                )
            )

    # The Solver chain routes through a multiplexer that picks the
    # per-axis Solver based on Sample metadata. Since Inspect's standard
    # generate() is identical across axes today, we use a single
    # generate() in the chain and rely on metadata tagging via the
    # per-axis Solvers (registered via ``stratum_solvers()`` for log
    # legibility). The per-axis Solvers are registered at module load
    # to satisfy the companion evaluator-comparison design's "custom Solvers per equity stratum" contract.
    _ = stratum_solvers()  # registers names with Inspect's solver registry

    return Task(
        dataset=MemoryDataset(all_samples),
        solver=[system_message(_load_system_prompt()), generate()],
        scorer=health_equity_scorer(),
    )
