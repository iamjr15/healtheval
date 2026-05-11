"""Pydantic schema for v3 structured-output judge responses.

This Pydantic model defines the v3 judge schema contract
that the v3 judge prompt asks the LLM to fill out.  The v3 fields
(``confidence``, ``rubric_breakdown``, ``failure_type``, ``evidence``)
are NOT exposed on the public ``data.schemas.JudgeScore`` shape — they
land in the internal :class:`eval.judge_parse_result.JudgeParseResult`
struct and the per-call ``results/judge_trace.jsonl`` row.  Existing
consumers (calibration recompute, tool_meta aggregator, dashboard
pages 2/3/4) read only ``score`` + ``rationale`` and stay unchanged.

The ``score`` and ``reason`` fields map directly onto the existing
``JudgeScore.score`` / ``JudgeScore.rationale`` columns; everything
else is metadata for the trace.
"""
from __future__ import annotations

from typing import Optional

try:  # pragma: no cover — exercised at runtime
    from pydantic import BaseModel, ConfigDict, Field
except ImportError as exc:  # pragma: no cover — pydantic is a hard dep
    raise RuntimeError(
        "pydantic>=2 is required for eval.judge_schema; install via "
        "`uv pip install pydantic` or rebuild the env."
    ) from exc


class JudgeOutputV3(BaseModel):
    """Structured judge output for the v3 methodology run.

    Validation rules:

    * ``score`` clamps to the canonical Likert 1..5 (matches
      ``data.schemas.JudgeScore.score`` and the constitution's
      ``score_1``..``score_5`` rubric anchors).
    * ``confidence`` is the judge's self-reported certainty; lives only
      in the trace, never on the public score row.
    * ``rubric_breakdown`` lets the judge cite which sub-anchor of the
      rubric drove the decision (e.g.
      ``{"score_4_anchor": 0.7, "score_5_anchor": 0.3}``).  Free-form
      keys; values are normalised weights.
    * ``failure_type`` should be a member of the rubric pack's
      ``failure_categories`` list (the validator doesn't enforce this —
      enforcement lives in ``calibration_retrieval`` so the schema
      stays decoupled from rubric loading).
    * ``evidence`` collects short pull-quotes from the response that
      anchor the score; useful for the dashboard's Page 7 trace view.

    ``model_config`` sets ``extra="ignore"`` so a judge that accidentally
    emits an extra field doesn't trigger a hard parse failure — the
    fallback path is reserved for genuine schema breaks.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    score: float = Field(ge=1.0, le=5.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rubric_breakdown: dict[str, float] = Field(default_factory=dict)
    failure_type: Optional[str] = None
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


__all__ = ["JudgeOutputV3"]
