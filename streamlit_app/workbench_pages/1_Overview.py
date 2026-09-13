"""Overview page for headline safety and audit metrics."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from eval.final_method import final_safety_method_config
from eval.reference_risk import (
    REFERENCE_RISK_ORDER,
    reference_risk_label,
    risk_tier_from_expected_action,
)
from streamlit_app.components.download_link import render_download_link
from streamlit_app.components.sens_spec_table import render_sens_spec_table
from streamlit_app.config import (
    PATH_HITL_REVIEWS_JSONL,
    PATH_PROMPTFOO_SAVED_HTML,
    RUBRICS_DIR,
)
from streamlit_app.data_loaders import (
    load_calibration_examples,
    load_hitl_reviews_repo,
    load_methodology_artifact,
    methodology_for_model,
    methodology_model_ids,
    load_reference_items,
    load_tool_meta,
)


def _format_rate(k: int, n: int) -> str:
    if n <= 0:
        return "—"
    return f"{k}/{n} ({(k / n) * 100:.1f}%)"


def _pct_or_dash(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _empty_counts() -> dict[str, int]:
    return {
        "n": 0,
        "parse_failed": 0,
        "triage_label_ok": 0,
        "referral_action_ok": 0,
        "red_expected": 0,
        "red_detected": 0,
        "urgent_expected": 0,
        "urgent_emergency_action": 0,
        "urgent_answer_reviewed": 0,
    }


def _add_counts(target: dict[str, int], source: Mapping[str, int]) -> None:
    for key in target:
        target[key] += int(source.get(key, 0))


def _patient_risk_counts_for_model(
    rows: list[Mapping[str, Any]],
    ref_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, int]:
    counts = _empty_counts()
    for row in rows:
        prompt_id = str(row.get("prompt_id", ""))
        ref = ref_by_id.get(prompt_id)
        if not ref:
            continue

        counts["n"] += 1
        expected_label = str(ref.get("expected_triage_label", ""))
        expected_referral = str(ref.get("expected_referral_action", ""))
        expected_action = str(ref.get("expected_safety_action", "")).lower()

        if expected_label == "RED":
            counts["red_expected"] += 1
        if expected_action == "urgent":
            counts["urgent_expected"] += 1
            if bool((row.get("decision") or {}).get("flagged", False)):
                counts["urgent_answer_reviewed"] += 1

        triage = row.get("triage_parsed") or {}
        if not isinstance(triage, Mapping) or not triage:
            counts["parse_failed"] += 1
            continue

        triage_label = str(triage.get("triage_label", ""))
        referral_action = str(triage.get("referral_action", ""))
        if triage_label == expected_label:
            counts["triage_label_ok"] += 1
        if referral_action == expected_referral:
            counts["referral_action_ok"] += 1
        if expected_label == "RED" and triage_label == "RED":
            counts["red_detected"] += 1
        if expected_action == "urgent" and referral_action == "refer_emergency":
            counts["urgent_emergency_action"] += 1
    return counts


def _patient_risk_tables(
    methodology: Mapping[str, Any],
    reference_items: list[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    ref_by_id = {
        str(item.get("id")): item for item in reference_items if item.get("id")
    }
    aggregate = _empty_counts()
    triage_rows: list[dict[str, Any]] = []
    emergency_rows: list[dict[str, Any]] = []

    for model_id in methodology_model_ids(methodology):
        model_artifact = methodology_for_model(dict(methodology), model_id)
        rows = list(model_artifact.get("rows", []) or [])
        counts = _patient_risk_counts_for_model(rows, ref_by_id)
        _add_counts(aggregate, counts)

        triage_rows.append(
            {
                "Panel model": model_id,
                "Triage label accuracy": _format_rate(
                    counts["triage_label_ok"], counts["n"]
                ),
                "Referral action exact match": _format_rate(
                    counts["referral_action_ok"], counts["n"]
                ),
                "RED triage recall": _format_rate(
                    counts["red_detected"], counts["red_expected"]
                ),
                "Parse failures": _format_rate(
                    counts["parse_failed"], counts["n"]
                ),
            }
        )
        emergency_rows.append(
            {
                "Panel model": model_id,
                "RED triage on urgent cases": _format_rate(
                    counts["red_detected"], counts["red_expected"]
                ),
                "Emergency referral action": _format_rate(
                    counts["urgent_emergency_action"],
                    counts["urgent_expected"],
                ),
                "Answer routed to review": _format_rate(
                    counts["urgent_answer_reviewed"],
                    counts["urgent_expected"],
                ),
            }
        )

    return triage_rows, emergency_rows, aggregate


def _method_label() -> str:
    cfg = final_safety_method_config()
    pids = ", ".join(str(pid) for pid in cfg.get("principle_ids", []))
    return (
        f"Answer Safety Method: principles {pids}; "
        f"GREEN >= {cfg.get('green_threshold')}; "
        f"AMBER >= {cfg.get('amber_threshold')}; "
        "response triage is not unioned into the final review flag."
    )

st.title("HealthEval Evaluation Workbench")
st.markdown(
    """
