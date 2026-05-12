"""Compute robustness metrics across perturbed cells for both evaluators.

Per-prompt metrics:
* `cerai_score_range`  — max(mean) - min(mean) across the 7 cells (original + 6 perturbed)
* `cerai_score_std`    — standard deviation of the means
* `maaswasth_flag_consistency`   — fraction of cells with the same `flagged` as original
* `maaswasth_triage_consistency` — fraction of cells with the same triage label as original

Aggregate:
* Mean per-prompt CeRAI score range with bootstrap 95% CI (B=10000)
* Mean MaaSwasth flag-consistency with Wilson 95% CI for the proportion of
  fully-consistent prompts (consistency == 1.0)
* Krippendorff's alpha (interval) with jackknife 95% CI for each tool's stability
  across perturbation cells (Hughes 2024)
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import numpy as np
import scipy.stats as st

REPO_ROOT = Path(__file__).resolve().parents[1]
CERAI = REPO_ROOT / "results" / "perturbation_scores_cerai.json"
MAAS = REPO_ROOT / "results" / "perturbation_scores_maaswasth.json"
OUT = REPO_ROOT / "results" / "perturbation_audit.json"


def _wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    z = st.norm.ppf(1 - alpha / 2)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _bootstrap_ci(values: list[float], B: int = 10000, alpha: float = 0.05) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = np.random.default_rng(seed=42)
    arr = np.array(values, dtype=float)
    samples = rng.choice(arr, size=(B, len(arr)), replace=True).mean(axis=1)
    return (float(np.quantile(samples, alpha / 2)), float(np.quantile(samples, 1 - alpha / 2)))


def _alpha_interval(units: list[list[float]]) -> float:
    """Krippendorff's alpha (interval level) on `units[i] = ratings for unit i`.

    Treats each unit as having multiple "ratings" (here: scores across perturbations
    of the same factual content). Higher alpha = more agreement / more stability.
    """
    all_pairs_de = 0.0
    n_pairs = 0
    for u in units:
        for i in range(len(u)):
            for j in range(i + 1, len(u)):
                all_pairs_de += (u[i] - u[j]) ** 2
                n_pairs += 1
    if n_pairs == 0:
        return 1.0
    observed = all_pairs_de / n_pairs
    flat = [v for u in units for v in u]
    expected_pairs_de = 0.0
    n_e = 0
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            expected_pairs_de += (flat[i] - flat[j]) ** 2
            n_e += 1
    if n_e == 0 or expected_pairs_de == 0:
        return 1.0
    expected = expected_pairs_de / n_e
    return 1.0 - observed / expected


def _krippendorff_jackknife(units: list[list[float]]) -> dict[str, float]:
    a0 = _alpha_interval(units)
    if len(units) < 2:
        return {"alpha": a0, "ci_low": a0, "ci_high": a0}
    pseudovals = []
    n = len(units)
    for k in range(n):
        loo = units[:k] + units[k + 1:]
        a_k = _alpha_interval(loo)
        pseudovals.append(n * a0 - (n - 1) * a_k)
    mean = statistics.mean(pseudovals)
    sd = statistics.stdev(pseudovals) / math.sqrt(n)
    z = 1.96
    return {"alpha": a0, "ci_low": mean - z * sd, "ci_high": mean + z * sd, "n_pseudovals": n}


def _load(p: Path) -> dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    if not CERAI.exists() or not MAAS.exists():
        print("Both scoring artifacts must exist. Run score_perturbations_*.py first.", file=sys.stderr)
        return 1

    cerai = _load(CERAI)
    maas = _load(MAAS)

    by_prompt_cerai: dict[str, dict[str, float]] = {}
    for c in cerai["cells"]:
        by_prompt_cerai.setdefault(c["prompt_id"], {})[c["perturbation_type"]] = c["mean"]

    by_prompt_maas_flag: dict[str, dict[str, bool]] = {}
    by_prompt_maas_triage: dict[str, dict[str, str]] = {}
    by_prompt_maas_mean: dict[str, dict[str, float]] = {}
    for c in maas["cells"]:
        by_prompt_maas_flag.setdefault(c["prompt_id"], {})[c["perturbation_type"]] = bool(c.get("flagged"))
        by_prompt_maas_triage.setdefault(c["prompt_id"], {})[c["perturbation_type"]] = str(c.get("triage_label") or "")
        if c.get("jury_safety_mean") is not None:
            by_prompt_maas_mean.setdefault(c["prompt_id"], {})[c["perturbation_type"]] = float(c["jury_safety_mean"])

    per_prompt: list[dict[str, Any]] = []
    cerai_ranges: list[float] = []
    maas_flag_consistencies: list[float] = []
    cerai_units_for_alpha: list[list[float]] = []
    maas_units_for_alpha: list[list[float]] = []

    for pid in sorted(by_prompt_cerai):
        cerai_scores = list(by_prompt_cerai[pid].values())
        cerai_range = max(cerai_scores) - min(cerai_scores)
        cerai_std = statistics.stdev(cerai_scores) if len(cerai_scores) > 1 else 0.0
        cerai_units_for_alpha.append(cerai_scores)
        cerai_ranges.append(cerai_range)

        flags = by_prompt_maas_flag.get(pid, {})
        triages = by_prompt_maas_triage.get(pid, {})
        means_by_p = by_prompt_maas_mean.get(pid, {})

        orig_flag = flags.get("original")
        orig_triage = triages.get("original")
        flag_match = sum(1 for v in flags.values() if v == orig_flag) / max(1, len(flags))
        triage_match = sum(1 for v in triages.values() if v == orig_triage) / max(1, len(triages))
        maas_flag_consistencies.append(flag_match)
        if means_by_p:
            maas_units_for_alpha.append(list(means_by_p.values()))

        per_prompt.append({
            "prompt_id": pid,
            "cerai_score_range": cerai_range,
            "cerai_score_std": cerai_std,
            "cerai_scores_by_perturbation": by_prompt_cerai[pid],
            "maaswasth_flag_consistency": flag_match,
            "maaswasth_triage_consistency": triage_match,
            "maaswasth_flags_by_perturbation": flags,
            "maaswasth_triages_by_perturbation": triages,
            "maaswasth_means_by_perturbation": means_by_p,
        })

    cerai_range_ci = _bootstrap_ci(cerai_ranges)
    fully_consistent = sum(1 for v in maas_flag_consistencies if v == 1.0)
    maas_flag_wilson = _wilson_ci(fully_consistent, len(maas_flag_consistencies))
    cerai_alpha = _krippendorff_jackknife(cerai_units_for_alpha)
    maas_alpha = _krippendorff_jackknife(maas_units_for_alpha) if maas_units_for_alpha else None

    aggregate = {
        "cerai": {
            "mean_score_range": statistics.mean(cerai_ranges) if cerai_ranges else 0.0,
            "score_range_bootstrap95_ci": cerai_range_ci,
            "krippendorff_alpha": cerai_alpha,
            "interpretation": (
                "score_range = max(mean) - min(mean) per prompt across 7 perturbation cells. "
                "Higher = less robust to surface-form variation of identical factual content. "
                "Krippendorff alpha is internal consistency across cells per prompt."
            ),
        },
        "maaswasth": {
            "n_prompts": len(maas_flag_consistencies),
            "fully_consistent_prompts": fully_consistent,
            "flag_consistency_wilson95_ci": maas_flag_wilson,
            "mean_flag_consistency": statistics.mean(maas_flag_consistencies) if maas_flag_consistencies else 0.0,
            "jury_mean_krippendorff_alpha": maas_alpha,
            "interpretation": (
                "fully_consistent_prompts = prompts where the binary `flagged` is the same across all "
                "7 cells. Wilson CI is on that proportion. Krippendorff alpha (interval) is on the "
                "jury_safety_mean values across cells."
            ),
        },
        "literature_anchors": {
            "Eiras_2025": "Documents LLM safety judges can shift up to 0.24 in FNR on style perturbation alone (PMLR 296:56-66).",
            "Khullar_2025": "Documents script-shift on Indian-language LLM medical triage produces inconsistent outputs (arXiv:2512.10780).",
            "Flores_2025": "Justifies the asymmetric-loss frame: missed safety > false-positive in MNH (arXiv:2506.14540).",
            "Hughes_2024": "Jackknife CI for Krippendorff alpha at small N.",
        },
    }

    OUT.write_text(
        json.dumps({"per_prompt": per_prompt, "aggregate": aggregate}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(aggregate, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
