# HealthEval end-to-end validation

Validated on 13 September 2026. This records software and API integration checks against the AI-authored draft benchmark; it is not clinical validation.

## Automated checks

- Python: 155 passed, no failures or skips. Includes a complete isolated 30-case × four-model pipeline with mocked provider boundaries; synthetic outputs stay in temporary test directories.
- Publication regression: flagged answers remain in the review queue even when comparison evaluators agree; missing comparison evidence does not create a disagreement. Failed judge scores are excluded from the queue's dispersion calculation. The Node requirement now matches the installed optional tooling. Aggregate routing labels now name safety probes (including refusal cases) rather than implying that all 21 positive probes are AMBER/RED patients; routing rates are not tinted as clinical pass/fail.
- Worker endpoint: five tests passed, covering request validation, current Sarvam dispatch/settings, Gemini key alias, response parsing and sanitized provider errors.
- Promptfoo → Python provider → Sarvam → DeepEval/Gemini: one real case passed, no assertion failures or evaluation errors.
- Docker: image built and health endpoint returned `ok`; Compose configuration validated.

## Live benchmark

| Model | Cases | Valid triage JSON | Judge cells | Failed judge cells | Independent judges per answer |
|---|---:|---:|---:|---:|---:|
| `sarvam-105b-conversations` | 30 | 30 | 150 | 0 | 1 |
| `sarvam-105b` | 30 | 30 | 150 | 0 | 1 |
| `gemini-2.5-pro` | 30 | 30 | 150 | 0 | 1 |

The two Sarvam variants were judged by Gemini. Gemini was judged by Sarvam 105B. Both Sarvam variants exclude their related Sarvam judge. Anthropic returned an insufficient-credit error, so the full four-model/two-judge configuration could not be validated live. The reduced jury is recorded explicitly in each artifact.

An initial Gemini run returned one truncated JSON fence on `ref-026`; the evaluator flagged it. After setting a bounded thinking budget and additional output headroom, all 30 Gemini cases were rerun. The original run is preserved under `results/live_smoke/gemini_before_output_budget_fix.json`. The final 90 responses all parse; model safety and triage correctness remain separate measured outcomes.

## Browser checks

Using `agent-browser --auto-connect` against the local workbench:

- All nine pages opened without Streamlit exceptions, including the empty-evidence state before the first completed run.
- Publication browser recheck: Overview shows the corrected safety-probe labels; the Sarvam 105B review queue includes flagged `ref-029` without false missing-comparator disagreements; Safety Thresholds opens without an exception.
- Case Explorer opened a reference case with checklist, source context, model response, score grid and missing-comparator notice.
- Single Prompt Evaluation ran a real emergency case through Sarvam and five independent judge scores.
- Live Multi-turn ran routine hygiene followed by chest pain and severe breathing difficulty: classifier/model trajectory GREEN → RED, emergency escalation on turn 2. The test exposed and fixed a counter that confused answer-review flags with missed emergency triage.
- The Pages/Worker browser demo called Sarvam and displayed RED, `refer_emergency`, the stated symptoms and a real response.

## Scope and remaining external prerequisites

Clinical and bilingual review remain pending. CeRAI and robustness-comparison measurements have not been regenerated; the UI shows them as unavailable. Perturbation generation is covered by isolated success, verifier-failure, changed-meaning and provider-outage tests. No synthetic responses are used as measured dashboard evidence.

The GitHub repository is [iamjr15/healtheval](https://github.com/iamjr15/healtheval); its description was updated and its obsolete deployment homepage was cleared. At the start of publication, 19 local commits had not yet been pushed, in addition to the migration changes. This report records validation; Git history records the subsequent publication. No hosting deployment was performed. Historical artifacts and the pre-migration working tree were backed up outside the repository before replacement.

Local validation used a workbench on port 8502 and a browser response demo on port 8788. Those local preview addresses are not public deployments.

[Workbench screenshot](qa/healtheval-overview.png).

Detailed counts: `results/live_smoke/e2e_summary.json`. Current evidence: `results/methodology_panel_refset_eval.json` and `results/tool_meta_evaluation.json`.