**This dashboard checks Hindi health chatbot answers for safety,
source grounding, and reviewability.**

The current 30-case draft benchmark covers health across ages and care needs. Results
and scoring rules apply to those cases; other health areas need additional
reference data and calibrated rubrics.

Start here for the headline numbers. Then use the sidebar to run one live
prompt, inspect individual cases, tune thresholds, or review cases that need
a human decision. Automated result files are treated as fixed evidence; this
dashboard adds explanations, controls, and review records on top.
    """
)
methodology, selected_path, _calibration_suffix = load_methodology_artifact()
if methodology.get("models"):
    judge_counts = sorted({len(m.get("jury", [])) for m in methodology["models"].values()})
    st.caption("Independent judges per response in this run: " + ", ".join(map(str, judge_counts)) + ". Draft references and scoring anchors are pending clinical review.")

if not methodology.get("rows"):
    st.info("No completed HealthEval benchmark run yet. Explore the draft reference cases, scoring rubrics, or run a live evaluation.")
    st.dataframe([{k: r.get(k) for k in ("id", "health_topic", "expected_triage_label", "review_status")} for r in load_reference_items()], hide_index=True, width="stretch")
    st.stop()

tool_meta = load_tool_meta()
reference_items = load_reference_items()
calibration_examples = load_calibration_examples()
hitl_repo_reviews = load_hitl_reviews_repo()
final_method_rows = list(tool_meta.get("table_final_method", []))
best_variant: dict | None = final_method_rows[0] if final_method_rows else None

panel_table = list(tool_meta.get("table_panel_models", []))
native_table = panel_table or list(tool_meta.get("table_native", []))
triage_table_rows, emergency_table_rows, patient_risk_counts = _patient_risk_tables(
    methodology,
    reference_items,
)

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

st.caption(
    "Read the dashboard in two lanes. Lane 1 checks whether the model recognised "
    "the patient risk in its structured triage JSON. Lane 2 checks whether the "
    "actual answer was safe enough to clear without human review."
)

lane_cols = st.columns(2)
with lane_cols[0]:
    with st.container(border=True):
        st.markdown("**1. Patient Risk Recognition**")
        st.caption(
            "Source: the model's parsed `triage_label` and `referral_action`. "
            "This is the closest dashboard view to danger-sign detection."
        )
        risk_metrics = [
            ("Triage accuracy", "triage_label_ok", "n", "responses",
             "How often the model's label matches the draft reference label."),
            ("RED recall", "red_detected", "red_expected", "RED cases",
             "Among reference RED cases, how often the model emitted RED."),
            ("Emergency action", "urgent_emergency_action", "urgent_expected", "urgent cases",
             "Among urgent reference cases, how often the model emitted refer_emergency."),
        ]
        for col, (label, numerator, denominator, unit, help_text) in zip(
            st.columns(3), risk_metrics
        ):
            k, n = patient_risk_counts[numerator], patient_risk_counts[denominator]
            with col:
                st.metric(label, _pct_or_dash(k / n if n else None), help=help_text)
                st.caption(f"{k}/{n} {unit}" if n else "No measured responses")
        st.caption(
            "These metrics do not judge answer quality. They only compare the "
            "structured triage block to the reference labels."
        )

with lane_cols[1]:
    with st.container(border=True):
        st.markdown("**2. Answer Safety Review**")
        st.caption(
            "Source: the cross-family judge jury over the response text. A RED "
            "patient case can clear here when the answer escalated correctly."
        )
        if best_variant is not None:
            sens = best_variant.get("sensitivity", {}).get("rate")
            spec = best_variant.get("specificity", {}).get("rate")
            review_metric_cols = st.columns(2)
            with review_metric_cols[0]:
                st.metric(
                    "Safety-probe answers routed",
                    _pct_or_dash(sens),
                    help=(
                        "Cases expecting refusal, referral or required red flags whose "
                        "answers were routed to review. A well-handled answer "
                        "can correctly remain unflagged."
                    ),
                )
            with review_metric_cols[1]:
                st.metric(
                    "Other answers cleared",
                    _pct_or_dash(spec),
                    help=(
                        "Cases outside the safety-probe group whose answers "
                        "were left unflagged by the judge jury."
                    ),
                )
        else:
            st.metric("Answer review summary", "—")
        st.caption(_method_label())

st.subheader("Evidence Inventory")
inventory_cols = st.columns(5)
with inventory_cols[0]:
    st.metric(
        "Reference set x panel",
        f"n = {len(reference_items)} x {len(panel_models) or 1}",
        help=(
            f"{expected_violation_count} yellow/red reference cases · "
            f"{expected_clean_count} routine reference cases."
        ),
    )
with inventory_cols[1]:
    st.metric(
        "Judge jury",
        f"{len(jury_models)} judges",
        help=(
            "Cross-family jury: " + ", ".join(f"`{m}`" for m in jury_models)
            if jury_models
            else "Jury list missing from canonical artefact metadata."
        ),
    )
with inventory_cols[2]:
    st.metric(
        "Human reviews",
        f"{hitl_total}",
        help=(
            f"{len(session_reviews)} this browser session · "
            f"{len(hitl_repo_reviews)} from `{PATH_HITL_REVIEWS_JSONL.name}`."
        ),
    )
with inventory_cols[3]:
    st.metric(
        "Judge-memory examples",
        f"{len(calibration_examples)}",
        help="Seed pack at `data/judge_calibration_examples.yaml`.",
    )
with inventory_cols[4]:
    st.metric(
        "Rubric packs",
        f"{len(rubric_pack_files)}",
        help="Versioned YAML files in `data/rubrics/`.",
    )

st.subheader("Patient Risk Recognition By Model")
st.caption(
    "This table uses only the model's structured triage JSON. It answers: "
    "did the model identify the risk and referral action before we judge the prose?"
)
if triage_table_rows:
    st.dataframe(
        pd.DataFrame(triage_table_rows),
        hide_index=True,
        width="stretch",
    )
else:
    st.info("No model triage rows were available in the selected artefact.")

st.subheader("Urgent Case Snapshot")
st.caption(
    "Urgent cases are the fastest reviewer check. RED triage and emergency "
    "referral should be high. `Answer routed to review` is shown separately "
    "because a correct emergency answer can safely clear response review."
)
if emergency_table_rows:
    st.dataframe(
        pd.DataFrame(emergency_table_rows),
        hide_index=True,
        width="stretch",
    )
else:
    st.info("No urgent-case rows were available in the selected artefact.")
st.subheader("Reference Risk Tiers")
st.caption(
    "Each reference case carries a risk tier derived from its expected safety "
    "action. This lets the dashboard separate routine education from cases "
    "where a bad answer could cause more harm."
)
risk_counts = {
    tier: sum(
        1
        for item in reference_items
        if risk_tier_from_expected_action(item.get("expected_safety_action")) == tier
    )
    for tier in REFERENCE_RISK_ORDER
}
risk_cols = st.columns(3)
for idx, tier in enumerate(REFERENCE_RISK_ORDER):
    with risk_cols[idx]:
        st.metric(reference_risk_label(tier), risk_counts[tier])

risk_table = list(tool_meta.get("table_risk_tiers", []))
panel_risk_rows = [
    row
    for row in risk_table
    if row.get("evaluator") == "healtheval_safety_method:panel_mean"
]
if panel_risk_rows:
    risk_df = pd.DataFrame(
        [
            {
                "Reference risk": row.get("reference_risk_label"),
                "Answer-review readout": (
                    "Routine answers cleared"
                    if row.get("reference_risk_tier") == "green"
                    else "Answers routed to review"
                ),
                "Panel mean": f"{float(row.get('success_rate', 0.0)) * 100:.1f}%",
            }
            for row in panel_risk_rows
        ]
    )
    st.table(risk_df)
st.subheader("Answer Safety Review By Model")
st.caption(
    "These rates are judge-jury response-review outcomes. They are not the "
    "same as patient-risk recognition; see the triage table above for that."
)


def _display_evaluator_name(raw: object) -> str:
    name = str(raw or "—")
    if name.startswith("healtheval_safety_method:"):
        return name.split(":", 1)[1]
    return name.replace("_", " ")


healtheval_rows = [
    row for row in native_table
    if str(row.get("evaluator", "")).startswith("healtheval_safety_method")
]

native_chart_rows = []
for row in healtheval_rows:
    name = _display_evaluator_name(row.get("evaluator", "?"))
    sens_rate = row.get("sensitivity", {}).get("rate")
    spec_rate = row.get("specificity", {}).get("rate")
    if sens_rate is None or spec_rate is None:
        continue
    native_chart_rows.append(
        {
            "Evaluator": name,
            "Safety-probe answers routed": float(sens_rate),
            "Other answers cleared": float(spec_rate),
        }
    )

if native_chart_rows:
    df_native = pd.DataFrame(native_chart_rows)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="Safety-probe answers routed",
            x=df_native["Evaluator"],
            y=df_native["Safety-probe answers routed"],
            marker_color="#1d4ed8",
            text=df_native["Safety-probe answers routed"].map(lambda v: f"{v * 100:.0f}%"),
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            name="Other answers cleared",
            x=df_native["Evaluator"],
            y=df_native["Other answers cleared"],
            marker_color="#06aed4",
            text=df_native["Other answers cleared"].map(lambda v: f"{v * 100:.0f}%"),
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
        healtheval_rows,
        title="Per-panel-model answer-review detail — uncertainty intervals",
        caption=(
            "Safety probes expect refusal, referral or required red flags; this "
            "includes one GREEN case. Routing counts answers sent to review, "
            "not independently confirmed errors. Other answers cleared counts "
            "unflagged answers outside that group. The sample is small; a "
            "zero-width empirical interval does not establish certainty."
        ),
        show_credible_intervals=True,
    )
else:
    st.info("Panel evaluator table missing from `tool_meta_evaluation.json`.")
st.subheader("What The HealthEval Safety Method Adds")
st.markdown(
    """
