"""Pick the complete panel methodology artefact.

A re-run might be in flight when the dashboard loads. Reading a partial
artefact would silently drop rows and corrupt downstream pages, so every
methodology load goes through this selector.

Completeness rule (top-level only, never per-row): the artefact must
satisfy ``n_prompts_done == n_prompts_total`` AND ``len(rows) == total``.
Anything else (including a parseable but in-flight ``_v3.tmp.json``
that hasn't been atomically renamed yet) is skipped.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import RESULTS_DIR

CANDIDATE_PATHS_IN_PRIORITY_ORDER: tuple[Path, ...] = (
    RESULTS_DIR / "methodology_panel_refset_eval.json",
)


def select_complete_methodology_artifact(
    candidates: tuple[Path, ...] = CANDIDATE_PATHS_IN_PRIORITY_ORDER,
) -> Path | None:
    """Return path of the most recent complete methodology artefact, or None.

    Completeness is decided **only** from the top-level counters
    (``n_prompts_done`` / ``n_prompts_total``) and the length of the
    ``rows`` list.  Per-row schema integrity is checked downstream by
    ``evidence_validator.py`` — keeping that out of here means the selector
    stays cheap (one ``json.load`` per candidate, short-circuits on first
    hit) and never mistakes "rows are weird" for "artefact is in flight".
    """
    for path in candidates:
        if not path.exists():
            continue
        try:
            with path.open() as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # Treat malformed JSON as in-flight.
            continue
        if not isinstance(data, dict):
            continue
        done = data.get("n_prompts_done")
        total = data.get("n_prompts_total")
        rows = data.get("rows")
        if (
            isinstance(done, int)
            and isinstance(total, int)
            and isinstance(rows, list)
            and total > 0
            and done == total
            and len(rows) == total
        ):
            return path
    return None

def selected_methodology_version_label(selected: Path | None) -> str:
    """Return a short label for the selected artefact."""
    return "panel" if selected is not None else "unknown"


__all__ = [
    "CANDIDATE_PATHS_IN_PRIORITY_ORDER",
    "select_complete_methodology_artifact",
    "selected_methodology_version_label",
]
