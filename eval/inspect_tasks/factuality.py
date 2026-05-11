"""Inspect ``factuality`` task wrapper.

Scores each candidate model's response to the n=30 source-grounded
reference set (``data/reference_set.yaml``, lead's deliverable per the source-grounded reference-set contract) on:

1. **Schema-first JSON conformance** (axis 11 of the triage and rubric contract OSCE rubric) —
   the response must contain a parseable
   ``{"triage_label": "RED|AMBER|GREEN",
       "referral_action": str,
       "red_flags_detected": list[str]}``
   block. Parse failures count as INCORRECT, period.
2. **Triage-label correctness** vs ``expected_triage_label`` (continue /
   refer / urgent → GREEN / AMBER / RED).
3. **Factual checklist coverage** — fraction of ``factual_checklist``
   items entailed by the natural-language Hindi response.

Solver chain
------------

``system_message(<MNH system prompt>)``  →  ``generate()``

The system prompt is loaded from ``data/system_prompt_mnh.yaml`` (locked,
identical for every candidate per §4.1). The Sample input is the prompt
text in Devanagari; ``target`` carries the expected triage label;
``metadata`` carries the factual checklist and source paragraph for the
Scorer.

Scorer
------

A custom ``mnh_factuality_scorer`` parses the JSON block, compares
``triage_label`` to ``target``, and computes checklist coverage either
via simple string-containment (offline) or via the DeepEval GEval judge
(online — see :func:`eval.judges.geval_factuality`, eval-core's
deliverable). The combined score is the mean of the two sub-scores.

Output
------

Native Inspect log archived to ``results/inspect/factuality/`` per
the saved Inspect log Hr 27-29.5 — sits alongside the Promptfoo HTML report for
cross-harness sanity checking.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

    # Inspect imports — guarded so the module is importable in static
# analysis contexts where inspect-ai isn't installed yet (CI cold start
# before ``uv sync``). After ``uv sync`` resolves ``inspect-ai>=0.3``
# (pyproject.toml), the real symbols load and ``@task`` registers the
try:
    from inspect_ai import Task, task
    from inspect_ai.dataset import MemoryDataset, Sample
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, mean, scorer
    from inspect_ai.solver import Generate, TaskState, generate, solver, system_message

    _INSPECT_AI_AVAILABLE = True
except ImportError:  # pragma: no cover — only fires pre-`uv sync`
    _INSPECT_AI_AVAILABLE = False

    def task(fn=None, **_kwargs):  # type: ignore[no-redef]
        return fn

    def scorer(*_args, **_kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn

        return _decorator
# Configuration: paths into data-spec + lead deliverables.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PROMPT_PATH = _REPO_ROOT / "data" / "system_prompt_mnh.yaml"
REFERENCE_SET_PATH = _REPO_ROOT / "data" / "reference_set.yaml"

# Schema-first JSON contract (the schema-first triage contract). Every candidate
# response under the shared system prompt MUST emit this block.
_TRIAGE_JSON_RE = re.compile(r"\{[^{}]*\"triage_label\"[^{}]*\}", re.DOTALL)


def _load_system_prompt() -> str:
    """Load the locked MNH Hindi-first system prompt verbatim.

    Falls back to a placeholder if data-spec hasn't yet shipped the YAML;
    the placeholder still teaches the JSON schema so smoke tests pass.
    """
    if SYSTEM_PROMPT_PATH.exists():
        with SYSTEM_PROMPT_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        text = data.get("system_prompt") or data.get("text") or ""
        if text:
            return str(text)
    return (
        "You are a Hindi-first maternal/neonatal health triage assistant grounded in "
        "WHO ANC 2016, MoHFW JSY/JSSK/PMSMA, and ICMR guidelines. After your Hindi "
        "natural-language reply, append a JSON block of exactly the form:\n"
        '{"triage_label": "RED|AMBER|GREEN", "referral_action": "<string>", '
        '"red_flags_detected": ["<string>", ...]}\n'
        "Parse failures are evaluated as incorrect."
    )


def _load_reference_samples() -> list[dict[str, Any]]:
    """Load the n=30 source-grounded reference set (the source-grounded reference-set contract).

    Returns an empty list if the lead's YAML hasn't landed yet — the
    Inspect Task is still well-formed; it just runs on an empty dataset
    until the data shows up.
    """
    if not REFERENCE_SET_PATH.exists():
        return []
    with REFERENCE_SET_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    items = data.get("prompts") or data.get("items") or data
    return list(items) if isinstance(items, list) else []
# Schema-first parsing utility (shared with safety.py + equity.py).
# Delegate to eval.judges.parse_triage_response — the single source of
# truth eval-core ships per their teammate-message contract. It validates
# against data.schemas.TriageLabel + ReferralAction, so unknown labels /
# actions count as parse failures (stricter than our regex fallback,
# matching the schema-first triage contract contract). Fallback to a local regex is
# retained for the rare case eval-core's module isn't importable
# (e.g. partial installs in offline CI cold start).
try:
    from eval.judges import parse_triage_response as _shared_parse_triage_response

    def parse_triage_json(text: str) -> dict[str, Any] | None:
        """Schema-first triage parser — delegates to eval.judges.

        The Scorer treats ``None`` as an automatic INCORRECT (the
        schema-first JSON contract is a hard pass/fail axis per the triage and rubric contract
        axis 11). Validation against TriageLabel + ReferralAction enums
        is enforced inside :func:`eval.judges.parse_triage_response`.
        """
        return _shared_parse_triage_response(text)

except ImportError:  # pragma: no cover — fallback when eval-core absent

    def parse_triage_json(text: str) -> dict[str, Any] | None:  # type: ignore[no-redef]
        """Fallback regex parser used only when eval.judges isn't importable."""
        if not text:
            return None
        match = _TRIAGE_JSON_RE.search(text)
        if not match:
            try:
                brace_start = text.index("{")
                brace_end = text.rindex("}") + 1
                obj = json.loads(text[brace_start:brace_end])
            except (ValueError, json.JSONDecodeError):
                return None
        else:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        if not isinstance(obj, dict) or "triage_label" not in obj:
            return None
        return obj
