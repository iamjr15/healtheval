"""Statistical layer for the MaaSwasth eval harness (statistical utilities and confidence-interval reporting).

This module is intentionally thin: it wraps four well-vetted libraries
(``scipy``, ``statsmodels``, ``krippendorff``, plus a closed-form
Beta-Binomial helper) behind a uniform return contract that always reports
``n`` explicitly, so every CI caption emitted into the report can show the
sample size it was computed on (the confidence-interval reporting contract binding).

The four primitives are:

* :func:`paired_bootstrap_ci`         — paired bootstrap 95% CI via
  ``scipy.stats.bootstrap`` (Miller 2024 *Adding Error Bars to Evals*,
  arXiv:2411.00640).
* :func:`krippendorff_alpha`          — Krippendorff's α via the maintained
  ``krippendorff`` package (NOT ``simpledorff`` — unmaintained since 2020).
* :func:`mcnemar_paired`              — McNemar's paired-difference test via
  ``statsmodels.stats.contingency_tables.mcnemar``.
* :func:`beta_binomial_credible_interval`
                                       — closed-form Beta-Binomial
  conjugate-prior credible interval (Qu et al. *BetaConform*, NeurIPS 2025
  — provably tighter than bootstrap on n<50).

``power_estimate`` lives in :mod:`eval.power_analysis` (owned by
``eval-integ``); it is intentionally NOT re-exported here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
# Public return shape — every CI we emit carries ``n`` so the report caption
# generator can always fill in "(n=…)" without round-tripping through the
# caller.  Migrates to the data-spec Pydantic ``CIReport`` when it lands.
@dataclass(frozen=True)
class CIReport:
    """Lightweight return-type for any function that emits a CI.

    Attributes
    ----------
    point:
        Point estimate (mean / proportion / MAP).
    ci_low, ci_high:
        Lower and upper bound of the credible / confidence interval.
    n:
        Sample size the CI was computed on.  the confidence-interval reporting contract mandates this
        always be reported with the interval.
    method:
        Free-text method tag (e.g. ``"paired-bootstrap"``,
        ``"beta-binomial-MAP"``) for downstream report captions.
    """

    point: float
    ci_low: float
    ci_high: float
    n: int
    method: str
# 1. Paired bootstrap 95% CI (Miller 2024)
def paired_bootstrap_ci(
    scores: np.ndarray | Sequence[float],
    n_resamples: int = 10_000,
    confidence_level: float = 0.95,
    random_state: int | None = 1729,  # locked for reproducibility (the reproducibility gate)
) -> CIReport:
    """Paired bootstrap CI for a vector of paired per-prompt scores.

    Uses :func:`scipy.stats.bootstrap` with method ``"BCa"`` (bias-corrected
    accelerated) which is the Miller 2024 recommendation for small-to-medium
    n typical of MaaSwasth (n=30 reference set, n=60 equity subset).

    Parameters
    ----------
    scores:
        1-D array of paired score deltas or per-prompt scores.  For a
        head-to-head paired test pass ``scores_a - scores_b``.
    n_resamples:
        Number of bootstrap resamples.  10,000 is the Miller 2024 default
        and is cheap (<1 s for n≤200).
    confidence_level:
        Two-sided coverage; default 95 %.
    random_state:
        Seeded for reproducibility (the reproducibility gate mandates that every CI be
        reproducible bit-for-bit from the locked seed).

    Returns
    -------
    CIReport
        With ``method="paired-bootstrap-BCa"``.
    """
    arr = np.asarray(scores, dtype=float)
    if arr.ndim != 1:
        raise ValueError("paired_bootstrap_ci expects a 1-D vector of paired scores")
    n = int(arr.size)
    if n < 2:
        # Degenerate: a single sample has no bootstrap variance.  Return the
        # point estimate with a zero-width interval and surface n=… so the
        # report caption is still correct.
        point = float(arr.mean()) if n == 1 else float("nan")
        return CIReport(point, point, point, n, "paired-bootstrap-degenerate")

    # Lazy import keeps module-level import-cost low for callers that only
    # need (e.g.) the Krippendorff helper.
    from scipy import stats as _sp_stats

    res = _sp_stats.bootstrap(
        (arr,),
        statistic=np.mean,
        n_resamples=n_resamples,
        confidence_level=confidence_level,
        method="BCa",
        random_state=random_state,
        vectorized=True,
    )
    return CIReport(
        point=float(arr.mean()),
        ci_low=float(res.confidence_interval.low),
        ci_high=float(res.confidence_interval.high),
        n=n,
        method=f"paired-bootstrap-BCa-{int(confidence_level * 100)}",
    )
# 2. Krippendorff's α — inter-judge reliability (the judge-panel contract)
def krippendorff_alpha(
    reliability_data: np.ndarray | Sequence[Sequence[float]],
    level_of_measurement: str = "interval",
) -> float:
    """Krippendorff's α over a (judges × prompts) reliability matrix.

    The ``krippendorff`` package is the maintained successor to
    ``simpledorff`` (which has had no commits since 2020 and is missing the
    nominal/ordinal variance fixes).  Missing scores must be encoded as
    ``np.nan`` — the matrix is *judges × items*, with one row per judge.

    Parameters
    ----------
    reliability_data:
        2-D array, rows = judges, cols = items.  Use ``np.nan`` for the
        Sarvam-105b judge slot when self-judging avoidance drops it for a
        Sarvam-105b panel response (the judge-panel contract).
    level_of_measurement:
        ``"nominal"`` / ``"ordinal"`` / ``"interval"`` / ``"ratio"``.
        Default ``"interval"`` matches the 0-1 axis scoring used by the
        Constitutional MNH rubric.

    Returns
    -------
    float
        α ∈ [-1, 1].  Values < 0.6 should be flagged as judge-disagreement
        zones per the judge-panel contract.
    """
    arr = np.asarray(reliability_data, dtype=float)
    if arr.ndim != 2:
        raise ValueError(
            "krippendorff_alpha expects a 2-D (judges × items) matrix; "
            f"got shape {arr.shape}"
        )

    import krippendorff as _krip  # lazy to keep cold-import cheap

    return float(
        _krip.alpha(
            reliability_data=arr,
            level_of_measurement=level_of_measurement,
        )
    )
# 3. McNemar paired test — head-to-head model A vs B disagreement
def mcnemar_paired(
    table: np.ndarray | Sequence[Sequence[int]],
    exact: bool | None = None,
    correction: bool = True,
) -> tuple[float, float]:
    """McNemar's paired-difference test for binary head-to-head outcomes.

    The 2×2 contingency table is laid out as::

        [[A_correct & B_correct,  A_correct & B_wrong  ],
         [A_wrong  & B_correct,  A_wrong  & B_wrong  ]]

    The off-diagonal cells (b, c) are the discordant pairs the test
    actually inspects.

    Parameters
    ----------
    table:
        A 2×2 array of paired counts.
    exact:
        ``True`` forces the binomial exact test (recommended when the
        smaller off-diagonal count is ≤ 25).  ``None`` lets statsmodels
        auto-pick.
    correction:
        Apply continuity correction (default ``True``).

    Returns
    -------
    tuple[float, float]
        ``(statistic, p_value)``.  Use the p-value to gate any "model A
        beats model B" claim in the report (the statistical-rigor contract statistical-rigor
        bar).
    """
    arr = np.asarray(table, dtype=int)
    if arr.shape != (2, 2):
        raise ValueError(
            f"mcnemar_paired expects a 2x2 contingency table; got {arr.shape}"
        )

    from statsmodels.stats.contingency_tables import mcnemar as _mcnemar

    # statsmodels picks exact=True automatically when the smaller
    # off-diagonal count is small if exact is left as None.
    result = _mcnemar(arr, exact=exact if exact is not None else True, correction=correction)
    return float(result.statistic), float(result.pvalue)
# 4. Beta-Binomial conjugate-prior credible interval (Qu NeurIPS 2025)
def beta_binomial_credible_interval(
    successes: int,
    trials: int,
    alpha_prior: float = 1.0,
    beta_prior: float = 1.0,
    ci: float = 0.95,
) -> CIReport:
    """Closed-form Beta-Binomial conjugate-prior credible interval.

    Posterior is ``Beta(α + successes, β + trials − successes)``; the
    credible interval is the equal-tailed interval of that posterior.  Per
    Qu et al. *BetaConform* (NeurIPS 2025, OpenReview SsHCyEBMLz), this is
    provably tighter than the paired bootstrap for n<50, which is exactly
    the n=30 reference-set and n=20 minimum-viable regime MaaSwasth ships
    in (the confidence-interval reporting contract).

    Parameters
    ----------
    successes:
        Number of successes (e.g. prompts where the model answered
        correctly).  Must satisfy ``0 ≤ successes ≤ trials``.
    trials:
        Total number of trials (n).
    alpha_prior, beta_prior:
        Beta prior hyperparameters; ``(1, 1)`` is the uniform Jeffreys-ish
        default.  the confidence-interval reporting contract supports prior transfer from upstream
        evals — pass them in here.
    ci:
        Credible-interval coverage (default 0.95).

    Returns
    -------
    CIReport
        ``point`` is the posterior MAP (mode), with the equal-tailed
        credible interval; ``method="beta-binomial-MAP"``.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not (0 <= successes <= trials):
        raise ValueError(f"successes must lie in [0, trials]; got {successes}/{trials}")
    if not (0 < ci < 1):
        raise ValueError("ci must lie in (0, 1)")

    from scipy import stats as _sp_stats

    a = alpha_prior + successes
    b = beta_prior + (trials - successes)

    lo = float(_sp_stats.beta.ppf((1 - ci) / 2, a, b))
    hi = float(_sp_stats.beta.ppf(1 - (1 - ci) / 2, a, b))

    # MAP of Beta(a, b) when both > 1 is (a-1)/(a+b-2); fall back to the
    # posterior mean when the mode is undefined (a≤1 or b≤1).
    if a > 1 and b > 1:
        point = (a - 1.0) / (a + b - 2.0)
    else:
        point = a / (a + b)

    return CIReport(
        point=float(point),
        ci_low=lo,
        ci_high=hi,
        n=int(trials),
        method=f"beta-binomial-MAP-{int(ci * 100)}",
    )


__all__ = [
    "CIReport",
    "paired_bootstrap_ci",
    "krippendorff_alpha",
    "mcnemar_paired",
    "beta_binomial_credible_interval",
]
