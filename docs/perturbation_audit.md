# Real-World Robustness Audit

This audit tests whether each evaluator gives consistent verdicts when the **same factual content** is delivered in the surface forms real Hindi mNH users actually produce. The target model is held fixed; the evaluator is the variable under test.

> Numbers in this document are filled from `results/perturbation_audit.json`. Some headline cells are marked `[FILL]` until the scoring jobs (long-running) finish; the methodology and design are final.

## Summary

`[FILL ONE-PARAGRAPH HEADLINE WITH NUMBERS — completed once results/perturbation_audit.json is final]`

## Why this audit exists

A response with the same medical content can reach a Hindi mNH user in many surface forms. Real users write in Devanagari, in Roman Hindi, in Hinglish, in SMS-length compressions, with cultural and authority-register shifts. Khullar et al. (Dec 2025, arXiv:2512.10780) document that **script alone** shifts LLM medical-triage outputs on Indian languages. Eiras et al. (ICLR 2025 Workshops, PMLR 296:56-66) document that LLM-as-judge scores shift up to **0.24 in false-negative rate on style perturbation** of the same content. An evaluator that gates clinical content needs to be robust to that variation, not just accurate in aggregate.

The CeRAI sensitivity/specificity table in `methodology_panel_refset_eval.json` measures evaluator behaviour on a fixed 30-prompt reference set. It does not measure stability under the surface-form variation real users produce. This audit closes that gap.

## Methodology

