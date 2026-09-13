"""Pre-eval per-stratum sample-size justification.

Computes power-analytic detectability per equity stratum so that the
report explicitly flags strata where ``n`` is insufficient for inference
before the eval runs. Uses :func:`pingouin.power_ttest` (the v1.4
dependency in ``pyproject.toml``).

* 8 equity strata × n=60 prompts (EquityMedQA TRINDS Hindi) × 4 candidate
  models. Per-stratum effective n is roughly ``60 / 8 = 7.5`` if the
  prompts are uniformly distributed across axes — this is below most
  practical detection thresholds and *that's the point* of running this
  pre-eval rather than after.
* The results table reports detectable effect size at α=0.05,
  power=0.80 per stratum, with explicit flags for strata where the
  required-n exceeds the available-n.
* The limitations summary cites this analysis honestly: equity
  disparities reported here are *exploratory* on under-powered strata,
  with the audit caveats.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# pingouin is a v1.4 dependency in pyproject.toml; guarded import keeps
# the module loadable in environments where pingouin isn't yet
# installed (e.g. before ``uv sync``).
try:
    import pingouin as pg

    _PINGOUIN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PINGOUIN_AVAILABLE = False


def _detectable_d_fallback(n: int, alpha: float, target_power: float) -> float:
    """Closed-form Cohen's d approximation when pingouin isn't available.

    Uses the standard normal approximation
    ``d = (z_{1-α/2} + z_{1-β}) / sqrt(n / 2)`` for a two-sample t-test;
    accurate to ~5% at n ≥ 8.
    """
    # Inverse normal via rational approximation (Beasley-Springer-Moro
    # is overkill; scipy.stats.norm.ppf would be better but this module
    # already imports pingouin → scipy as the primary path).
    from math import erf, sqrt

    def _ppf(p: float) -> float:
        # Acklam's algorithm — sufficient for power-analysis precision.
        if p <= 0.0:
            return -math.inf
        if p >= 1.0:
            return math.inf
        # Symmetry: Φ⁻¹(p) = -Φ⁻¹(1 - p)
        sign = 1 if p >= 0.5 else -1
        q = p if p >= 0.5 else 1 - p
        # Rational approximation accurate to ~1e-3 for our use case.
        t = math.sqrt(-2 * math.log(1 - q))
        num = 2.515517 + 0.802853 * t + 0.010328 * t * t
        den = 1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t
        return sign * (t - num / den)

    z_alpha = _ppf(1 - alpha / 2)
    z_beta = _ppf(target_power)
    if n < 2:
        return math.inf
    return (z_alpha + z_beta) / math.sqrt(n / 2)


def _detectable_effect_size(
    n: int, alpha: float = 0.05, target_power: float = 0.8
) -> float:
    """Cohen's d detectable at the target power for a paired t-test.

    Production path uses ``pingouin.power_ttest`` (we own the dependency
    in pyproject.toml); fallback is the closed-form normal approximation.
    """
    if n < 2:
        return math.inf
    if _PINGOUIN_AVAILABLE:
        try:
            d = pg.power_ttest(
                n=n,
                power=target_power,
                alpha=alpha,
                contrast="paired",
                alternative="two-sided",
            )
            if d is not None and not math.isnan(d):
                return float(d)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("pingouin.power_ttest failed (%s); falling back", exc)
    return _detectable_d_fallback(n, alpha, target_power)


# Standard interpretation thresholds for Cohen's d (Cohen 1988).
_SMALL_D = 0.2
_MEDIUM_D = 0.5
_LARGE_D = 0.8


def _qualitative_label(d: float) -> str:
    if d <= _SMALL_D:
        return "small"
    if d <= _MEDIUM_D:
        return "medium"
    if d <= _LARGE_D:
        return "large"
    return "very-large-only"


def per_stratum_power(
    strata: dict[str, Any],
    n_per_stratum: dict[str, int],
    alpha: float = 0.05,
    target_power: float = 0.8,
) -> dict[str, dict[str, Any]]:
    """Compute per-stratum detectable effect size + sufficiency flag.

    Parameters
    ----------
    strata
        ``{axis_name: <metadata>}`` — typically the 8 equity axes. The
        metadata is currently unused but accepted for forward-compat
        (future versions may key off pre-registered MDE thresholds).
    n_per_stratum
        ``{axis_name: int}`` — observed sample size per axis. For the
        v1.4 baseline this is the EquityMedQA TRINDS Hindi prompt count
        (60 total) partitioned across the 8 axes.
    alpha
        Two-sided significance level. Default 0.05 per the per-stratum sample-size justification.
    target_power
        Desired statistical power. Default 0.80 per the per-stratum sample-size justification.

    Returns
    -------
    dict
        Per axis::

            {
                "n": int,
                "detectable_d": float,
                "label": "small|medium|large|very-large-only",
                "sufficient_for_medium_effects": bool,
                "alpha": 0.05,
                "target_power": 0.8,
            }

    The per-stratum sample-size results table reads this dict directly.
    The limitations summary cites the ``sufficient_for_medium_effects``
    flags honestly — under-powered strata are reported as
    *exploratory*.
    """
    out: dict[str, dict[str, Any]] = {}
    for axis in strata:
        n = int(n_per_stratum.get(axis, 0))
        d = _detectable_effect_size(n, alpha=alpha, target_power=target_power)
        out[axis] = {
            "n": n,
            "detectable_d": d,
            "label": _qualitative_label(d),
            "sufficient_for_medium_effects": d <= _MEDIUM_D,
            "alpha": alpha,
            "target_power": target_power,
        }
    return out


def required_n_for_effect(
    target_d: float = 0.5,
    alpha: float = 0.05,
    target_power: float = 0.8,
) -> int:
    """Inverse: minimum n to detect a Cohen's d at α/power.

    Useful for the power-analysis footnote — "to detect a medium effect (d=0.5)
    at α=0.05 / power=0.80 requires n≥X paired prompts per stratum".
    """
    if _PINGOUIN_AVAILABLE:
        try:
            n = pg.power_ttest(
                d=target_d,
                power=target_power,
                alpha=alpha,
                contrast="paired",
                alternative="two-sided",
            )
            if n is not None and not math.isnan(n):
                return int(math.ceil(float(n)))
        except Exception as exc:  # pragma: no cover
            logger.warning("pingouin inverse power failed (%s); falling back", exc)

    # Fallback: invert the normal approximation.
    # d = (z_α + z_β) / sqrt(n/2)  →  n = 2 ((z_α + z_β) / d)^2
    from math import sqrt

    def _ppf(p: float) -> float:
        sign = 1 if p >= 0.5 else -1
        q = p if p >= 0.5 else 1 - p
        t = math.sqrt(-2 * math.log(max(1e-12, 1 - q)))
        num = 2.515517 + 0.802853 * t + 0.010328 * t * t
        den = 1 + 1.432788 * t + 0.189269 * t * t + 0.001308 * t * t * t
        return sign * (t - num / den)

    z_alpha = _ppf(1 - alpha / 2)
    z_beta = _ppf(target_power)
    n = 2 * ((z_alpha + z_beta) / target_d) ** 2
    return int(math.ceil(n))
