"""Internal struct for v3 judge parse output.

This internal parse-result struct is **never** exposed on
the public :class:`data.schemas.JudgeScore` contract.  Existing
consumers (calibration recompute, dashboard pages 2/3/4) read only
``JudgeScore.score`` + ``JudgeScore.rationale``; the v3 fields land
here and are forwarded to ``results/judge_trace.jsonl`` by the caller.

The struct's ``score`` + ``rationale`` columns are populated identically
in both branches (Pydantic validates → mapped from
:class:`eval.judge_schema.JudgeOutputV3`; or v3 invalid → mapped from
the v1 fallback parser in ``eval.judges._parse_judge_score``).  This
ensures :func:`eval.judges.judge_panel` always returns a usable
``JudgeScore`` regardless of which parser branch fired.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# Local import to avoid a circular at module-load: `eval.judges` imports
# this module, so we read the v1 score-extractor lazily inside parse().
#
# NB: this regex was the only fallback in v1 (where outputs were always
# {"score": <int>, "rationale": <str>} — no nested objects).  v3 outputs
# carry a nested ``rubric_breakdown: {...}`` so the ``[^{}]*`` would stop
# at the first inner brace and never re-find ``"score"``.  The new
# brace-balanced extractor below (``_extract_balanced_object``) handles
# the v3 case; this regex is kept as the last-resort scan for legacy
# v1-shaped output that lacks fences and lacks nested objects.
_SCORE_OBJ_RE = re.compile(r"\{[^{}]*\"score\"[^{}]*\}", re.DOTALL)


# Markdown fence patterns: judges (especially Claude / Gemini) tend to
# wrap JSON output in ```json ... ``` even when explicitly instructed
# "JSON only, no other text".  Strip them robustly before parsing.
_FENCE_OPEN_RE = re.compile(r"^\s*```(?:[a-zA-Z0-9_+-]+)?\s*\n?", re.MULTILINE)
_FENCE_CLOSE_RE = re.compile(r"\n?\s*```\s*$")


def _strip_markdown_fence(raw: str) -> str:
    """Remove a leading ```json (or ```anything) and trailing ``` if present.

    Idempotent — safe to call on already-clean output.  Preserves leading
    natural-language preamble (which the brace-balanced extractor below
    will skip past).  Only strips fences at the boundaries; inline
    triple-backticks inside a string literal are left alone.
    """
    s = raw.strip()
    s = _FENCE_OPEN_RE.sub("", s, count=1)
    s = _FENCE_CLOSE_RE.sub("", s, count=1)
    return s.strip()


def _extract_balanced_object(s: str) -> Optional[dict[str, Any]]:
    """Extract the first complete top-level JSON object from ``s``.

    Uses ``json.JSONDecoder.raw_decode`` so nested objects (v3's
    ``rubric_breakdown: {...}``) and strings containing braces are
    handled correctly — unlike a simple character-counting scan.

    Returns the parsed dict or ``None`` if no balanced JSON object can
    be extracted.  Skips any leading natural-language preamble before
    the first ``{``.
    """
    decoder = json.JSONDecoder()
    # Try every '{' position as the candidate start until one parses cleanly.
    # This is O(n²) worst case but JSON judge outputs are < 4 KB so it's fine.
    start = 0
    while True:
        idx = s.find("{", start)
        if idx < 0:
            return None
        try:
            obj, _end = decoder.raw_decode(s[idx:])
        except (json.JSONDecodeError, ValueError):
            start = idx + 1
            continue
        if isinstance(obj, dict):
            return obj
        # Top-level wasn't an object (rare — judge emitted a bare array?);
        # keep searching past this match.
        start = idx + 1


@dataclass
class JudgeParseResult:
    """Result of parsing one raw judge reply under the v3 strategy.

    Attributes
    ----------
    raw_judge_output:
        The unmodified text returned by the judge model.  Logged into
        ``judge_trace.jsonl`` so the v3 run is reproducible.
    parsed_v3:
        ``None`` when Pydantic validation rejected the output (the v1
        fallback path then populates ``score`` / ``rationale``).
        Otherwise a dict mirroring :class:`JudgeOutputV3`'s shape.
    parser_version:
        ``"v3"`` when ``parsed_v3`` is non-None, ``"v1_fallback"`` when
        the v3 path failed and the v1 regex extractor produced the
        score.  The trace row records this so we can later count what
        share of cells used which path.
    validation_errors:
        Pydantic ``ValidationError`` messages (one per failing field).
        Empty list when ``parsed_v3`` validated cleanly.
    rendered_judge_prompt:
        The exact prompt sent to the judge — built by
        :func:`eval.judges._build_judge_prompt`.  Stored for the audit-trace page
        Page 7 "Replay this call" view.
    score, rationale:
        The two columns the existing ``JudgeScore`` shape needs.
        Always populated regardless of branch.
    """

    raw_judge_output: str
    parsed_v3: Optional[dict[str, Any]]
    parser_version: Literal["v3", "v1_fallback"]
    validation_errors: list[str]
    rendered_judge_prompt: str
    score: float
    rationale: str
    confidence: float = 1.0
    rubric_breakdown: dict[str, float] = field(default_factory=dict)
    failure_type: Optional[str] = None
    evidence: list[str] = field(default_factory=list)

    @classmethod
    def parse(
        cls, raw: str, rendered_prompt: str = ""
    ) -> "JudgeParseResult":
        """Try Pydantic-v3 first; fall back to the v1 regex parser on failure.

        ``rendered_prompt`` is what was actually sent to the judge — pass
        it through so the trace row is self-contained (a future replay
        doesn't need to re-build the prompt from rubric + retrieval).

        Hard parse failures still produce a ``JudgeParseResult`` (never
        raises).  ``score`` defaults to ``1.0`` (worst Likert) on a
        fallback that itself fails — same conservative posture the v1
        parser uses.
        """
        # Lazy import to avoid the eval.judges → judge_parse_result cycle.
        from eval.judge_schema import JudgeOutputV3

        if not raw:
            return cls(
                raw_judge_output=raw,
                parsed_v3=None,
                parser_version="v1_fallback",
                validation_errors=["empty raw judge output"],
                rendered_judge_prompt=rendered_prompt,
                score=1.0,
                rationale="empty judge response (treated as score=1.0 worst Likert)",
            )

        # Try the v3 Pydantic path first.  Three extraction layers, in
        # order from cheapest to most permissive:
        #   1. Strip markdown fences (```json ... ```) and try json.loads.
        #      Handles the common Claude / Gemini case where the judge
        #      wraps output in fences despite "JSON only" instruction.
        #   2. Brace-balanced raw_decode scan — handles v3 outputs whose
        #      nested rubric_breakdown defeats the v1 single-level regex.
        #   3. Legacy regex fallback — only for v1-shape outputs with no
        #      nested objects (kept for back-compat with old judge calls).
        candidate: Any = None
        fenceless = _strip_markdown_fence(raw)
        try:
            candidate = json.loads(fenceless)
        except (json.JSONDecodeError, ValueError):
            candidate = None

        if not isinstance(candidate, dict):
            balanced = _extract_balanced_object(fenceless)
            if balanced is not None:
                candidate = balanced

        if not isinstance(candidate, dict):
            m = _SCORE_OBJ_RE.search(raw)
            if m:
                try:
                    candidate = json.loads(m.group(0))
                except (json.JSONDecodeError, ValueError):
                    candidate = None

        if isinstance(candidate, dict):
            try:
                v3 = JudgeOutputV3.model_validate(candidate)
            except Exception as exc:  # pydantic.ValidationError, etc.
                # v1 fallback — extract score from the same dict, ignore the
                # v3-specific fields.  This branch fires when the judge
                # emitted JSON but missed v3 fields (e.g. confidence range
                # outside [0,1], or score outside [1,5]).
                return cls._fallback_from_dict(candidate, raw, rendered_prompt, str(exc))
            # v3 success: map onto the score / rationale columns the public
            # JudgeScore contract expects.
            return cls(
                raw_judge_output=raw,
                parsed_v3=v3.model_dump(),
                parser_version="v3",
                validation_errors=[],
                rendered_judge_prompt=rendered_prompt,
                score=float(v3.score),
                rationale=v3.reason or "",
                confidence=float(v3.confidence),
                rubric_breakdown=dict(v3.rubric_breakdown),
                failure_type=v3.failure_type,
                evidence=list(v3.evidence),
            )

        # No JSON object in the raw output at all — pure v1 fallback path.
        return cls(
            raw_judge_output=raw,
            parsed_v3=None,
            parser_version="v1_fallback",
            validation_errors=[
                f"no JSON object found in raw output: {raw[:120]!r}"
            ],
            rendered_judge_prompt=rendered_prompt,
            score=1.0,
            rationale=(
                f"unparseable judge response (treated as score=1.0): {raw[:120]!r}"
            ),
        )

    @classmethod
    def _fallback_from_dict(
        cls,
        data: dict[str, Any],
        raw: str,
        rendered_prompt: str,
        validation_msg: str,
    ) -> "JudgeParseResult":
        """v3 validation failed but the dict has SOME score-shaped data.

        Mirrors the v1 parser's behaviour: clamp to [1.0, 5.0], pull
        rationale if present, treat anything else as a soft failure.
        """
        score_val = data.get("score")
        if isinstance(score_val, (int, float)):
            clamped = max(1.0, min(5.0, float(score_val)))
            rationale = data.get("rationale") or data.get("reason") or ""
            return cls(
                raw_judge_output=raw,
                parsed_v3=None,
                parser_version="v1_fallback",
                validation_errors=[validation_msg],
                rendered_judge_prompt=rendered_prompt,
                score=clamped,
                rationale=str(rationale),
            )
        return cls(
            raw_judge_output=raw,
            parsed_v3=None,
            parser_version="v1_fallback",
            validation_errors=[validation_msg, "no usable score field"],
            rendered_judge_prompt=rendered_prompt,
            score=1.0,
            rationale=f"unparseable judge response (treated as score=1.0): {raw[:120]!r}",
        )

    def to_trace_row(
        self,
        *,
        prompt_id: str,
        judge_model: str,
        principle_id: int,
        rubric_version: str,
        prompt_template_version: str,
        dataset_version: str,
        strategy_version: str,
        calibration_example_ids: list[str],
        cache_key: str,
        timestamp_iso: str,
        duration_sec: float,
        temperature: float = 0.0,
        seed: int = 0,
    ) -> dict[str, Any]:
        """Render this result as a ``judge_trace.jsonl`` row.

        The schema mirrors :class:`streamlit_app.schemas.JudgeTraceRow`
        so the dashboard's Page 7 (Judge Trace) reads the same shape
        the writer here produces.  ``temperature`` + ``seed`` default
        to deterministic-ish values when the caller doesn't track
        them per-call.
        """
        return {
            "cache_key": cache_key,
            "prompt_id": prompt_id,
            "judge_model": judge_model,
            "principle_id": principle_id,
            "temperature": temperature,
            "seed": seed,
            "rubric_version": rubric_version,
            "prompt_template_version": prompt_template_version,
            "dataset_version": dataset_version,
            "strategy_version": strategy_version,
            "calibration_example_ids": list(calibration_example_ids),
            "rendered_judge_prompt": self.rendered_judge_prompt,
            "raw_judge_output": self.raw_judge_output,
            "parser_version": self.parser_version,
            "score": self.score,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "rubric_breakdown": self.rubric_breakdown,
            "failure_type": self.failure_type,
            "evidence": self.evidence,
            "validation_errors": self.validation_errors,
            "timestamp": timestamp_iso,
            "duration_sec": duration_sec,
        }


__all__ = ["JudgeParseResult"]
