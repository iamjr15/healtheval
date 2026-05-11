# CeRAI Findings Log

This is the archived review log for the CeRAI evaluation tool analysis. It is
kept as comparative research evidence for the submission, not as a Streamlit
dashboard page.

## Findings

1. **Reviewer setup was too fragile.** A reviewer should be able to run the
   harness with one clear command and predictable defaults. The CeRAI flow had
   too many implicit setup assumptions for a two-day assignment review.

2. **Configuration validation happened too late.** Environment variables, model
   providers, paths, and data files needed an explicit preflight check before any
   evaluation run.

3. **The application surface was fragmented.** Multiple services, scripts, and
   routes made it hard to tell which path was the canonical evaluation workflow.

4. **Metric outputs were not strongly schema-bound.** Evaluation results should
   have a stable, typed contract so reports, dashboards, and downstream checks
   cannot silently consume malformed outputs.

5. **Lexical metrics were over-emphasized.** BLEU, ROUGE, METEOR, and similar
   overlap metrics are useful as weak signals, but they are poor primary
   indicators for Hindi maternal-health safety.

6. **The LLM judge was stateless.** Each judge call was made as a fresh prompt,
   without calibration examples, previous human corrections, or dataset-specific
   precedent.

7. **Rubrics were not versioned as first-class artifacts.** The scoring scale,
   thresholds, examples, false-positive guidance, and domain-specific rules
   should be pinned by rubric version.

8. **Judge responses were too free-form.** A production-quality harness should
   require structured judge output with score, confidence, evidence, failure
   type, and rubric breakdown.

9. **Judge reproducibility metadata was incomplete.** Model version,
   temperature, seed, prompt version, rubric version, dataset version, strategy
   version, and cache key should be persisted with every verdict.

10. **There was no judge self-consistency layer.** Running one judge once hides
    variance. Repeated calls or multiple judge models are needed to surface
    disagreement and low-confidence cases.

11. **Human-in-the-loop review was not a core workflow.** Borderline, unsafe, or
    high-disagreement cases should flow into an adjudication queue and optionally
    become calibration examples.

12. **Medical safety rules needed stronger domain grounding.** The harness
    needed explicit maternal-health red flags, referral rules, self-medication
    risks, and source-grounding expectations.

13. **Evaluator performance needed a reference-set view.** A credible safety
    evaluator should report sensitivity and specificity against a hand-labelled
    reference set, not only aggregate metric scores.

14. **Case-level auditability was weak.** Reviewers should be able to inspect
    the prompt, expected answer, model answer, evaluator verdict, rubric, judge
    trace, and final routing decision in one place.

## How This Informed MaaSwasth

MaaSwasth keeps the useful CeRAI-style metric comparison, but wraps it in a
schema-first safety harness: a canonical reference set, a source-grounded safety
method, panel-model evaluation, structured judge traces, threshold tuning,
calibration memory, and HITL review overlays.