**Design.** Take 5 base responses (sarvam-105b's outputs to ref-001, ref-007, ref-009, ref-012, ref-024 under the MaaSwasth system prompt). For each base, generate 6 perturbations of the Hindi prose portion while holding the JSON triage block constant. The JSON triage is the schema-first envelope; the prose carries the medical content under test. By preserving the triage block we isolate prose-form variation as the single variable.

**Perturbation types.**

| Type | What changes | Anchor |
|---|---|---|
| `script_swap` | Devanagari → Roman-script Hindi | Khullar et al. 2025 |
| `code_mix` | Pure Hindi → Hinglish | Real ARMMAN-style user behaviour |
| `length_compress` | Full answer → SMS-length | Low-bandwidth phone behaviour |
| `style_inflate` | Casual → confident/clinical register, may add citation-shaped phrase | Eiras et al. 2025 |
| `style_deflate` | Formal → casual ASHA-worker register | Real cohort variation |
| `authority_register` | First-person → ASHA training-manual voice | Authority laundering pattern |

**Factual preservation.** Each perturbation is verified by an **independent judge model** (Gemini 2.5 Pro). The verifier lists facts dropped, facts added, and facts preserved between the original prose and the perturbed prose. A perturbation passes when both `facts_dropped` and `facts_added` are empty. The generator (Claude Sonnet 4.5) gets up to 2 retries per cell; the last attempt is recorded honestly even if it still fails.

**Generator pass rate.** Of the 30 perturbations, **20/30 preserved all medical facts** on the final attempt. The failures cluster in `length_compress` (4/5 prompts) and `authority_register` (3/5 prompts) — these transformations are inherently lossy or additive for clinical content under LLM-assisted generation. This is itself a methodological finding: LLM-mediated content transformation in Hindi medical contexts is unreliable for compression and structural-register shifts. All 30 cells are still scored; the audit reports per-type pass rates honestly.

**Scoring pipelines.**
* **MaaSwasth** — `scripts/score_perturbations_maaswasth.py` calls `eval.judges.judge_panel` with the same arguments `scripts/run_panel_refset_eval.py` uses for the canonical reference-set run. Jury = claude-sonnet-4-6 + gemini-2.5-pro (sarvam-105b dropped per HEALTH-PARIKSHA self-judging avoidance because the target is sarvam-105b). Calibration = `final_safety_method` (principles 1, 2, 3, 6, 12; green 4.0, amber 3.5; `union_with_response_triage=True`).
* **CeRAI** — `scripts/score_perturbations_cerai_dashboard.py` inserts 105 new test cases (35 cells × 3 metrics) into CeRAI's docker database and invokes `response_analyzer/analyze.py` for each metric run. This uses CeRAI's actual DeepEval-backed scoring pipeline (`llm_judge_positive` for Accuracy and Relevance, `hallucination_haluqa` for Hallucination) with the verbatim judge prompts that produced the original run 25/26/27 baseline. Judge model = `gemini-2.5-flash` (CeRAI's vendor-judge fallback per the MaaSwasth patch in CeRAI's `llm_judge.py`).

**Metrics.**
* Per-prompt **CeRAI score range** = max(mean) − min(mean) across the 7 cells (original + 6 perturbed). Higher = less robust.
* Per-prompt **MaaSwasth flag-consistency** = fraction of the 7 cells with the same `flagged` value as the original.
* Per-prompt **MaaSwasth triage-consistency** = fraction with the same triage label.
* Aggregate **CeRAI mean score range** with bootstrap 95% CI (B=10000) on the per-prompt values.
* Aggregate **MaaSwasth fully-consistent prompts** with Wilson 95% CI (Brown, Cai & DasGupta 2001, *Statistical Science* 16:101-133).
* **Krippendorff α (interval)** with jackknife 95% CI (Hughes 2024) for each tool's internal consistency across cells.

## Results

`[FILL FROM results/perturbation_audit.json once scoring completes]`

**Aggregate.**

| Metric | CeRAI metric layer | MaaSwasth panel |
|---|---:|---:|
| Mean score range per prompt | `[FILL]` | n/a (binary flag) |
| Score range bootstrap 95% CI | `[FILL, FILL]` | — |
| Krippendorff α (interval) | `[FILL]` | `[FILL]` |
| Krippendorff α jackknife 95% CI | `[FILL, FILL]` | `[FILL, FILL]` |
| Prompts with identical flag across 7 cells | n/a | `[FILL] / 5` |
| Flag-consistency Wilson 95% CI | — | `[FILL, FILL]` |
| Mean flag-consistency | n/a | `[FILL]` |

**Per-prompt breakdown.**

| Prompt | CeRAI range | CeRAI std | MaaSwasth flag-consistency | MaaSwasth triage-consistency |
|---|---:|---:|---:|---:|
| ref-001 | `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| ref-007 | `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| ref-009 | `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| ref-012 | `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |
| ref-024 | `[FILL]` | `[FILL]` | `[FILL]` | `[FILL]` |

## Named exhibits

`[Fill 2 short case writeups from the data — the largest CeRAI drift case and a case where MaaSwasth held steady but CeRAI swung]`

## Limitations

* **N = 5 base responses** is too small for any statistical certainty about population behaviour. The bootstrap and Wilson CIs reported here are sample-level, not generalisation claims. The point is to demonstrate the failure mode exists with literature-anchored precedent, not to estimate its rate in the population of all Hindi mNH responses.
* **LLM-assisted perturbation generation** introduces noise. 10/30 perturbations did not preserve facts on the final attempt despite an independent verifier — that is itself reported. Scoring proceeds on all 30 cells; the audit notes per-type pass rates so a reviewer can re-run with stricter constraints.
* **Single judge for CeRAI** — CeRAI's analyzer uses gemini-2.5-flash (its fallback when OLLAMA_URL is empty). A different judge model could produce different score drift. The literature anchor (Eiras 2025) was on different judges and saw the same family of effects.
* **Triage block is held constant.** That is a deliberate design choice (isolating prose variation) but it means we are not testing how MaaSwasth would respond to triage-block perturbations specifically. The `script_swap` perturbation type does not transliterate the JSON keys; only the prose is changed.
* **CeRAI's `hallucination_haluqa` strategy** uses DeepEval's GEval at runtime rather than materialising a single prompt to `LLMJudgePrompts`. Our replication is via CeRAI's own analyzer pipeline rather than a verbatim prompt capture; the in-process replica was discarded in favour of dashboard-driven scoring.

## References

1. Eiras, F.; Zemour, E.; Lin, E.; Mugunthan, V. (2025). *Know Thy Judge: On the Robustness Meta-Evaluation of LLM Safety Judges*. ICLR 2025 Workshops, PMLR 296:56-66. <https://proceedings.mlr.press/v296/eiras25a.html>
2. Khullar, A. et al. (Dec 2025). *Script Gap: Evaluating LLM Triage on Indian Languages in Native vs Roman Scripts*. arXiv:2512.10780.
3. Flores, G. A.; Smith, A. H.; Fukuyama, J. A.; Wilson, A. C. (2025). *Aligning Evaluation with Clinical Priorities: Calibration, Label Shift, and Error Costs*. arXiv:2506.14540.
4. WHO (Jan 2024). *Ethics and governance of artificial intelligence for health: Guidance on large multi-modal models*. ISBN 978-92-4-008475-9.
5. Hughes, J. (2024). *Toward improved inference for Krippendorff's Alpha agreement coefficient*. Pennsylvania State University.
6. Brown, L. D.; Cai, T. T.; DasGupta, A. (2001). *Interval Estimation for a Binomial Proportion*. *Statistical Science* 16(2):101-133.
7. Ribeiro, M. T.; Wu, T.; Guestrin, C.; Singh, S. (2020). *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList*. ACL 2020.
