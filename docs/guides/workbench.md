# Using the workbench

[Documentation](../README.md) · [Project overview](../../README.md)

## Using the workbench

| Page | What to inspect |
|---|---|
| **Overview** | Dataset coverage, available measurements and reference-risk comparisons. |
| **Live Demo** | A new single prompt, a live conversation, or a walkthrough backed by saved responses. |
| **Case Explorer** | One reference question, factual checklist, sources, actual answer and judge scores. |
| **Human Review Queue** | Why a case was routed, the evidence, and the review form. |
| **Safety Thresholds** | How alternative cutoffs would change routing on the existing scores. |
| **Judge Memory** | Draft scoring anchors and available review records. |
| **Scoring Rubrics** | All principles, scoring anchors and failure categories. |
| **Audit Trace** | The exact context and outputs behind individual judge calls. |
| **Evaluator Stability** | Perturbation and comparison evidence when a current run exists. |

The main batch benchmark and single-prompt evaluation use the five-principle
safety method. The live multi-turn demo uses a faster profile: one independent
judge and principles 3, 6, 8 and 12, alongside a separate risk classifier. Its
conversation metrics should not be pooled with the batch benchmark as if the
methods were identical. Classifier judgments and fallback heuristics are also
model/software outputs, not clinical ground truth.

Human reviews are session-local and downloadable by default. Refreshing or losing
the session can lose unexported reviews. Persistent review submission requires an
operator-supplied endpoint and admin token; this repository does not ship that
persistence backend. Marking an example for calibration does not fine-tune a
model or automatically establish clinician approval.

<a id="human-review-preview"></a>

[![Human review form for flagged Sarvam 105B case ref-029, with routing reasons, reference risk, model response and reviewer decision controls](../screenshots/human-review.png)](../screenshots/human-review.png)

*`ref-029` is one of the two answers flagged in the included Sarvam 105B run.
The form is shown before submission. No reviewer identity, approval or clinical
judgment was invented for this screenshot.*

Capture details and refresh instructions are in
[the screenshot guide](../screenshots/README.md).
