"""Route flagged answers and compare only available evaluator decisions."""
from __future__ import annotations

import math
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


def comparison_review_flag(mean: Any, cutoff: float) -> bool | None:
    """Unavailable comparison scores must not become passing decisions."""
    try:
        score = float(mean)
    except (TypeError, ValueError):
        return None
    return score < cutoff if math.isfinite(score) else None


def comparison_disagrees(flagged: Any, other_flagged: Any) -> bool | None:
    """Only two measured decisions can establish agreement or disagreement."""
    if not isinstance(flagged, bool) or not isinstance(other_flagged, bool):
        return None
    return flagged != other_flagged
