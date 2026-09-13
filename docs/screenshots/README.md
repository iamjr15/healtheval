# README screenshots

Captured from the local HealthEval workbench on 13 September 2026 using
`agent-browser --auto-connect`, attached to the existing Chrome browser. These
are browser captures of the application, with no generated model answers,
retouched scores or invented reviewer approvals. Open an image at full size to
read the Hindi text and detailed labels.

The underlying evidence is the current three-model benchmark: 90 responses,
450 usable final judge cells, and one independent judge per response. The cases
and calibration anchors remain synthetic drafts pending clinical review. The
trace file contains additional calls from retries and the earlier Gemini run.

| Image | Application view | Selected state |
|---|---|---|
| [Overview](overview.png) | Overview | Current benchmark inventory, patient-risk metrics and answer-review routing. |
| [Case Explorer](case-explorer.png) | Case Explorer | Sarvam 105B Conversations, all 30 reference cases. |
| [Reference case](reference-case.png) | Case Explorer → Open Case Detail | `ref-003`, with expected emergency handling, checklist and source link. |
| [Response and review](response-review.png) | Same case detail, scrolled to the response | Sarvam 105B Conversations answer, RED triage, and Gemini's five-principle score grid and GREEN answer-review band. |
| [Human review](human-review.png) | Human Review Queue | Sarvam 105B, flagged `ref-029`, response excerpt expanded. The form has not been submitted. |
| [Audit trace](audit-trace.png) | Audit Trace | `ref-003`, one recorded Sarvam judge call, its rationale and retrieved draft anchors. |

## Refresh the captures

1. Start the workbench from the repository root:

   ```bash
   uv run streamlit run streamlit_app/app.py --server.port 8503
   ```

2. Open a dedicated, pinned capture tab in the existing browser:

   ```bash
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     tab new --label healtheval-readme http://localhost:8503/Overview
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     set viewport 1600 940
   ```

3. Use snapshots and the application controls to reach each state in the table.
   Wait for the case, table and chart to finish rendering. The case-detail and
   review images use ordinary scrolling and expanded sections. Use a taller
   viewport when needed to include a complete section without cutting off its
   labels or decision values.
4. Select the dedicated tab before capturing so Chrome paints the current view
   completely, then capture to an **absolute output path**:

   ```bash
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     tab healtheval-readme
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     screenshot /absolute/path/to/healtheval/docs/screenshots/overview.png
   ```

5. Inspect every image, check its README caption against the selected result,
   and verify both normal and expanded image sections on GitHub. Keep credentials,
   personal input and private review records out of captures. Do not submit a
   review just to populate an illustration.
6. Close only the dedicated capture tab when finished. Refresh these screenshots
   when the visible interface or benchmark changes; do not edit a screenshot to
   imply a result the application did not produce.

The Overview percentages and their counts are displayed separately to avoid
truncation. Judge heatmaps use the rubric's fixed 1–5 scale so colors remain
comparable between cases. Draft anchor scores are labeled as drafts in the audit
view.
