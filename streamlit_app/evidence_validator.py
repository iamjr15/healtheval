"""Phase 0 startup validator: fail loud, fail early.

Runs once on first page render (and on cache invalidation when an
artefact's mtime changes).  For each required file, executes a list of
``(field_path, predicate)`` rules; the first failure raises
``EvidenceMissing`` with a message that names the file, the rule, and
the script that regenerates it.  The ``app.py`` shell renders that
exception as a single-page error banner so the user sees a useful
"run X" instruction instead of a stack trace.

Why predicates instead of Pydantic: the canonical evidence files mix
plain dicts, arrays, and YAML lists; full Pydantic models would balloon
the maintenance surface (and ``data/schemas.py`` already covers the
write side).  The validator is a *contract test* the dashboard runs
against the live artefacts — small, fast, and easy to extend per page.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from eval.benchmark import require_current_benchmark

from .canonical_selector import select_complete_methodology_artifact
from .config import (
    PATH_CALIBRATION_EXAMPLES,
    PATH_CERAI_DB_SCORES,
    PATH_CONSTITUTION,
    PATH_INSPECT,
    PATH_REFERENCE_SET,
    PATH_TOOL_META,
    REPO_ROOT,
    RUBRICS_DIR,
)

# ``rule`` is ``(field_path, predicate, regen_script)`` where field_path
# uses dotted notation rooted at the document and predicate returns True
# when the value is acceptable.  ``"."`` selects the document itself.
Rule = tuple[str, Callable[[Any], bool], str]


class EvidenceMissing(RuntimeError):
    """Raised by ``validate_evidence()`` when a required artefact / rule fails."""


def _valid_cerai_db_scores(payload: object) -> bool:
    """Validate the saved CeRAI Docker DB score export, without live DB access."""
    if not isinstance(payload, dict) or len(payload) != 30:
        return False
    required = {"accuracy", "relevance", "hallucination", "mean"}
    for ref_id, scores in payload.items():
        if not str(ref_id).startswith("ref-") or not isinstance(scores, dict):
            return False
        if not required <= set(scores):
            return False
        for metric in required:
            try:
                value = float(scores[metric])
            except (TypeError, ValueError):
                return False
            if not 0 <= value <= 1:
                return False
    return True


def _display_path(path: Path) -> str:
    """Render ``path`` relative to the repo root if possible, else as absolute.

    Tests sometimes monkeypatch a config path to a tmpdir outside the repo;
    ``Path.relative_to`` would raise ``ValueError`` in that case and bury
    the actual ``EvidenceMissing`` message under a stack trace.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _load(path: Path) -> Any:
    """Load JSON or YAML based on suffix.  Raises ``EvidenceMissing`` cleanly."""
    rel = _display_path(path)
    if not path.exists():
        raise EvidenceMissing(
            f"Required evidence file `{rel}` is missing."
        )
    try:
        with path.open() as f:
            if path.suffix in (".yaml", ".yml"):
                return yaml.safe_load(f)
            return json.load(f)
    except (json.JSONDecodeError, yaml.YAMLError, OSError) as exc:
        raise EvidenceMissing(
            f"Required evidence file `{rel}` could not be parsed: {exc}"
        ) from exc


def _resolve(doc: Any, dotted: str) -> Any:
    """Walk ``dotted`` (``a.b.c`` / ``"."``) into ``doc``.  Missing → KeyError."""
    if dotted == ".":
        return doc
    cursor: Any = doc
    for part in dotted.split("."):
        if isinstance(cursor, dict):
            if part not in cursor:
                raise KeyError(part)
            cursor = cursor[part]
        else:  # array index by integer-like part, or invalid
            try:
                cursor = cursor[int(part)]
            except (TypeError, ValueError, IndexError) as exc:
                raise KeyError(part) from exc
    return cursor


def _check(path: Path, rules: list[Rule]) -> None:
    doc = _load(path)
    rel = _display_path(path)
    for field_path, predicate, regen in rules:
        try:
            value = _resolve(doc, field_path)
        except KeyError as exc:
            raise EvidenceMissing(
                f"Evidence file `{rel}` is missing required field `{field_path}`. "
                f"Re-run `{regen}` to regenerate."
            ) from exc
        try:
            ok = bool(predicate(value))
        except Exception as exc:  # predicate errored, treat as failure
            raise EvidenceMissing(
                f"Evidence file `{rel}` failed rule on `{field_path}`: {exc}. "
                f"Re-run `{regen}` to regenerate."
            ) from exc
        if not ok:
            raise EvidenceMissing(
                f"Evidence file `{rel}` failed rule on `{field_path}`. "
                f"Re-run `{regen}` to regenerate."
            )


