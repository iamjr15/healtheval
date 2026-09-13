# Published evaluation evidence

The canonical artifacts contain real provider outputs on the synthetic
`healtheval_health_v1` benchmark. They are separate from mocked software-test
fixtures, which are generated only in temporary directories.

| Path | Role |
|---|---|
| `panel_refset_eval/<model>.json` | Candidate checkpoints with responses, triage, scores and settings. |
| `methodology_panel_refset_eval.json` | Combined selected-model evidence and actual jury. |
| `judge_trace.jsonl` | Per-call rendered judge context, raw output and parser result. Includes retries and superseded calls. |
| `tool_meta_evaluation.json` | Derived aggregate measures used by the workbench. |
| `live_smoke/` | Named diagnostics and historical API/browser verification, including the initial Gemini output-budget issue. Not the canonical benchmark. |
| `runs/` | Ignored local experiments; created when running the documented live examples. |

The included panel contains 90 answers across three candidates and 450 usable
final judge cells. Each answer has one independent judge. Claude was not funded
for the recorded live validation. Dataset labels and anchors remain clinical-review
drafts; the results are not a clinical safety certification.

Use [the evaluation guide](../docs/guides/evaluations.md) to reproduce or replace
evidence. Preserve the benchmark fingerprint, Git revision, actual jury and
model settings. Regenerate the combined and aggregate files together. The
[detailed validation report](../docs/validation/end-to-end.md) records measured
scope and limitations.

Prompts, answers and traces can contain sensitive material when using custom
inputs. Review a run before intentionally publishing it. Local budget, review and
threshold overlays belong in ignored `var/`, not here; existing overlays can be
migrated using the [operations guide](../docs/guides/deployment.md#storage-and-data-lifecycle).
