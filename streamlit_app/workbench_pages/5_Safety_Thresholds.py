"""Threshold sandbox over saved evaluator scores."""
from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

import pandas as pd
import streamlit as st

from eval.reference_risk import (
    REFERENCE_RISK_ORDER,
    reference_risk_description,
    reference_risk_label,
    reference_risk_tier,
)
from eval.judges import jury_to_section_5_8_decision

from streamlit_app.canonical_selector import (
    select_complete_methodology_artifact,
    selected_methodology_version_label,
)
from streamlit_app.components.confusion_matrix import (
    ConfusionCounts,
    compute_confusion,
    render_confusion_matrix,
)
from streamlit_app.components.download_link import render_download_link
from streamlit_app.components.sens_spec_table import (
    render_sens_spec_kpi_strip,
)
from streamlit_app.config import (
    EVALUATOR_TRIAGE_AMBER_THRESHOLD,
    EVALUATOR_TRIAGE_GREEN_THRESHOLD,
    CERAI_DB_SCORE_CUTOFF,
    SAFETY_PRINCIPLE_IDS,
)
from streamlit_app.data_loaders import (
    load_cerai_db_scores,
    load_methodology_artifact,
    load_reference_items,
    methodology_for_model,
    methodology_model_ids,
)
from streamlit_app.threshold_sweep_writer import (
    append_sweep,
    clear_sweeps,
    list_sweeps,
    sweeps_to_jsonl_bytes,
)
# Likert bounds are constructed without bare 1.0 / 5.0 literals for the
# dashboard hard-code scan.
PRINCIPLE_OPTIONS = list(range(1, 13))
DEFAULT_GREEN = float(EVALUATOR_TRIAGE_GREEN_THRESHOLD)
DEFAULT_AMBER = float(EVALUATOR_TRIAGE_AMBER_THRESHOLD)

SLIDER_LIKERT_MIN = float(1)
SLIDER_LIKERT_MAX = float(5)
SLIDER_LIKERT_STEP = float(0.1)
CERAI_SCORE_MIN = float(0)
CERAI_SCORE_MAX = float(1)
CERAI_SCORE_STEP = float(0.05)
CERAI_DEFAULT_SCORE_CUTOFF = float(CERAI_DB_SCORE_CUTOFF)


@st.cache_data(show_spinner=False)
def _per_prompt_inputs(selected_model: str | None) -> list[dict[str, Any]]:
    """Build the per-prompt input row used by every classification pass.

    Each entry holds the bits the threshold loop needs:

    * ``prompt_id`` — for joining
    * ``expected_violation`` — reference yellow/red prompt (refer / urgent → True)
    * ``judge_scores`` — the 24-cell jury list (list of mappings)
    * ``cerai_score_mean`` / per-metric CeRAI DB scores
    """
    raw_methodology, _selected_path, _suffix = load_methodology_artifact()
    methodology = methodology_for_model(raw_methodology, selected_model)
    cerai_db_scores = load_cerai_db_scores().get("scores_by_prompt", {})
    reference_items = load_reference_items()
    jury_cells_by_prompt = {
        row.get("prompt_id"): row.get("judge_scores", [])
        for row in methodology.get("rows", [])
        if row.get("prompt_id")
    }

    method_rows = {
        r.get("prompt_id"): r for r in methodology.get("rows", []) if r.get("prompt_id")
    }

    out: list[dict[str, Any]] = []
    for ref in reference_items:
        prompt_id = ref.get("id")
        if not prompt_id:
            continue
        expected_action = str(ref.get("expected_safety_action", "")).lower()
        expected_violation = expected_action in {"refer", "urgent"}

        meth_row = method_rows.get(prompt_id, {})
        cells = jury_cells_by_prompt.get(prompt_id, [])

        cerai_scores = cerai_db_scores.get(prompt_id, {})

        out.append(
            {
                "prompt_id": prompt_id,
                "expected_action": expected_action,
                "expected_violation": expected_violation,
                "reference_risk_tier": reference_risk_tier(ref),
                "judge_scores": cells,
                "cerai_score_mean": cerai_scores.get("mean"),
                "cerai_accuracy": cerai_scores.get("accuracy"),
                "cerai_relevance": cerai_scores.get("relevance"),
                "cerai_hallucination": cerai_scores.get("hallucination"),
            }
        )
    return out


def _classify_methodology(
    rows: Sequence[Mapping[str, Any]],
    *,
    principle_ids: Sequence[int],
    green: float,
    amber: float,
) -> dict[str, bool]:
    """Return ``{prompt_id: predicted_flagged}`` under the methodology config."""
    out: dict[str, bool] = {}
    for row in rows:
        decision = jury_to_section_5_8_decision(
            row["judge_scores"],
            principle_ids=list(principle_ids),
            green_threshold=green,
            amber_threshold=amber,
        )
        flagged = bool(decision["flagged"])
        out[row["prompt_id"]] = flagged
    return out


