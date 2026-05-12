"""Real-World Robustness audit page.

Shows per-prompt CeRAI score drift and MaaSwasth flag/jury-mean consistency across six
prose-level perturbations of the same factual content. Anchored on Eiras et al. (ICLR 2025
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
AUDIT_DOC = REPO_ROOT / "docs" / "perturbation_audit.md"


PERTURBATION_DEFINITIONS: dict[str, str] = {
    "original": "The unmodified sarvam-105b response under the MaaSwasth system prompt. The reference cell every perturbation is compared against.",
    "script_swap": "Hindi prose rewritten from Devanagari to Roman script (Hinglish-script). Mirrors the input-side variation documented in Khullar et al. (arXiv:2512.10780). Medical facts preserved exactly.",
    "code_mix": "Pure Hindi rewritten as natural Hinglish, mixing Hindi and English keywords the way real Indian ASHA workers and beneficiaries write. Same medical content.",
    "length_compress": "Full answer rewritten to an SMS-length 1-2 sentence message. Safety-critical facts preserved; politeness phrases dropped. Mirrors low-bandwidth phone behaviour.",
    "style_inflate": "Same content with a more confident/clinical register; may include citation-shaped phrases like '(WHO ANC 2016)'. No new medical facts. Eiras et al. (ICLR 2025) showed this kind of style shift moves LLM-as-judge scores up to 0.24 FNR.",
    "style_deflate": "Same content rewritten in a casual ASHA-worker register. Citations removed; doses/referrals/helplines preserved.",
    "authority_register": "Same content rewritten in an ASHA-training-manual voice (instructional, third-person, structured).",
}

VERIFIER_PASS_RATES: dict[str, str] = {
    "script_swap": "5/5",
    "code_mix": "5/5",
    "style_deflate": "4/5",
    "style_inflate": "3/5",
    "authority_register": "2/5",
    "length_compress": "1/5",
}


def _load_audit() -> dict | None:
    if not AUDIT_PATH.exists():
        return None
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def _load_perturbations() -> dict[tuple[str, str], dict]:
    if not PERT_PATH.exists():
        return {}
    out: dict[tuple[str, str], dict] = {}
    for line in PERT_PATH.open(encoding="utf-8"):
        rec = json.loads(line)
        out[(rec["prompt_id"], rec["perturbation_type"])] = rec
    return out


def _load_bases() -> dict[str, dict]:
    if not BASE_PATH.exists():
        return {}
    out = {}
    for line in BASE_PATH.open(encoding="utf-8"):
        rec = json.loads(line)
        out[rec["prompt_id"]] = rec
    return out


# === Page setup ===
st.set_page_config(page_title="Real-World Robustness", layout="wide")
st.title("Real-World Robustness Audit")

st.markdown(
    "**The question this page answers.** When the *same factual content* is delivered in the "
    "surface forms real Hindi mNH users actually produce — Devanagari ↔ Roman Hindi, Hinglish "
    "code-mix, SMS-length compression, register shifts — does each evaluator give consistent "
    "verdicts? A clinical reviewer cannot trust a 0.85 score if the same medical content scores "
    "0.50 under a different surface form. The target model is held fixed; the evaluator is the "
    "variable under test."
)

with st.container(border=True):
    st.markdown(
        "📚 **Methodology anchors** &nbsp;·&nbsp; "
        "[Eiras et al., ICLR 2025](https://proceedings.mlr.press/v296/eiras25a.html) — judge robustness "
        "meta-evaluation (style perturbation can shift LLM-as-judge FNR by 0.24) &nbsp;·&nbsp; "
        "[Khullar et al., arXiv:2512.10780](https://arxiv.org/abs/2512.10780) — Indian-language LLM "
        "medical-triage script-shift on the same content &nbsp;·&nbsp; "
        "[Flores et al. 2025](https://arxiv.org/abs/2506.14540) — asymmetric error costs in clinical AI "
        "&nbsp;·&nbsp; [WHO 2024](https://www.who.int/publications/i/item/9789240084759) — automation "
        "bias / large multi-modal model governance &nbsp;·&nbsp; "
        "[Hughes 2024](https://stagingpure.psu.edu/en/publications/toward-improved-inference-for-krippendorffs-alpha-agreement-coeff) — "
        "jackknife CI for Krippendorff α at small N."
    )

audit = _load_audit()
bases = _load_bases()
perts = _load_perturbations()

# === Headline section ===
st.divider()
st.subheader("Headline")

if audit is None:
    st.warning(
        "**Audit results not generated yet.** Run `scripts/score_perturbations_maaswasth.py` and "
        "`scripts/score_perturbations_cerai_dashboard.py`, then `scripts/compute_perturbation_robustness.py`. "
        "The audit JSON will materialise at `results/perturbation_audit.json` and this page will "
        "populate automatically."
    )
else:
    agg = audit["aggregate"]
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**CeRAI metric layer** (dashboard analyzer · `gemini-2.5-flash` judge · `llm_judge_positive` + `hallucination_haluqa`)")
        st.metric(
            "Mean score range per prompt",
            f"{agg['cerai']['mean_score_range']:.3f}",
            help=(
                "max(mean) − min(mean) across the 7 cells per prompt, averaged over 5 prompts. "
                "Higher = less robust. Bootstrap 95% CI: "
                f"[{agg['cerai']['score_range_bootstrap95_ci'][0]:.3f}, "
                f"{agg['cerai']['score_range_bootstrap95_ci'][1]:.3f}]"
            ),
        )
        alpha = agg["cerai"]["krippendorff_alpha"]
        st.metric(
            "Krippendorff α (interval)",
            f"{alpha['alpha']:.3f}",
            help=(
                "Across-cell stability per prompt. Closer to 1.0 = more stable; "
                "0.0 = random; negative = systematically inconsistent. "
                f"Jackknife 95% CI: [{alpha['ci_low']:.3f}, {alpha['ci_high']:.3f}]"
            ),
        )
        st.caption("Higher α = more stable. Higher score range = less stable.")

    with c2:
        st.markdown("**MaaSwasth panel** (claude-sonnet-4-6 + gemini-2.5-pro jury · `final_safety_method` calibration)")
        m = agg["maaswasth"]
        st.metric(
            "Prompts with identical `flagged` across all 7 cells",
            f"{m['fully_consistent_prompts']} / {m['n_prompts']}",
            help=(
                "How many of the 5 base prompts had the same flag (True/False) on every perturbation. "
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
        st.caption("Higher fully-consistent count = more stable flag.")

    st.info(
        "**How to read this.** Compare **CeRAI's score range** to **MaaSwasth's flag-consistency**. "
        "CeRAI emits a continuous score; the range tells you how much the same factual content "
        "swings purely from surface form. MaaSwasth emits a binary flag plus a jury_safety_mean; "
        "flag-consistency tells you whether the routing decision (HITL or not) survives surface change. "
        "This audit measures **stability**, not correctness."
    )

# === Honest caveats ===
st.divider()
st.subheader("What this audit does not claim")

st.markdown(
    "1. **Not an 'overall winner' claim.** MaaSwasth's flag is more stable on this set, but its "
    "specificity remains 0.15 — it over-flags safe cases. CeRAI is more balanced (specificity 0.60). "
    "The claim here is *MaaSwasth's chosen operating point is more stable under input variation*, not "
    "*MaaSwasth beats CeRAI*. See the canonical sens/spec table in the project README.\n"
    "2. **Asymmetric design.** We held the JSON triage block constant across perturbations; only the "
    "Hindi prose was changed. That isolates prose-form variation as the variable. CeRAI does not have "
    "a 'schema' so it sees prose drift only. Both evaluators score what they were designed to score.\n"
    "3. **20/30 perturbations preserved all medical facts on the final attempt.** Per-type pass rates: "
    f"`script_swap` {VERIFIER_PASS_RATES['script_swap']}, "
    f"`code_mix` {VERIFIER_PASS_RATES['code_mix']}, "
    f"`style_deflate` {VERIFIER_PASS_RATES['style_deflate']}, "
    f"`style_inflate` {VERIFIER_PASS_RATES['style_inflate']}, "
    f"`authority_register` {VERIFIER_PASS_RATES['authority_register']}, "
    f"`length_compress` {VERIFIER_PASS_RATES['length_compress']}. "
    "`length_compress` and `authority_register` systematically struggle to preserve clinical content "
    "under LLM-assisted generation — itself a notable finding about LLM-mediated content transformation "
    "in low-resource Hindi medical contexts.\n"
    "4. **N = 5 base responses.** Confidence intervals reported on this page are sample-level, not "
    "population-level. The point is to demonstrate the failure mode exists with literature-anchored "
    "precedent, not to estimate its rate across all Hindi mNH responses."
)

# === Perturbation type catalog ===
st.divider()
st.subheader("Perturbation types")
for ptype, definition in PERTURBATION_DEFINITIONS.items():
    if ptype == "original":
        continue
    pass_rate = VERIFIER_PASS_RATES.get(ptype, "n/a")
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"**`{ptype}`** — {definition}")
        c2.metric("Verifier pass rate", pass_rate)

# === Per-prompt breakdown ===
st.divider()
st.subheader("Per-prompt breakdown")
st.caption(
    "One expander per base prompt. Each row of the inner table is one cell (original + 6 perturbations). "
    "CeRAI `mean` = average of Accuracy + Relevance + Hallucination from the dashboard analyzer. "
    "MaaSwasth `flagged` is the binary HITL routing decision; `triage` is the calibrated band."
)

if audit is not None:
    for row in audit["per_prompt"]:
        title = (
            f"**{row['prompt_id']}** — CeRAI score range "
            f"`{row['cerai_score_range']:.2f}` · MaaSwasth flag-consistency "
            f"`{row['maaswasth_flag_consistency']:.2f}`"
        )
        with st.expander(title):
            base = bases.get(row["prompt_id"], {})
            if base:
                st.markdown(f"**User prompt:** {base.get('user_prompt', '')}")
                st.caption(f"`violation_expected={base.get('violation_expected')}` · "
                           f"urgency='{base.get('expected_urgency','')[:80]}…' · "
                           f"`base_source={base.get('base_source','')}`")
            cerai_scores = row.get("cerai_scores_by_perturbation", {})
            maas_flags = row.get("maaswasth_flags_by_perturbation", {})
            maas_triages = row.get("maaswasth_triages_by_perturbation", {})
            maas_means = row.get("maaswasth_means_by_perturbation", {})
            perts_order = list(cerai_scores.keys())
            df = pd.DataFrame({
                "perturbation": perts_order,
                "cerai_mean": [round(cerai_scores.get(p), 3) if cerai_scores.get(p) is not None else None for p in perts_order],
                "maas_jury_mean": [round(maas_means.get(p), 2) if maas_means.get(p) is not None else None for p in perts_order],
                "maas_flagged": [maas_flags.get(p) for p in perts_order],
                "maas_triage": [maas_triages.get(p) for p in perts_order],
            })
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Inspect-a-cell drill-down
            ptype_options = [p for p in perts_order if p != "original"]
            if ptype_options:
                picked = st.selectbox(
                    "Inspect a cell — see the original prose, the perturbed prose, and the verifier's facts list:",
                    options=ptype_options, key=f"inspect_{row['prompt_id']}",
                )
                pert_rec = perts.get((row["prompt_id"], picked))
                if pert_rec:
                    diff = pert_rec.get("factual_diff", {})
                    cA, cB = st.columns(2)
                    with cA:
                        st.markdown("**Original prose**")
                        st.code(base.get("base_response_prose", ""), language=None)
                    with cB:
                        st.markdown(f"**Perturbed prose · `{picked}`**")
                        st.code(pert_rec.get("perturbed_prose", ""), language=None)
                    st.caption(
                        f"verifier_pass=`{pert_rec.get('verifier_pass')}` · "
                        f"facts_preserved={len(diff.get('facts_preserved', []))} · "
                        f"facts_dropped={len(diff.get('facts_dropped', []))} · "
                        f"facts_added={len(diff.get('facts_added', []))} · "
                        f"generator=`{pert_rec.get('generator_model')}` · "
                        f"verifier=`{pert_rec.get('verifier_model')}`"
                    )
                    if diff.get("facts_dropped") or diff.get("facts_added"):
                        with st.expander("Verifier-detected fact drift"):
                            if diff.get("facts_dropped"):
                                st.markdown("**Facts dropped:**")
                                for f in diff["facts_dropped"]:
                                    st.markdown(f"- {f}")
                            if diff.get("facts_added"):
                                st.markdown("**Facts added:**")
                                for f in diff["facts_added"]:
                                    st.markdown(f"- {f}")

# === Where else to look ===
st.divider()
st.subheader("Where else to look")
st.markdown(
    "- **Full audit writeup with citations**: `docs/perturbation_audit.md`\n"
    "- **Raw scores**: `results/perturbation_scores_cerai.json`, `results/perturbation_scores_maaswasth.json`\n"
    "- **Audit aggregate (this page's source data)**: `results/perturbation_audit.json`\n"
    "- **Perturbation data + factual diffs**: `data/perturbations/perturbed_responses.jsonl`\n"
    "- **Canonical sens/spec table** (the other axis of comparison): see README §Evaluator Comparison Result\n"
    "- **Compute script**: `scripts/compute_perturbation_robustness.py`"
)

# === Full citations ===
with st.expander("Full references"):
    st.markdown(
        "1. **Eiras, F.; Zemour, E.; Lin, E.; Mugunthan, V. (2025).** *Know Thy Judge: On the "
        "Robustness Meta-Evaluation of LLM Safety Judges.* PMLR 296:56-66. "
        "<https://proceedings.mlr.press/v296/eiras25a.html>\n"
        "2. **Khullar, A. et al. (Dec 2025).** *Script Gap: Evaluating LLM Triage on Indian "
        "Languages in Native vs Roman Scripts.* arXiv:2512.10780.\n"
        "3. **Flores, G. A.; Smith, A. H.; Fukuyama, J. A.; Wilson, A. C. (2025).** *Aligning "
        "Evaluation with Clinical Priorities: Calibration, Label Shift, and Error Costs.* arXiv:2506.14540.\n"
        "4. **WHO (Jan 2024).** *Ethics and governance of AI for health: Guidance on large multi-modal "
        "models.* ISBN 978-92-4-008475-9.\n"
        "5. **Hughes, J. (2024).** *Toward improved inference for Krippendorff's Alpha agreement coefficient.* "
        "Pennsylvania State University.\n"
        "6. **Brown, L. D.; Cai, T. T.; DasGupta, A. (2001).** *Interval Estimation for a Binomial Proportion.* "
        "Statistical Science 16(2):101-133.\n"
        "7. **Ribeiro, M. T. et al. (2020).** *Beyond Accuracy: Behavioral Testing of NLP Models with "
        "CheckList.* ACL 2020."
    )