@scorer(metrics=[accuracy(), mean()])
def mnh_factuality_scorer() -> "Scorer":
    """Composite scorer for the factuality task.

    Score = 0.5 × triage_label_correct + 0.5 × checklist_coverage.
    A schema-parse failure short-circuits to score=0 (axis 11 contract).
    """

    async def score(state: "TaskState", target: "Target") -> "Score":
        completion = (state.output.completion or "").strip()
        parsed = parse_triage_json(completion)

        if parsed is None:
            return Score(
                value=0.0,
                answer=completion,
                explanation="schema_parse_failure (the schema-first triage contract)",
            )

        # 1. Triage label correctness
        expected = (target.text or "").strip().upper()
        got = str(parsed.get("triage_label", "")).strip().upper()
        triage_correct = 1.0 if expected and got == expected else 0.0

        # 2. Factual checklist coverage (offline keyword-containment fallback;
        #    the real implementation calls the DeepEval GEval judge in
        #    eval.judges. Keyword fallback keeps the scorer deterministic in
        #    smoke tests).
        checklist = (state.metadata or {}).get("factual_checklist", []) or []
        if not checklist:
            checklist_coverage = 1.0  # no checklist → don't penalise
        else:
            hay = completion.lower()
            hits = sum(1 for fact in checklist if str(fact).lower() in hay)
            checklist_coverage = hits / max(1, len(checklist))

        composite = 0.5 * triage_correct + 0.5 * checklist_coverage
        return Score(
            value=composite,
            answer=str(parsed.get("triage_label", "")),
            explanation=(
                f"triage_correct={triage_correct} "
                f"checklist_coverage={checklist_coverage:.2f}"
            ),
            metadata={
                "triage_correct": triage_correct,
                "checklist_coverage": checklist_coverage,
                "parsed_triage": parsed,
            },
        )

    return score
def _placeholder_sample() -> "Sample":
    """One inert Sample so ``Task(...)`` constructs even before
    ``data/reference_set.yaml`` lands. Inspect rejects empty
    datasets at Task construction time. Marked so reviewers/eval
    runners can detect the placeholder and skip it."""
    return Sample(
        input="__placeholder__",
        target="GREEN",
        metadata={"placeholder": True, "factual_checklist": []},
    )


def _samples_from_reference_set() -> list["Sample"]:
    """Convert lead's reference_set.yaml rows into Inspect Samples."""
    if not _INSPECT_AI_AVAILABLE:
        return []
    raw = _load_reference_samples()
    samples: list[Sample] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        prompt_text = row.get("prompt") or row.get("text") or ""
        expected_triage = (
            row.get("expected_triage_label")
            or _safety_action_to_triage(row.get("expected_safety_action"))
            or "GREEN"
        )
        samples.append(
            Sample(
                input=str(prompt_text),
                target=str(expected_triage).upper(),
                metadata={
                    "factual_checklist": row.get("factual_checklist", []) or [],
                    "red_flag_match_required": row.get("red_flag_match_required", []) or [],
                    "source_url": row.get("source_url"),
                    "source_paragraph": row.get("source_paragraph"),
                    "prompt_id": row.get("id") or row.get("prompt_id"),
                },
            )
        )
    return samples


def _safety_action_to_triage(action: str | None) -> str | None:
    """Map ``expected_safety_action`` (continue/refer/urgent) → RED/AMBER/GREEN."""
    if not action:
        return None
    mapping = {"continue": "GREEN", "refer": "AMBER", "urgent": "RED"}
    return mapping.get(str(action).strip().lower())
@task
def factuality() -> "Task":
    """Inspect task — factuality wrap of the source-grounded reference-set contract reference set.

    Run via:

        inspect eval eval/inspect_tasks/factuality.py:factuality \\
            --model anthropic/claude-sonnet-4-6  # one of the 4 candidates
    """
    if not _INSPECT_AI_AVAILABLE:
        raise RuntimeError(
            "inspect-ai is not installed; `uv sync` resolves it via pyproject.toml."
        )
    samples = _samples_from_reference_set() or [_placeholder_sample()]
    return Task(
        dataset=MemoryDataset(samples),
        solver=[system_message(_load_system_prompt()), generate()],
        scorer=mnh_factuality_scorer(),
    )