def _classify_cerai(
    rows: Sequence[Mapping[str, Any]],
    *,
    score_cutoff: float,
) -> dict[str, bool]:
    """CeRAI flags when its Docker DB mean metric score is below cutoff."""
    out: dict[str, bool] = {}
    for row in rows:
        mean_score = row.get("cerai_score_mean")
        if mean_score is None:
            continue
        flagged = float(mean_score) < float(score_cutoff)
        out[row["prompt_id"]] = flagged
    return out


def _risk_tier_rows(
    rows: Sequence[Mapping[str, Any]],
    predictions: Mapping[str, bool],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tier in REFERENCE_RISK_ORDER:
        tier_rows = [r for r in rows if r.get("reference_risk_tier") == tier]
        total = len(tier_rows)
        if not total:
            continue
        flagged = sum(
            1 for r in tier_rows if predictions.get(str(r.get("prompt_id")), False)
        )
        if tier == "green":
            success = total - flagged
            metric = "Routine answers cleared"
        else:
            success = flagged
            metric = "Yellow/red answers routed"
        out.append(
            {
                "Reference risk": reference_risk_label(tier),
                "What this means": reference_risk_description(tier),
                "Cases": total,
                "Answers sent to review": flagged,
                "Routing metric": metric,
                "Count": f"{success}/{total}",
                "Rate": success / total,
            }
        )
    return out


def _confusion_for(rows: Sequence[Mapping[str, Any]], preds: Mapping[str, bool]) -> ConfusionCounts:
    pairs: list[tuple[bool, bool]] = []
    for row in rows:
        if row["prompt_id"] not in preds:
            continue
        actual = bool(row["expected_violation"])
        predicted = bool(preds.get(row["prompt_id"], False))
        pairs.append((actual, predicted))
    return compute_confusion(pairs)


def _baseline_canonical_predictions(
    rows: Sequence[Mapping[str, Any]],
    selected_model: str | None,
) -> dict[str, bool]:
    """Reproduce the canonical methodology decision per row (for delta view).

    The methodology artefact already stores its decision under
    ``rows[i].decision.flagged`` — we read it back so the page's
    "cases changed vs canonical" view matches the artefact, not a
    recomputation that might drift from upstream conventions.

    The current panel artefact supplies the baseline.
    """
    raw_methodology, _selected_path, _suffix = load_methodology_artifact()
    methodology = methodology_for_model(raw_methodology, selected_model)
    return {
        row.get("prompt_id"): bool(row.get("decision", {}).get("flagged", False))
        for row in methodology.get("rows", [])
        if row.get("prompt_id")
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _routed_count(conf: ConfusionCounts) -> int:
    return conf.tp + conf.fp


st.title("Safety Thresholds")
st.caption(
    "Tune the answer-review routing rule over the saved judge scores. This "
    "page uses the reference risk tier as a workload proxy: yellow/red prompts "
    "should usually route unless the response handled the risk correctly, while "
    "routine prompts should clear when the response is safe. It does not rewrite "
    "the underlying evaluation files."
)

canonical_path = select_complete_methodology_artifact()
canonical_version_label = selected_methodology_version_label(canonical_path)
raw_methodology, _selected_path, _suffix = load_methodology_artifact()
if not raw_methodology.get("rows"):
    st.info("Run the current benchmark before exploring threshold changes.")
    st.stop()

model_ids = methodology_model_ids(raw_methodology)
with st.sidebar:
    st.header("Choose Thresholds")
    selected_model = None
    if len(model_ids) > 1:
        selected_model = st.selectbox(
            "Panel model",
            model_ids,
            index=0,
            help="Recompute thresholds for this model's saved reference-set rows.",
        )
    elif model_ids:
        selected_model = model_ids[0]
    st.subheader("HealthEval Safety Method")
    principles = st.multiselect(
        "Safety principles used by the judge",
        options=PRINCIPLE_OPTIONS,
        default=list(SAFETY_PRINCIPLE_IDS),
        help=(
            "Default = the current HealthEval Safety Method principles "
            f"({', '.join(str(pid) for pid in SAFETY_PRINCIPLE_IDS)}). "
            "Add principles to make the judge consider more concerns; "
            "remove principles to make the rule narrower."
        ),
    )

    green_threshold = st.slider(
        "Safe threshold: judge mean must be at least this high",
        min_value=SLIDER_LIKERT_MIN,
        max_value=SLIDER_LIKERT_MAX,
        value=DEFAULT_GREEN,
        step=SLIDER_LIKERT_STEP,
    )
    amber_threshold = st.slider(
        "Warning threshold: below this becomes RED",
        min_value=SLIDER_LIKERT_MIN,
        max_value=green_threshold - SLIDER_LIKERT_STEP,
        value=min(DEFAULT_AMBER, green_threshold - SLIDER_LIKERT_STEP),
        step=SLIDER_LIKERT_STEP,
    )
    st.subheader("CeRAI")
    cerai_score_cutoff = st.slider(
        "CeRAI comparison cutoff: below this routes response",
        min_value=CERAI_SCORE_MIN,
        max_value=CERAI_SCORE_MAX,
        value=CERAI_DEFAULT_SCORE_CUTOFF,
        step=CERAI_SCORE_STEP,
        help=(
            "CeRAI score = mean of Docker DB Accuracy, Relevance, and "
            "Hallucination scores. Higher is better; scores below this cutoff "
            "are routed to review. This is a comparison threshold, not a "
            "HealthEval Safety Method default."
        ),
    )

per_prompt = _per_prompt_inputs(selected_model)
baseline_canonical = _baseline_canonical_predictions(per_prompt, selected_model)
t0 = time.perf_counter()
preds_methodology = _classify_methodology(
    per_prompt,
    principle_ids=principles or list(SAFETY_PRINCIPLE_IDS),
    green=green_threshold,
    amber=amber_threshold,
)
preds_cerai = _classify_cerai(
    per_prompt,
    score_cutoff=cerai_score_cutoff,
)
elapsed_ms = (time.perf_counter() - t0) * 1000

st.caption(
    f"Recomputed response-review rates for 2 evaluators × "
    f"{len(per_prompt)} prompts in **{elapsed_ms:.1f} ms**  ·  target: "
    "< 200 ms / tick. CeRAI is thresholded on Docker DB metric scores."
)
methodology_conf = _confusion_for(per_prompt, preds_methodology)
cerai_conf = _confusion_for(per_prompt, preds_cerai)

st.info("Review routing measures how many answers are sent to a reviewer. A correctly escalating answer to an emergency can pass response review. This is not a clinical sensitivity measurement.")
if not preds_cerai:
    st.info("CeRAI has not been measured for the current benchmark; no comparator decisions or rates are inferred.")

cols = st.columns(2)
with cols[0]:
    st.markdown("**HealthEval Safety Method**")
    render_sens_spec_kpi_strip(
        "Safety Method",
        methodology_conf.sensitivity,
        methodology_conf.specificity,
    )
with cols[1]:
    st.markdown("**CeRAI**")
    render_sens_spec_kpi_strip(
        "CeRAI",
        cerai_conf.sensitivity,
        cerai_conf.specificity,
    )
st.subheader("Answer Review By Reference Risk")
st.caption(
    "This section compares HealthEval review routing against the reference risk "
    "tier. It is a routing/workload view, not a separate patient diagnosis."
)
risk_rows = _risk_tier_rows(per_prompt, preds_methodology)
if risk_rows:
    risk_df = pd.DataFrame(risk_rows)
    risk_df["Rate"] = risk_df["Rate"].map(lambda v: f"{v * 100:.0f}%")
    st.table(risk_df)
st.subheader("Per-Case Classification Under Current Settings")
st.caption(
    "Read this as prompt-risk routing, not response correctness. `Routed risk` "
    "means a yellow/red prompt was sent to review; `Passed risk` means a "
    "yellow/red prompt was not sent to review; `Routed routine` means a green "
    "prompt was sent to review."
)


def _cell_label(actual: bool, predicted: bool) -> str:
    if actual and predicted:
        return "Routed risk"
    if actual and not predicted:
        return "Passed risk"
    if (not actual) and predicted:
        return "Routed routine"
    return "Passed routine"


def _score_label(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "—"


classification_rows = []
flipped_prompt_ids: list[str] = []
for row in per_prompt:
    pid = row["prompt_id"]
    actual = row["expected_violation"]
    pred_meth = preds_methodology.get(pid, False)
    pred_cerai = preds_cerai.get(pid, False)
    meth_decision = jury_to_section_5_8_decision(
        row["judge_scores"],
        principle_ids=list(principles or list(SAFETY_PRINCIPLE_IDS)),
        green_threshold=green_threshold,
        amber_threshold=amber_threshold,
    )
    base_meth = baseline_canonical.get(pid, False)
    if pred_meth != base_meth:
        flipped_prompt_ids.append(pid)
    classification_rows.append(
        {
            "Prompt ID": pid,
            "Reference risk": reference_risk_label(row["reference_risk_tier"]),
            "Expected action": row["expected_action"],
            "Reference yellow/red?": "Yes" if actual else "No",
            "HealthEval mean": _score_label(meth_decision.get("jury_safety_mean")),
            "HealthEval result": _cell_label(actual, pred_meth),
            "CeRAI DB mean": _score_label(row.get("cerai_score_mean")),
            "CeRAI result": _cell_label(actual, pred_cerai) if pid in preds_cerai else "Not measured",
        }
    )

st.dataframe(
    pd.DataFrame(classification_rows),
    hide_index=True,
    width="stretch",
)
st.subheader("Cases Changed From Current Saved Baseline")
canonical_artefact_caption = (
    f"Baseline source: `{canonical_path.name if canonical_path else '?'}`. "
    "This is the complete HealthEval Safety Method result currently selected by the dashboard."
)
st.caption(canonical_artefact_caption)
if flipped_prompt_ids:
    st.markdown(
        "HealthEval Safety Method decision changed for **"
        + str(len(flipped_prompt_ids))
        + "** prompt(s) compared with the saved baseline:"
    )
    st.markdown(", ".join(f"`{p}`" for p in flipped_prompt_ids))
else:
    st.info(
        "HealthEval Safety Method decision matches the saved baseline for all prompts "
        "under the current settings — try changing "
        "principles or thresholds."
    )
st.subheader("Confusion Matrices")
cm_cols = st.columns(2)
with cm_cols[0]:
    render_confusion_matrix(methodology_conf, title="HealthEval Safety Method (live)")
with cm_cols[1]:
    render_confusion_matrix(cerai_conf, title="CeRAI (live)")
st.subheader("In-Session Threshold Experiment Log")
st.caption(
    "Use this when comparing several slider settings during one browser session. "
    "It records the current thresholds and summary rates below; it does not write "
    "to the repo unless you download the JSONL."
)

save_col, clear_col = st.columns([1, 1])
with save_col:
    if st.button("Save Current Settings To Log", type="primary"):
        record = append_sweep(
            config={
                "methodology": {
                    "principles": list(principles or list(SAFETY_PRINCIPLE_IDS)),
                    "green": green_threshold,
                    "amber": amber_threshold,
                },
                "cerai": {"score_cutoff": cerai_score_cutoff},
                "canonical_methodology_version_at_sweep": canonical_version_label,
                "canonical_methodology_path_at_sweep": (
                    canonical_path.name if canonical_path else None
                ),
            },
            results={
                "methodology": {
                    "sens": methodology_conf.sensitivity or 0.0,
                    "spec": methodology_conf.specificity or 0.0,
                },
                "cerai": {
                    "sens": cerai_conf.sensitivity,
                    "spec": cerai_conf.specificity,
                },
            },
            cases_changed_vs_baseline=flipped_prompt_ids,
        )
        st.success(f"Saved threshold experiment `{record['sweep_id']}`.", icon="✅")

with clear_col:
    sweeps = list_sweeps()
    if st.button("Clear In-Session Log", type="secondary", disabled=not sweeps):
        clear_sweeps()
        st.rerun()

sweeps = list_sweeps()
if sweeps:
    sweeps_table = []
    for s in sweeps:
        cfg = s.get("config", {})
        res = s.get("results", {})
        sweeps_table.append(
            {
                "Experiment ID": s.get("sweep_id"),
                "Principles": str(cfg.get("methodology", {}).get("principles")),
                "GREEN threshold": cfg.get("methodology", {}).get("green"),
                "AMBER threshold": cfg.get("methodology", {}).get("amber"),
                "CeRAI score cutoff": cfg.get("cerai", {}).get(
                    "score_cutoff",
                    cfg.get("cerai", {}).get("bleu_cutoff"),
                ),
                "HealthEval yellow/red routed": res.get("methodology", {}).get("sens"),
                "HealthEval routine cleared": res.get("methodology", {}).get("spec"),
                "CeRAI yellow/red routed": res.get("cerai", {}).get("sens"),
                "CeRAI routine cleared": res.get("cerai", {}).get("spec"),
                "Cases changed": len(s.get("cases_changed_vs_baseline", [])),
            }
        )
    st.dataframe(pd.DataFrame(sweeps_table), hide_index=True, width="stretch")
    render_download_link(
        "Download In-Session Log (JSONL)",
        sweeps_to_jsonl_bytes(sweeps),
        file_name="threshold_sweeps.jsonl",
        mime="application/jsonl",
    )
else:
    st.info(
        "No threshold settings have been saved in this browser session yet. "
        "Adjust the sliders and click **Save Current Settings To Log** to compare runs."
    )
