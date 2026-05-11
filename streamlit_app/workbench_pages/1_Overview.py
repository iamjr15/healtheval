"""Overview page for headline safety and audit metrics."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from streamlit_app.components.download_link import render_download_link
from streamlit_app.components.sens_spec_table import render_sens_spec_table
from streamlit_app.config import (
    CLOUDFLARE_LIVE_DEMO_URL,
    GITHUB_REPO_URL,
    PATH_HITL_REVIEWS_JSONL,
    PATH_PROMPTFOO_SAVED_HTML,
    PROJECT_ID,
    RUBRICS_DIR,
)
from streamlit_app.data_loaders import (
    load_calibration_examples,
    load_hitl_reviews_repo,
    load_methodology_artifact,
    methodology_model_ids,
    load_reference_items,
    load_tool_meta,
)
st.title("MaaSwasth Evaluation Workbench")
st.markdown(
    """
**This dashboard checks Hindi maternal-health chatbot answers for safety,
source grounding, and reviewability.**

Start here for the headline numbers. Then use the sidebar to run one live
prompt, inspect individual cases, tune thresholds, or review cases that need
a human decision. Automated result files are treated as fixed evidence; this
dashboard adds explanations, controls, and review records on top.
    """
)
methodology, selected_path, _calibration_suffix = load_methodology_artifact()
tool_meta = load_tool_meta()
reference_items = load_reference_items()
calibration_examples = load_calibration_examples()
hitl_repo_reviews = load_hitl_reviews_repo()
st.subheader("Headline Numbers")
st.caption(
    "Safety catch rate = unsafe cases caught. False-alarm control = safe "
    "cases that were not over-flagged. In maternal health, the recommended "
    "setting intentionally prioritizes catching risk over minimizing review volume."
)

final_method_rows = list(tool_meta.get("table_final_method", []))
best_variant: dict | None = final_method_rows[0] if final_method_rows else None

panel_table = list(tool_meta.get("table_panel_models", []))
native_table = panel_table or list(tool_meta.get("table_native", []))

expected_violation_count = sum(
    1
    for item in reference_items
    if str(item.get("expected_safety_action", "")).lower() != "continue"
)
expected_clean_count = len(reference_items) - expected_violation_count

session_reviews = list(st.session_state.get("hitl_reviews", []))
hitl_total = len(session_reviews) + len(hitl_repo_reviews)

rubric_pack_files = sorted(Path(RUBRICS_DIR).glob("*.yaml"))

jury_models = list(methodology.get("jury", []))
panel_models = methodology_model_ids(methodology)
row1 = st.columns(3)
row2 = st.columns(3)

with row1[0]:
    if best_variant is not None:
        sens = best_variant.get("sensitivity", {}).get("rate")
        spec = best_variant.get("specificity", {}).get("rate")
        st.metric(
            "Safety catch rate / false-alarm control",
            f"{sens * 100:.1f}% / {spec * 100:.1f}%"
            if (sens is not None and spec is not None)
            else "—",
            help=(
                "Sensitivity = unsafe cases caught. "
                "Specificity = safe cases not over-flagged. "
                "MaaSwasth Safety Method row from "
                "`results/tool_meta_evaluation.json`."
            ),
        )
        st.caption(
            "Optimized for high safety recall. Lower false-alarm control means "
            "borderline cases are intentionally sent to human review instead "
            "of being treated as safe automatically."
        )
    else:
        st.metric("Safety catch rate / false-alarm control", "—")

with row1[1]:
    st.metric(
        "Reference set x panel",
        f"n = {len(reference_items)} x {len(panel_models) or 1}",
        help=(
            f"{expected_violation_count} expected violations · "
            f"{expected_clean_count} expected clean · "
            "from `data/reference_set.yaml`, evaluated once per selected panel model."
        ),
    )

with row1[2]:
    st.metric(
        "Judge jury",
        f"{len(jury_models)} judges",
        help=(
            "Cross-family jury: " + ", ".join(f"`{m}`" for m in jury_models)
            if jury_models
            else "Jury list missing from canonical artefact metadata."
        ),
    )

with row2[0]:
    st.metric(
        "Human reviews completed",
        f"{hitl_total}",
        help=(
            f"{len(session_reviews)} this browser session · "
            f"{len(hitl_repo_reviews)} from `{PATH_HITL_REVIEWS_JSONL.name}` "
            "if the persistent endpoint has appended any."
        ),
    )

with row2[1]:
    st.metric(
        "Judge-memory examples",
        f"{len(calibration_examples)} examples",
        help=(
            "Hand-authored seed pack at `data/judge_calibration_examples.yaml`."
            "  HITL-promoted entries arrive offline via "
            "`scripts/promote_to_calibration.py` after sustained review."
        ),
    )

with row2[2]:
    st.metric(
        "Scoring rubrics",
        f"{len(rubric_pack_files)} packs",
        help=(
            "Files in `data/rubrics/` — bumping a rubric creates a new "
            "`{metric}_v{N}.yaml` rather than overwriting the old version."
        ),
    )
st.subheader("Evaluator Comparison")
st.caption(
    "These comparator results show how each automated evaluator behaves on "
    "the same 30 cases. Blue is catch rate; teal is false-alarm control."
)


def _display_evaluator_name(raw: object) -> str:
    labels = {
        "independent_methodology": "MaaSwasth Safety Method",
        "cerai_metric_layer": "CeRAI",
        "inspect_safety_scorer": "Inspect scorer",
    }
    name = str(raw or "—")
    if name.startswith("maaswasth_safety_method:"):
        return name.split(":", 1)[1]
    return labels.get(name, name.replace("_", " "))


native_chart_rows = []
for row in native_table:
    name = _display_evaluator_name(row.get("evaluator", "?"))
    sens_rate = row.get("sensitivity", {}).get("rate")
    spec_rate = row.get("specificity", {}).get("rate")
    if sens_rate is None or spec_rate is None:
        continue
    native_chart_rows.append(
        {
            "Evaluator": name,
            "Catch rate": float(sens_rate),
            "False-alarm control": float(spec_rate),
        }
    )

if native_chart_rows:
    df_native = pd.DataFrame(native_chart_rows)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Catch rate",
            x=df_native["Evaluator"],
            y=df_native["Catch rate"],
            marker_color="#1d4ed8",
            text=df_native["Catch rate"].map(lambda v: f"{v * 100:.0f}%"),
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            name="False-alarm control",
            x=df_native["Evaluator"],
            y=df_native["False-alarm control"],
            marker_color="#06aed4",
            text=df_native["False-alarm control"].map(lambda v: f"{v * 100:.0f}%"),
            textposition="outside",
        )
    )
    fig.update_layout(
        barmode="group",
        height=320,
        margin=dict(l=10, r=10, t=10, b=10),
        yaxis=dict(range=[0, 1 + 0.1], tickformat=",.0%"),
        legend=dict(orientation="h", yanchor="bottom", y=1 + 0.02),
    )
    st.plotly_chart(fig, width="stretch")
    render_sens_spec_table(
        native_table,
        title="Evaluator comparison — full table with uncertainty intervals",
        caption=(
            "Intervals show uncertainty from the small 30-case reference set. "
            "The Beta-Binomial interval is the preferred small-sample estimate."
        ),
        show_credible_intervals=True,
    )
else:
    st.info("Panel evaluator table missing from `tool_meta_evaluation.json`.")
st.subheader("What The MaaSwasth Safety Method Adds")
st.markdown(
    """
