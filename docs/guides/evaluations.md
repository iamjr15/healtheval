# Running evaluations

[Documentation](../README.md) · [Project overview](../../README.md)

## Model panel and generation settings

| Candidate model ID | Role | Judges in the full configuration |
|---|---|---|
| `sarvam-105b-conversations` | Default Hindi conversation candidate. | Gemini, Claude |
| `sarvam-105b` | Sarvam reasoning-model comparator. | Gemini, Claude |
| `claude-sonnet-4-6` | Anthropic comparator. | Gemini, Sarvam 105B |
| `gemini-2.5-pro` | Google comparator. | Claude, Sarvam 105B |

Sarvam's currently supported chat model IDs were verified on **13 September
2026** against its [API reference](https://docs.sarvam.ai/api-reference/chat/chat-completions)
and [changelog](https://docs.sarvam.ai/changelog). The conversational 105B variant
is the default because of its stated Indic-dialogue focus. That is a task-fit
choice, not evidence of clinical superiority. The project uses exact model IDs
and does not silently substitute a different model for a retired one.

The main candidate clients use temperature 0. Sarvam uses v1 chat completions,
`max_tokens=2048` and explicit `reasoning_effort=null`. Claude uses
`max_tokens=2048`. Gemini uses `max_output_tokens=4096`, `thinking_budget=512` and
excludes thought content from the displayed answer. Exact settings are recorded
in each model artifact. These are the project's chosen evaluation settings, not
claims about each model's maximum capability. API outputs may still vary across
runs and provider updates.


## Run evaluations

Run these commands from the repository root. The examples write to separate
output directories so experiments do not replace the committed workbench evidence.
Every live example makes provider API calls.

### Small end-to-end run with Sarvam and Gemini

This asks three reference questions of one candidate and scores each answer with
one independent judge: three candidate calls and 15 judge cells before retries.
A limit selects the first cases; it is not a stratified sample of all risk levels.

```bash
uv run python scripts/run_panel_refset_eval.py \
  --models sarvam-105b-conversations \
  --judges gemini-2.5-pro \
  --limit 3 \
  --output-dir results/runs/my_smoke

uv run python scripts/compute_panel_tool_meta.py \
  --panel results/runs/my_smoke/methodology_panel_refset_eval.json \
  --output results/runs/my_smoke/tool_meta_evaluation.json
```

### Full four-model, two-judge configuration

This evaluates 30 cases × four models: **120 answers and 1,200 judge cells** before
retries. It requires funded access to all three providers. Judge selection is
explicit so a local reduced-jury environment setting cannot change this example.

```bash
uv run python scripts/run_panel_refset_eval.py \
  --models sarvam-105b-conversations,sarvam-105b,claude-sonnet-4-6,gemini-2.5-pro \
  --judges claude-sonnet-4-6,gemini-2.5-pro,sarvam-105b \
  --model-workers 2 --judge-workers 3 \
  --output-dir results/runs/my_full_run

uv run python scripts/compute_panel_tool_meta.py \
  --panel results/runs/my_full_run/methodology_panel_refset_eval.json \
  --output results/runs/my_full_run/tool_meta_evaluation.json
```

### Reproduce the configuration used for the included live evidence

The included run uses three candidates and one independent judge per answer:
Gemini judges both Sarvam variants; Sarvam 105B judges Gemini.

```bash
uv run python scripts/run_panel_refset_eval.py \
  --models sarvam-105b-conversations,sarvam-105b,gemini-2.5-pro \
  --judges gemini-2.5-pro,sarvam-105b \
  --model-workers 2 --judge-workers 3 \
  --output-dir results/runs/my_three_model_run

uv run python scripts/compute_panel_tool_meta.py \
  --panel results/runs/my_three_model_run/methodology_panel_refset_eval.json \
  --output results/runs/my_three_model_run/tool_meta_evaluation.json
```

This reproduces the configuration, not necessarily identical model outputs.
A reduced jury must be reported as such.

### Resume, reuse and change a run

| Option | Behavior |
|---|---|
| `--resume` | Keep compatible completed rows and continue missing cases in the selected output directory. |
| `--reuse-responses` | Re-score saved candidate responses using the compatible saved benchmark and scoring configuration. Judge calls still cost money. |
| `--fill-missing-responses` | With response reuse, permit candidate calls for answers that are absent. |
| `--force` | Delete selected models' existing artifacts before running again. Use deliberately when replacement is intended. |
| `--reset-trace` | Clear that output directory's judge trace before the run. |
| `--model-workers`, `--judge-workers` | Bound concurrent candidate workflows and judge calls per answer. |

The runner checks the benchmark fingerprint, jury, scoring configuration and
candidate generation settings before reusing artifacts. Use a fresh directory
when changing them. A subset run combines only the selected models; it does not
claim to be the full panel. Judge traces append unless reset, so they can contain
more calls than the final set of scored rows.

The workbench reads the canonical files under `results/`. To intentionally
replace its evidence, run a coherent selected panel with `--output-dir results`
and then run `scripts/compute_panel_tool_meta.py` with its defaults. Preserve the
old run first and use `--force` only when replacement is intended. Experimental
output directories are not selected automatically by the workbench.


## Saved evidence and reproducibility

| File, relative to the selected output directory | Contents |
|---|---|
| `panel_refset_eval/<model>.json` | Per-model checkpoints, responses, triage, judge scores, decisions and generation settings. |
| `methodology_panel_refset_eval.json` | Combined selected-model evidence, case counts, actual jury and benchmark metadata. |
| `judge_trace.jsonl` | One JSON record per judge call, including the rendered scoring prompt, raw output and retrieved examples. |
| `tool_meta_evaluation.json` | Derived aggregate metrics, produced by `compute_panel_tool_meta.py`. |

The benchmark fingerprint hashes the relative filenames and bytes of the reference
set, shared system prompt, constitution, calibration examples and rubric YAMLs.
It detects a change to those assets, even when a filename stays the same. It is
not a hash of the entire source tree: retain the Git commit and generation
settings as well when comparing experiments.

Per-model checkpoints are written atomically. Dashboard evidence loading checks
for a completed current-benchmark artifact, with further validation downstream.
Stale or absent measurements are shown as unavailable. Older-domain measurements
are not relabeled as current HealthEval results.

<a id="audit-trace-preview"></a>

<details>
<summary><strong>Inspect the audit trail behind a score</strong></summary>

[![Audit Trace showing recorded judge calls and the selected call's scoring evidence](../screenshots/audit-trace.png)](../screenshots/audit-trace.png)

*Trace records connect a score to its case, model, principle, parser result and
judge output. They support inspection and debugging; repeated calls can appear
when a run is retried.*

</details>


## Optional integrations

| Integration | Purpose and current scope |
|---|---|
| **Cloudflare Pages / Worker demo** | A browser chat interface using the shared health prompt and current model clients. It returns a candidate response and parsed triage; it does not run the independent judging pipeline. |
| **Promptfoo + DeepEval** | Additional evaluation of live or saved responses through custom Python providers. Promptfoo is pinned in `package.json`. Saved responses still require a funded LLM judge for DeepEval scoring. |
| **Inspect tasks** | Separate safety, factuality and equity evaluation entry points under `eval/inspect_tasks/`. Their results are separate from the main five-principle method. |
| **CeRAI** | Optional comparison with an external evaluation service. Configure the service and regenerate current-benchmark results before making comparisons. |
| **Perturbation audit** | Generate meaning-preserving answer variants, verify them, re-score them and examine evaluator stability. See the [audit methodology](../methodology/perturbation-audit.md). |
| **Red-team configuration** | Optional Promptfoo adversarial testing in `promptfooconfig.redteam.yaml`; the external service may require account verification. |

For the local Worker demo:

```bash
npm ci
npm run demo
```

Wrangler uses local provider secrets from `.dev.vars`. Supply the appropriate
`SARVAM_API_KEY`, `ANTHROPIC_API_KEY`, or `GOOGLE_API_KEY` / `GEMINI_API_KEY` there
for the model selected in the browser. Open the local URL printed by Wrangler,
usually <http://localhost:8788>. Hosting requires a separate Cloudflare setup;
renaming the GitHub repository does not deploy a public service.

Promptfoo configs are [live](../../promptfooconfig.yaml) and
[saved-output](../../promptfooconfig.saved.yaml). The saved config lists all four
candidate IDs; match that list to the models actually present in your artifact
before running it. The included evidence has no completed Claude run. Set
`PROMPTFOO_PYTHON` to the project's `.venv/bin/python` and use
`HEALTHEVAL_PROMPTFOO_LIMIT` for a small case limit. A live one-case integration
was verified; a complete optional red-team, CeRAI or perturbation measurement is
not included.


## Troubleshooting

| Symptom | Next step |
|---|---|
| Live evaluation is unavailable | Configure the selected candidate and its independent judges, then restart the application if environment settings changed. |
| Authentication, credit or quota error | Check that provider's account and model access. Select an explicitly reduced panel if appropriate and record that reduction. |
| “No independent judge remains” | Add a judge from another family. The two Sarvam variants cannot judge each other. |
| Results belong to a different benchmark | Keep the old run for reference and regenerate against the current assets in a fresh output directory. |
| Overview has no measured results | Confirm the canonical panel artifact is complete and current, then generate `tool_meta_evaluation.json`. |
| An optional comparison is unavailable | Run and configure that integration against the current benchmark; missing measurements are not passing scores. |
| Malformed triage or failed judge cells | Inspect the raw response and trace. Check provider errors and output limits before rerunning affected work. |
| A browser review disappears | Export session-local reviews before leaving, or configure a persistence endpoint. |
| Port 8501 is already in use | Start Streamlit with `--server.port 8502` and open that port. |
| Node engine mismatch | Use Node 22.22 or newer, then rerun `npm ci`. |
