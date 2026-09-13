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
| [Overview](overview.png) | Overview | 90 answers, 98.9% triage matches, two flags and one model comparison. 1440 × 1000. |
| [Case Explorer](case-explorer.png) | Cases | Sarvam Conversations, first 10 of 30 matching cases. 1440 × 1120. |
| [Reference case](reference-case.png) | Cases → Open case → Reference | `ref-003`, with expected emergency handling, checklist and source link. Focused dialog capture, 960 × 995. |
| [Response and review](response-review.png) | Cases → Open case → Answer | Full Sarvam Conversations answer to `ref-003`, RED model triage and GREEN answer score. Focused dialog capture, 960 × 671. |
| [Human review](human-review.png) | Human review | Sarvam 105B, flagged `ref-029`, full response and unsubmitted form. Focused review-panel capture, 980 × 1161, at a 1440-wide viewport. |
| [Audit trace](audit-trace.png) | Judge trace | `ref-003`, Sarvam 105B judge, P6, score rationale and quoted evidence. 1440 × 1000. |

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
     set viewport 1440 1000
   ```

3. Use snapshots and the application controls to reach each state in the table.
   Wait for the case, table and chart to finish rendering. A heading appearing
   does not prove that Streamlit has completed the rest of the page. For Overview,
   wait until all three headline values, the model comparison and the final
   “Detailed triage and review statistics” expander exist before capturing.
   Bring the tab to the foreground before navigation and capture. Case details
   use the Answer and Reference tabs; the review image uses ordinary scrolling
   to the expanded `ref-029` form. Use a taller
   viewport when needed to include a complete section without cutting off its
   labels or decision values.
4. Set the viewport before scrolling. Wait for dialog and tab animations to
   settle (about one second), then select the dedicated tab so Chrome paints the current view
   completely, then capture to an **absolute output path**:

   ```bash
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     tab healtheval-readme
   agent-browser --auto-connect --session healtheval-shots --pin-tab \
     screenshot /absolute/path/to/healtheval/docs/screenshots/overview.png
   ```

   For a focused case image, use `screenshot '[role=dialog]' /absolute/path.png`.
   For the review image, capture the expanded review container. Make the viewport
   tall enough for its complete bounds before capture; off-screen content inside
   Streamlit's scrolling main area may otherwise render blank in an element capture.

5. Inspect every image, check its README caption against the selected result,
   and verify both normal and expanded image sections on GitHub. Keep credentials,
   personal input and private review records out of captures. Do not submit a
   review just to populate an illustration.
6. Close only the dedicated capture tab when finished. Refresh these screenshots
   when the visible interface or benchmark changes; do not edit a screenshot to
   imply a result the application did not produce.

Headline values have visible definitions. Small tables wrap fully and become
labelled rows when space is narrow. Judge heatmaps use short principle IDs,
full labels below the chart and the fixed 1–5 scale. Draft examples remain
labelled as drafts. The default phone layout collapses the sidebar.
