# Using the workbench

[Documentation](../README.md) · [Project overview](../../README.md)

## Navigation

| Page | What to inspect |
|---|---|
| **Overview** | Three explained headline measures and a model comparison; scoring details expand on demand. |
| **Live evaluation** | A new single prompt, a live conversation, or a walkthrough backed by saved responses. |
| **Cases** | One reference question, factual checklist, sources, actual answer and judge scores. |
| **Human review** | Why a case was routed, the evidence, and the review form. |
| **Thresholds** | How alternative cutoffs would change routing on the existing scores. |
| **Judge examples** | Draft scoring anchors and available review records. |
| **Rubrics** | All principles, scoring anchors and failure categories. |
| **Judge trace** | The exact context and outputs behind individual judge calls. |
| **Stability** | Perturbation and comparison evidence when a current run exists. |

Use **Cases** to filter by model, answer flag and patient urgency. More filters
open in the sidebar. Results are paginated; opening a case preserves the full
prompt and answer in **Answer**, **Reference** and **Scores** tabs. Routine,
Needs care and Urgent are plain-language names for the draft reference tiers;
they do not change the saved GREEN, AMBER and RED triage labels. **Add to human
review** also routes an otherwise unflagged case into the session queue.

The **Human review** form starts without a verdict. Choose whether the answer
is safe/unsafe, whether the automated decision was correct/incorrect, or whether
clinician review is needed. The failure category can be left as “Not specified” (an empty string in the exported record). Optional assessments and
future-example proposals open separately. Only evaluators with measured decisions
appear as review targets. Explicit safe/unsafe verdicts determine answer safety;
requesting escalation always records clinician follow-up.

**Thresholds** shows the number of routed answers and changed decisions first.
Per-case decisions and routing statistics are expandable. **Judge trace** shows
the selected score, rationale and quoted evidence before raw prompts and run
metadata. The trace includes reruns; it can contain more calls than the final
benchmark has scores.

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
