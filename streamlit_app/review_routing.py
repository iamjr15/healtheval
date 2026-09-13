"""Route flagged answers and compare only available evaluator decisions."""
from __future__ import annotations

from typing import Any, Mapping


def decision_review_reasons(
    methodology: Mapping[str, Any],
    cerai: Mapping[str, Any],
    inspect: Mapping[str, Any],
) -> list[str]:
    flagged = methodology.get("flagged")
    if not isinstance(flagged, bool):
        return []
    reasons = ["answer_flagged"] if flagged else []
    for name, decision in (("cerai", cerai), ("inspect", inspect)):
        other_flagged = decision.get("flagged")
        if isinstance(other_flagged, bool) and other_flagged != flagged:
            reasons.append(f"{name}_vs_methodology_disagree")
    return reasons
