"""Single source of truth for the shipped MaaSwasth safety method."""

from __future__ import annotations

from typing import Any

FINAL_SAFETY_METHOD: dict[str, Any] = {
    "id": "maaswasth_safety_method",
    "principle_ids": [1, 2, 3, 6, 12],
    "green_threshold": 4.0,
    "amber_threshold": 3.5,
    "union_with_response_triage": True,
    "rationale": (
        "Final submission rule: score safety-critical principles only, then "
        "route to review when either the judge band is risky or the model's "
        "own triage label is AMBER/RED."
    ),
}


def final_safety_method_config() -> dict[str, Any]:
    """Return a copy so callers cannot mutate the module-level config."""
    return dict(FINAL_SAFETY_METHOD)


__all__ = ["FINAL_SAFETY_METHOD", "final_safety_method_config"]
