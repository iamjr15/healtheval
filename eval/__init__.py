"""HealthEval eval-core package.

Houses the four methodology layers owned by teammate ``eval-core``:

* :mod:`eval.judges`  — 3-judge cross-family jury with HEALTH-PARIKSHA
  self-judging avoidance (the judge-panel contract).
* :mod:`eval.stats`   — paired bootstrap CIs, Krippendorff's α, McNemar,
  Beta-Binomial credible intervals (statistical utilities and confidence-interval reporting).
* :mod:`eval.osce`    — 5-persona × 5-turn mini-OSCE with the AMIE-inspired
  12-axis rubric and judge-blind shuffling (the Mini-OSCE design ).
* :mod:`eval.stratify`— 8-axis equity stratification post-processor
  (the equity-axis schema).

All vendor SDK calls live behind mockable ``_call_judge_<vendor>`` hooks so
the unit tests written by ``foundation-eng`` can run fully offline.

Current contract:
    * ``data/schemas.py`` contains the canonical Pydantic v2 schemas.
    * The shared-system-prompt schema-first triage contract is:
      ``{"triage_label": "RED|AMBER|GREEN", "referral_action": str,
      "red_flags_detected": list[str], "triage_reason": str}`` plus the
      natural-language Hindi response. Older artefacts may omit
      ``triage_reason``. Parse failures count as incorrect.
"""

from __future__ import annotations

__all__ = [
    "judges",
    "stats",
    "osce",
    "reference_risk",
    "stratify",
]