def validate_evidence() -> Path | None:
    """Run all rules.  Return the selected methodology path on success.

    Two-step validation: pick the canonical methodology artefact
    first, then validate everything else (including the selected path's
    per-row schema).  Fails loudly if no complete methodology artefact
    exists — ``app.py`` surfaces that as the landing-page error.
    """
    selected = select_complete_methodology_artifact()

    # Selected methodology — selector already proved completeness; this only
    # checks per-row schema integrity that downstream pages depend on.
    methodology_rules: list[Rule] = [
        (
            "rows",
            lambda v: isinstance(v, list) and len(v) > 0,
            "scripts/run_panel_refset_eval.py",
        ),
        (
            "rows",
            lambda v: all(
                isinstance(r.get("judge_scores"), list)
                and len(r["judge_scores"]) >= 5
                for r in v
            ),
            "scripts/run_panel_refset_eval.py",
        ),
        (
            "jury",
            lambda v: isinstance(v, list) and len(v) >= 1,
            "scripts/run_panel_refset_eval.py",
        ),
    ]
    if selected is not None:
        _check(selected, methodology_rules)

    if selected is not None:
      _check(
        PATH_TOOL_META,
        [
            (
                "table_final_method",
                lambda v: isinstance(v, list) and len(v) >= 1,
                "scripts/compute_panel_tool_meta.py",
            ),
            (
                "table_panel_models",
                lambda v: isinstance(v, list) and len(v) >= 1,
                "scripts/compute_panel_tool_meta.py",
            ),
        ],
    )

    if PATH_CERAI_DB_SCORES.exists():
      _check(
        PATH_CERAI_DB_SCORES,
        [
            (
                "scores_by_prompt",
                _valid_cerai_db_scores,
                "scripts/export_cerai_db_scores.py or Docker DB score export",
            ),
        ],
    )

    if PATH_INSPECT.exists():
      _check(
        PATH_INSPECT,
        [
            (
                "evaluator_outputs",
                lambda v: isinstance(v, dict) and len(v) == 30,
                "eval/inspect_tasks/* (Inspect mode)",
            ),
        ],
    )

    _check(
        PATH_REFERENCE_SET,
        [
            (
                "items",
                lambda v: isinstance(v, list) and len(v) == 30,
                "(curate manually — reference set is locked at n=30)",
            ),
        ],
    )
    for path in (PATH_TOOL_META, PATH_CERAI_DB_SCORES, PATH_INSPECT):
        if path.exists():
            try:
                require_current_benchmark(_load(path), label=_display_path(path))
            except ValueError as exc:
                raise EvidenceMissing(str(exc)) from exc

    _check(
        PATH_CONSTITUTION,
        [
            (
                "principles",
                lambda v: isinstance(v, list) and len(v) == 12,
                "(curate manually — constitution has 12 principles)",
            ),
        ],
    )

    # Each rubric pack must declare the right metric name + a v* version.
    for metric in ("health_safety", "factuality", "limitation_awareness", "triage_schema"):
        rubric_path = RUBRICS_DIR / f"{metric}_v1.yaml"
        _check(
            rubric_path,
            [
                (
                    "metric",
                    lambda v, m=metric: v == m,
                    f"data/rubrics/{metric}_v1.yaml",
                ),
                (
                    "version",
                    lambda v: isinstance(v, str) and v.startswith("v"),
                    f"data/rubrics/{metric}_v1.yaml",
                ),
                (
                    "failure_categories",
                    lambda v: isinstance(v, list) and len(v) >= 5,
                    f"data/rubrics/{metric}_v1.yaml",
                ),
            ],
        )

    _check(
        PATH_CALIBRATION_EXAMPLES,
        [
            (
                "examples",
                lambda v: isinstance(v, list) and len(v) >= 5,
                "scripts/promote_to_calibration.py",
            ),
        ],
    )

    return selected


__all__ = ["EvidenceMissing", "validate_evidence"]