1. **Automated checks** compare each panel model answer against source evidence,
   safety rules, and independent judge scores.
2. **Promptfoo + DeepEval** provide a companion saved-output smoke check
   over the first reference case by default.
3. **Human review** catches cases where automated tools disagree, fail to
   parse, or sit near a decision boundary.
4. **Judge memory** gives the judge jury approved examples so future scoring
   has precedent.
5. **Versioned rubrics** keep scoring rules explicit and auditable.
6. **Audit traces** record the model, prompt, rubric, examples, and settings
   behind each judge call where trace data is available.
    """
)

if PATH_PROMPTFOO_SAVED_HTML.exists():
    render_download_link(
        "Download Promptfoo + DeepEval Smoke Output",
        PATH_PROMPTFOO_SAVED_HTML.read_bytes(),
        file_name=PATH_PROMPTFOO_SAVED_HTML.name,
        mime="text/html",
    )
    st.caption(
        "Generated from `promptfooconfig.saved.yaml`. The Docker smoke service "
        "runs the first reference prompt across the four saved panel outputs. "
        "Use `MAASWASTH_PROMPTFOO_LIMIT=30` only for a full DeepEval pass."
    )
else:
    st.warning(
        "`results/promptfoo_saved.html` is missing. Re-run "
        "`docker compose --profile test run --rm promptfoo-saved` to regenerate it.",
        icon="⚠️",
    )
st.subheader("Where To Go Next")
st.markdown(
    """
Use the sidebar to move through the workflow:

- **Live Demo**: run one Hindi prompt and see the full evaluation pipeline.
- **Case Explorer**: open any fixed test case and inspect all evidence.
- **Human Review Queue**: submit a human verdict for routed cases.
- **Safety Thresholds**: test how stricter or looser thresholds affect results.
- **Judge Memory**: see the examples used to calibrate the judge.
- **Scoring Rubrics**: read the rules behind each score.
- **Audit Trace**: inspect the exact judge-call evidence.
    """
)
st.subheader("Important Limits")
st.markdown(
    f"""
- **Triage JSON reliability.** The dashboard uses the current complete result
  file selected from `results/`. If a model does not return valid triage
  JSON, that case is treated as a failure and routed toward human review.
- **Small reference set.** The benchmark has 30 cases. This is useful for
  a two-day assignment and focused safety analysis, but not enough for broad
  claims across every user group.
- **Judge memory is early.** The seed pack has `{len(calibration_examples)}`
  approved examples. It demonstrates the mechanism; accuracy gains require
  more sustained human review.
    """
)
st.divider()
foot = st.columns(2)
with foot[0]:
    if GITHUB_REPO_URL:
        st.markdown(f"[GitHub repo →]({GITHUB_REPO_URL})")
    else:
        st.caption("GitHub URL not configured.")
with foot[1]:
    if CLOUDFLARE_LIVE_DEMO_URL:
        st.markdown(f"[Cloudflare live demo →]({CLOUDFLARE_LIVE_DEMO_URL})")
    else:
        st.caption("Cloudflare live demo URL not configured.")

st.caption(
    f"Complete result file: `{selected_path.name}`  ·  "
    f"models: `{', '.join(panel_models) or 'single target'}`  ·  "
    f"Cloud Run project: `{PROJECT_ID}`"
)
