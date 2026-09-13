"""8-axis equity stratification post-processor (the equity-axis schema).

For every metric (faithfulness, accuracy, refusal correctness, citation
faithfulness, mini-OSCE 12 axes per §5.5) and every model, compute:

* per-stratum **mean**;
* per-stratum **Krippendorff's α** across the jury (the judge-panel contract) — passed
  through to :func:`eval.stats.krippendorff_alpha`;
* **disparity ratio vs the majority stratum** per the Obermeyer 2019
  framework (Obermeyer et al., *Science* 2019, doi:10.1126/science.aax2342);
* automatic **flag** when any stratum is >10 % absolute below the majority
  stratum (the equity-axis schema binding).

The 8 axes (locked per the equity-axis schema v1.4-restored; cite-paths echoed inline
so the report caption can drop them in verbatim):

1. ``age_group``         — child / adolescent / adult / older adult
                                  / lactation (6 buckets).
2. ``risk_tier``               — low / medium / high.
3. ``language_script``         — Devanagari / Roman / Hinglish-mixed
                                  (Khullar 2025 arXiv:2512.10780).
4. ``frontline_worker_proxy``  — CHW-style vs end-beneficiary
                                  (ASHABot Ramjee CHI 2025).
5. ``crisis_flag_overlap``     — emergency markers present vs not.
6. ``geography``               — rural / peri-urban / urban (NFHS-5).
7. ``caste_community``         — SC / ST / OBC / General (NFHS-5 +
                                  Lee et al. PLOS Digital Health 2025
                                  doi:10.1371/journal.pdig.0000951 — author
                                  is **Lee**, not Mehta).
8. ``education_disability_combined`` — schooling × disability tag
                                  (Pfohl et al. EquityMedQA *Nature
                                  Medicine* 2024 + Panda et al. AccessEval
                                  EMNLP 2025).  Axis name matches the
                                  ``EquityAxis`` Literal in
                                  ``data.schemas`` (per data-spec's May-10
                                  reconciliation).

A ``Finding`` is the unit of input — one prompt × one model × one metric
score with stratum tags attached.  Pluggable so this works equally well on
factuality findings, OSCE axis scores, refusal-correctness booleans, etc.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .stats import krippendorff_alpha

logger = logging.getLogger(__name__)
EQUITY_AXES: tuple[str, ...] = (
    "age_group",
    "risk_tier",
    "language_script",
    "frontline_worker_proxy",
    "crisis_flag_overlap",
    "geography",
    "caste_community",
    "education_disability_combined",  # matches data.schemas.EquityAxis Literal
)

DEFAULT_DEGRADATION_THRESHOLD: float = 0.10
"""Per the equity-axis schema: flag any stratum >10 % absolute below majority."""
@dataclass(frozen=True)
class Finding:
    """One (prompt × model × metric) score with stratum tags attached.

    Attributes
    ----------
    prompt_id:
        Unique prompt id (e.g. ``"refset-007"``).
    model_id:
        Candidate panel model that produced the response.
    metric:
        Metric name (``"faithfulness"``, ``"refusal_correct"``,
        ``"osce_history_taking"``, …).  OSCE axes are flattened by
        prefixing ``"osce_"``.
    score:
        0..1 score (binary metrics use {0, 1}).
    strata:
        Mapping ``axis_name → stratum_value`` for every relevant axis
        (any subset of :data:`EQUITY_AXES`).  Missing keys are treated as
        "stratum unknown" and counted into a ``__missing__`` bucket so
        coverage gaps surface rather than silently disappear.
    judge_scores:
        Optional ``{judge_id: score}`` map per finding — used by
        :func:`stratify` to compute per-stratum Krippendorff α.
        ``np.nan`` is allowed for the dropped Sarvam-105b column under
        HEALTH-PARIKSHA self-judging avoidance (the judge-panel contract).
    """

    prompt_id: str
    model_id: str
    metric: str
    score: float
    strata: Mapping[str, str] = field(default_factory=dict)
    judge_scores: Mapping[str, float] = field(default_factory=dict)


@dataclass
class StratumStats:
    """Per-stratum result block for one (metric × model × axis × stratum)."""

    axis: str
    stratum: str
    n: int
    mean: float
    krippendorff_alpha: float | None  # None when <2 judges or all-NaN
    disparity_ratio: float  # mean / majority_mean (1.0 == parity)
    absolute_gap_vs_majority: float  # majority_mean − mean
    flagged: bool


@dataclass
class StratifiedReport:
    """Full output of :func:`stratify`."""

    metric: str
    model_id: str
    axis_results: dict[str, list[StratumStats]] = field(default_factory=dict)
    flagged: list[StratumStats] = field(default_factory=list)
    n_total: int = 0
def _extract_judge_matrix(
    findings: Sequence[Finding],
) -> tuple[np.ndarray | None, list[str]]:
    """Build a ``(judges × findings)`` reliability matrix.

    Judge ids are unioned across findings so the matrix is rectangular even
    when self-judging avoidance dropped one judge for some rows.  Returns
    ``(None, [])`` when there are <2 judges or no judge scores at all
    (Krippendorff α is undefined).
    """
    judge_ids: list[str] = []
    seen: set[str] = set()
    for f in findings:
        for jid in f.judge_scores:
            if jid not in seen:
                seen.add(jid)
                judge_ids.append(jid)

    if len(judge_ids) < 2 or not findings:
        return None, judge_ids

    matrix = np.full((len(judge_ids), len(findings)), np.nan, dtype=float)
    for col, finding in enumerate(findings):
        for row, jid in enumerate(judge_ids):
            v = finding.judge_scores.get(jid)
            if v is not None:
                try:
                    matrix[row, col] = float(v)
                except (TypeError, ValueError):
                    matrix[row, col] = np.nan
    return matrix, judge_ids


def _safe_alpha(matrix: np.ndarray | None) -> float | None:
    """Wrap :func:`krippendorff_alpha`; returns ``None`` on degenerate input."""
    if matrix is None or matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return None
    if np.all(np.isnan(matrix)):
        return None
    try:
        return krippendorff_alpha(matrix, level_of_measurement="interval")
    except Exception as exc:  # noqa: BLE001 — degenerate krippendorff input.
        logger.warning("Krippendorff α failed: %s", exc)
        return None


def _bucket_findings_by_stratum(
    findings: Sequence[Finding],
    axis: str,
) -> dict[str, list[Finding]]:
    """Group findings by their stratum value on one axis."""
    buckets: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        value = f.strata.get(axis, "__missing__")
        buckets[str(value)].append(f)
    return buckets


def _majority_stratum(buckets: Mapping[str, Sequence[Finding]]) -> str | None:
    """Return the stratum with the largest n; ``None`` if all empty."""
    if not buckets:
        return None
    return max(buckets.items(), key=lambda kv: len(kv[1]))[0]
def stratify(
    findings: Sequence[Finding],
    strata_config: Mapping[str, Any] | None = None,
) -> list[StratifiedReport]:
    """Per-(metric × model) stratification across all 8 equity axes.

    Parameters
    ----------
    findings:
        Iterable of :class:`Finding` rows.  Mixed metrics are fine; we
        partition on (metric, model_id) internally and emit one
        :class:`StratifiedReport` per partition.
    strata_config:
        Optional config block.  Recognised keys::

            {
                "axes":                 ["age_group", ...],   # subset of EQUITY_AXES
                "degradation_threshold": 0.10,                      # default 10 %
            }

        When omitted we use all 8 axes and the source-map locked 10 % flag.

    Returns
    -------
    list[StratifiedReport]
        One report per (metric × model_id), each carrying per-axis stratum
        stats and a flat list of flagged strata for the report's
        equity-section table.
    """
    cfg = dict(strata_config or {})
    axes: Sequence[str] = tuple(cfg.get("axes", EQUITY_AXES))
    threshold: float = float(cfg.get("degradation_threshold", DEFAULT_DEGRADATION_THRESHOLD))

    # Validate axis names so a typo in strata_config surfaces immediately
    # rather than silently emitting an empty section.
    unknown = [a for a in axes if a not in EQUITY_AXES]
    if unknown:
        raise ValueError(
            f"Unknown equity axis names {unknown}; valid axes are {EQUITY_AXES}"
        )

    # Partition by (metric, model_id) — the report consumes one block per
    # cell of that grid.
    by_partition: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        by_partition[(f.metric, f.model_id)].append(f)

    out: list[StratifiedReport] = []
    for (metric, model_id), part in sorted(by_partition.items()):
        report = StratifiedReport(metric=metric, model_id=model_id, n_total=len(part))

        for axis in axes:
            buckets = _bucket_findings_by_stratum(part, axis)
            if not buckets:
                report.axis_results[axis] = []
                continue

            majority_key = _majority_stratum(buckets)
            majority_mean = (
                float(np.mean([f.score for f in buckets[majority_key]]))
                if majority_key is not None and buckets[majority_key]
                else float("nan")
            )

            stratum_stats: list[StratumStats] = []
            for stratum_name, group in sorted(buckets.items()):
                if not group:
                    continue
                scores = np.array([g.score for g in group], dtype=float)
                mean = float(scores.mean())
                matrix, _ = _extract_judge_matrix(group)
                alpha = _safe_alpha(matrix)
                # Disparity ratio: 1.0 = parity, <1 = stratum behind majority.
                # Guard against divide-by-zero when majority mean is 0.
                if majority_mean == 0 or np.isnan(majority_mean):
                    disparity = float("nan")
                else:
                    disparity = mean / majority_mean
                gap = (majority_mean - mean) if not np.isnan(majority_mean) else float("nan")
                # Flag only NON-majority strata that fall >threshold below.
                flagged = (
                    stratum_name != majority_key
                    and not np.isnan(gap)
                    and gap > threshold
                )
                ss = StratumStats(
                    axis=axis,
                    stratum=stratum_name,
                    n=int(scores.size),
                    mean=mean,
                    krippendorff_alpha=alpha,
                    disparity_ratio=disparity,
                    absolute_gap_vs_majority=gap,
                    flagged=flagged,
                )
                stratum_stats.append(ss)
                if flagged:
                    report.flagged.append(ss)
            report.axis_results[axis] = stratum_stats

        out.append(report)
    return out


def stratified_reports_to_dicts(reports: Iterable[StratifiedReport]) -> list[dict[str, Any]]:
    """Serialiser for ``findings.json`` (data-spec contract)."""
    return [dataclasses.asdict(r) for r in reports]


__all__ = [
    "EQUITY_AXES",
    "DEFAULT_DEGRADATION_THRESHOLD",
    "Finding",
    "StratumStats",
    "StratifiedReport",
    "stratify",
    "stratified_reports_to_dicts",
]
