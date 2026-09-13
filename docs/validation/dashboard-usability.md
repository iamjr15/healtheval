# Dashboard clarity and responsive layout

This follow-up on 13 September 2026 addresses truncated labels and unnecessary
information in the workbench. The benchmark assets, fingerprint, measured model
answers and judge decisions are unchanged.

## What changed

- Overview: three explained measures and a single model comparison. Method details
  and routing uncertainty remain available in expanders.
- Cases: short model names, two primary filters, paginated readable rows, and full
  prompts/answers. Case details separate Answer, Reference and Scores.
- Human review: the full answer and available automated decisions precede the
  form. No verdict or failure category is preselected. Unmeasured evaluators are
  omitted from review targets and exported automated verdicts. Explicit safety
  verdicts and clinician escalation remain consistent with the saved fields.
- Thresholds: routed answers and changed decisions appear first; per-case and
  statistical detail expands on demand. The lowest slider boundary works.
- Judge trace: score, rationale and quoted evidence appear before raw prompts,
  retrieved examples and run statistics.
- Rubrics and judge examples: readable scoring tables, separated evidence tabs,
  shorter controls and explicit draft status.
- Shared layout: wrapped labels, responsive tables, shorter navigation and an
  automatically collapsed sidebar on phones. Live views use shorter labels and
  preserve complete saved responses.

## Checks performed

| Check | Result |
|---|---|
| Offline quality suite | 179 Python tests and five Worker tests passed; lint and repository checks passed. |
| New interaction regressions | Explicit review verdicts; safety-field precedence; absent comparator handling; escalation and example-proposal validation; flagged-case filtering and manual queue routing; threshold minimum; all four rubric packs. |
| Browser pages | All nine pages rendered at widths 1440, 1024, 768 and 390 using `agent-browser --auto-connect`. No Streamlit exceptions or page-level horizontal overflow. |
| Case detail | Full answer, reference and score tabs inspected, including the score table at phone width. An unflagged case was added from Cases and found in Human review through sidebar navigation. |
| README captures | Six fresh captures of actual saved evidence. Each image inspected at its original dimensions; review form left unsubmitted. |
| Evidence integrity | Deterministic asset and current-benchmark checks passed. No paid evaluations were rerun for the presentation changes. |

The browser pass checks saved-evidence states, filters and review controls. The
paid provider-path results remain those documented in the [end-to-end report](end-to-end.md).
The presentation changes do not create clinical approval or validate unmeasured
comparators. Historical implementation checks are in the
[repository validation report](production-quality.md).
