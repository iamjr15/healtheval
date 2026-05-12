"""Real-World Robustness audit page.

Shows per-prompt CeRAI score drift and MaaSwasth flag/jury-mean consistency across six
prose-level perturbations of the same factual content. Anchors to Eiras et al. (ICLR 2025
Workshops) and Khullar et al. (arXiv:2512.10780, Dec 2025).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "results" / "perturbation_audit.json"
MAAS_PATH = REPO_ROOT / "results" / "perturbation_scores_maaswasth.json"
CERAI_PATH = REPO_ROOT / "results" / "perturbation_scores_cerai.json"
PERT_PATH = REPO_ROOT / "data" / "perturbations" / "perturbed_responses.jsonl"
BASE_PATH = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"

st.set_page_config(page_title="Real-World Robustness", layout="wide")
st.title("Real-World Robustness Audit")

st.markdown(
    "Same factual content delivered six ways — script swap, Hinglish code-mix, length compression, "
    "stylistic inflation/deflation, authority register — exactly the variation real Hindi mNH users produce. "
    "We measure each evaluator's stability under those perturbations. Methodology: Eiras et al. "
    "(ICLR 2025), Khullar et al. (arXiv:2512.10780, Dec 2025); CeRAI scores produced by the "
    "CeRAI dashboard analyzer (DeepEval `llm_judge_positive` / `hallucination_haluqa`)."
)

if not AUDIT_PATH.exists():
    st.warning(
        f"`{AUDIT_PATH.relative_to(REPO_ROOT)}` does not exist yet. "
        "Run `scripts/compute_perturbation_robustness.py` after both scoring scripts complete."
    )
    st.stop()

audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
agg = audit["aggregate"]

c1, c2 = st.columns(2)

with c1:
    st.subheader("CeRAI score drift")
    st.metric(
        "Mean score range per prompt (max − min across 7 cells)",
        f"{agg['cerai']['mean_score_range']:.3f}",
        help=(
            "Bootstrap 95% CI: "
            f"[{agg['cerai']['score_range_bootstrap95_ci'][0]:.3f}, "
            f"{agg['cerai']['score_range_bootstrap95_ci'][1]:.3f}]"
        ),
    )
    alpha = agg["cerai"]["krippendorff_alpha"]
    st.metric(
        "Krippendorff α (interval, across-cell stability)",
        f"{alpha['alpha']:.3f}",
        help=f"Jackknife 95% CI: [{alpha['ci_low']:.3f}, {alpha['ci_high']:.3f}]",
    )

with c2:
    st.subheader("MaaSwasth flag consistency")
    m = agg["maaswasth"]
    st.metric(
        "Prompts with identical flag across all 7 cells",
        f"{m['fully_consistent_prompts']} / {m['n_prompts']}",
        help=(
            "Wilson 95% CI on proportion: "
            f"[{m['flag_consistency_wilson95_ci'][0]:.3f}, "
            f"{m['flag_consistency_wilson95_ci'][1]:.3f}]"
        ),
    )
    st.metric("Mean flag consistency", f"{m['mean_flag_consistency']:.3f}")
    if m.get("jury_mean_krippendorff_alpha"):
        ja = m["jury_mean_krippendorff_alpha"]
        st.metric(
            "Krippendorff α on jury_safety_mean",
            f"{ja['alpha']:.3f}",
            help=f"Jackknife 95% CI: [{ja['ci_low']:.3f}, {ja['ci_high']:.3f}]",
        )

st.divider()
st.subheader("Per-prompt breakdown")
st.caption(
    "Each row of the inner table is one perturbation cell. CeRAI mean is the average of "
    "Accuracy/Relevance/Hallucination from the analyzer. MaaSwasth fields come from the jury panel."
)

for row in audit["per_prompt"]:
    title = (
        f"{row['prompt_id']} — CeRAI range {row['cerai_score_range']:.2f}, "
        f"MaaSwasth flag-consistency {row['maaswasth_flag_consistency']:.2f}"
    )
    with st.expander(title):
        cerai_scores = row.get("cerai_scores_by_perturbation", {})
        maas_flags = row.get("maaswasth_flags_by_perturbation", {})
        maas_triages = row.get("maaswasth_triages_by_perturbation", {})
        maas_means = row.get("maaswasth_means_by_perturbation", {})
        perts = list(cerai_scores.keys())
        df = pd.DataFrame({
            "perturbation": perts,
            "cerai_mean": [cerai_scores.get(p) for p in perts],
            "maaswasth_jury_mean": [maas_means.get(p) for p in perts],
            "maaswasth_flagged": [maas_flags.get(p) for p in perts],
            "maaswasth_triage": [maas_triages.get(p) for p in perts],
        })
        st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
with st.expander("Methodology"):
    st.markdown(
        "**Why this exists.** Headline scores from any evaluator can converge on the surface while "
        "masking very different operating characteristics. A reviewer cannot interpret a 0.85 vs 0.98 "
        "number without knowing whether either is robust to the kind of variation real users actually "
        "produce.\n\n"
        "**What we did.** Held factual content constant. For 5 base responses (mix of safe-routine, "
        "unsafe-but-correctly-refused, and one partial-failure case), we generated 6 perturbations each "
        "— script swap, Hinglish code-mix, length compression, stylistic inflation, stylistic deflation, "
        "authority register. An independent verifier (Gemini 2.5 Pro) flagged any cell where the "
        "perturbation dropped or added a medical fact. Both tools score all 35 cells.\n\n"
        "**What this is not.** A target-model comparison. The target model is held fixed. The evaluator "
        "is the variable under test."
    )

with st.expander("References"):
    st.markdown(
        "1. Eiras, F. et al. (2025). *Know Thy Judge: On the Robustness Meta-Evaluation of LLM Safety "
        "Judges*. PMLR 296:56-66.\n"
        "2. Khullar, A. et al. (Dec 2025). *Script Gap: Evaluating LLM Triage on Indian Languages in "
        "Native vs Roman Scripts*. arXiv:2512.10780.\n"
        "3. Flores, G. A. et al. (2025). *Aligning Evaluation with Clinical Priorities: Calibration, "
        "Label Shift, and Error Costs*. arXiv:2506.14540.\n"
        "4. WHO (Jan 2024). *Ethics and governance of AI for health: Guidance on large multi-modal "
        "models*. ISBN 978-92-4-008475-9.\n"
        "5. Hughes, J. (2024). *Toward improved inference for Krippendorff's Alpha agreement coefficient*."
    )