1. **Patient-risk recognition** checks the model's structured triage JSON
   against the reference case labels.
2. **Answer-safety review** checks the actual Hindi answer with an independent
   judge jury and routes unsafe or borderline answers to human review.
3. **Human review** catches disagreements, parse failures, urgent cases, and
   near-threshold answers.
4. **Judge memory** supplies labeled draft or human-reviewed scoring examples.
5. **Versioned rubrics and audit traces** make each score inspectable and
   reproducible.
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
        "Generated from `promptfooconfig.saved.yaml`. The Docker Promptfoo service "
        "runs the first reference prompt across the four saved panel outputs. "
        "Use `HEALTHEVAL_PROMPTFOO_LIMIT=30` only for a full DeepEval pass."
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
- **Safety Thresholds**: stress-test how stricter or looser answer-review
  thresholds affect routing.
- **Judge Memory**: see the examples used to calibrate the judge.
- **Scoring Rubrics**: read the rules behind each score.
- **Audit Trace**: inspect the exact judge-call evidence.
    """
)
st.subheader("Important Limits")
st.markdown(
    f"""
- **Response-evaluation scope.** The dashboard judges whether the model's
  answer is safe, grounded, and complete. It does not score the user's
  medical condition as the final outcome.
- **Two-lane reading.** Use patient-risk recognition for danger-sign detection
  and answer-safety review for whether the response itself needs review. Do not
  collapse those two meanings into one number.
- **Small reference set.** The benchmark has 30 cases. This is useful for
  focused safety analysis, but not enough for broad
  claims across every user group.
- **Judge memory is early.** The seed pack has `{len(calibration_examples)}`
  draft reference examples. It demonstrates the mechanism; accuracy gains require
  more sustained human review.
    """
)
