"""Page 7 — Rubric Packs.

Renders ``data/rubrics/{metric}_v{N}.yaml`` for the reviewer.  Per main
plan the rubric-pack contract the layout has:

* Sidebar — rubric-pack selector + "show all versions" toggle.
* Main panel sections:
  * Identity (metric, version, pass/fail threshold, evidence count)
  * Constitution principles backing the selected pack
  * Ground-truth reference cases and source paragraphs
  * Calibration anchors for the selected metric
  * Scoring scale
  * Score examples (table)
  * Common false positives / false negatives
  * Domain-specific rules
  * Language-specific rules
  * Safety policy
  * Failure categories list with descriptions

Reading goes through ``rubric_loader.load_validated_rubric_packs`` so a
schema drift surfaces as a single-page error rather than a half-rendered
table.  No hard-coded rubric content lives here — every value comes
from the YAML.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from streamlit_app.config import RUBRIC_PACKS_V1, RUBRICS_DIR
from streamlit_app.data_loaders import (
    load_calibration_examples,
    load_constitution,
    load_reference_items,
)
from streamlit_app.rubric_loader import (
    RubricValidationError,
    list_all_pack_keys,
    list_available_pack_keys,
    load_validated_rubric_pack,
)

REF_ID_RE = re.compile(r"\bref-\d{3}\b")
SOURCE_SNIPPET_CHARS = 360
PROMPT_SNIPPET_CHARS = 120


def _plain_option(value: str) -> str:
    return str(value).replace("_", " ")


def _short_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - len("...")].rstrip() + "..."


def _ref_ids_in(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(REF_ID_RE.findall(value))
    if isinstance(value, Mapping):
        out: set[str] = set()
        for item in value.values():
            out |= _ref_ids_in(item)
        return out
    if isinstance(value, list | tuple | set):
        out: set[str] = set()
        for item in value:
            out |= _ref_ids_in(item)
        return out
    return set()


def _principle_rows(principles: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "ID": p.get("id"),
            "Principle": str(p.get("name", "")).replace("_", " "),
            "What it checks": _short_text(p.get("description", ""), 190),
            "Source": _short_text(p.get("source_citation", ""), 140),
        }
        for p in principles
    ]


def _reference_summary_rows(items: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "Ref ID": item.get("id"),
            "Expected action": item.get("expected_safety_action"),
            "Triage": item.get("expected_triage_label"),
            "Referral": item.get("expected_referral_action"),
            "Prompt": _short_text(item.get("hindi_text", ""), PROMPT_SNIPPET_CHARS),
            "Source": _short_text(item.get("source_paragraph", ""), SOURCE_SNIPPET_CHARS),
        }
        for item in items
    ]


st.title("Scoring Rubrics")
st.caption(
    "Trace each rubric from the scoring rule to the constitution principles, "
    "reference-set ground truth, source paragraphs, and judge-memory anchors."
)
with st.sidebar:
    st.header("Choose Rubric")
    show_all_versions = st.toggle(
        "Show older versions too",
        value=False,
        help=(
            "Off: only the current rubric packs. On: every rubric YAML file "
            "in `data/rubrics/`, including older archived versions."
        ),
    )
    if show_all_versions:
        candidate_keys = list_all_pack_keys()
    else:
        # Intersect canonical list with what's on disk so the selector
        # never shows a stem the loader can't resolve.
        on_disk = set(list_available_pack_keys())
        candidate_keys = [k for k in RUBRIC_PACKS_V1 if k in on_disk]

    if not candidate_keys:
        st.error(
            f"No rubric YAMLs found in `{RUBRICS_DIR}` for the current setting."
        )
        st.stop()

    pack_key = st.selectbox(
        "Rubric",
        options=candidate_keys,
        index=0,
        help="Each entry is loaded from `data/rubrics/<key>.yaml`.",
    )
    show_all_reference_cases = st.toggle(
        "Show all reference cases",
        value=False,
        help=(
            "Off: show only reference cases mentioned by this rubric or its "
            "calibration examples. On: show every case in the n=30 set."
        ),
    )
# Load + validate the chosen pack — fail loudly on contract miss.
pack_path = RUBRICS_DIR / f"{pack_key}.yaml"
try:
    pack = load_validated_rubric_pack(pack_path)
except RubricValidationError as err:
    st.error(f"Rubric validation failed: {err}", icon="🚫")
    st.stop()

raw_pack_text = pack_path.read_text()
constitution = load_constitution()
reference_items = load_reference_items()
calibration_examples = load_calibration_examples()
principles_by_id = {
    int(p["id"]): p for p in constitution.get("principles", []) if p.get("id")
}
reference_by_id = {
    str(item.get("id")): item for item in reference_items if item.get("id")
}
principle_ids = [int(pid) for pid in pack.get("constitution_principle_ids") or []]
selected_principles = [
    principles_by_id[pid] for pid in principle_ids if pid in principles_by_id
]
metric_calibration_examples = [
    ex for ex in calibration_examples if str(ex.get("metric")) == str(pack["metric"])
]
linked_ref_ids = sorted(
    _ref_ids_in(pack)
    | _ref_ids_in(raw_pack_text)
    | {
        str(ex.get("ref_id"))
        for ex in metric_calibration_examples
        if ex.get("ref_id")
    }
)
if show_all_reference_cases:
    evidence_items = list(reference_items)
else:
    evidence_items = [
        reference_by_id[ref_id] for ref_id in linked_ref_ids if ref_id in reference_by_id
    ]

st.header(f"{pack['metric']} · {pack['version']}")
description = pack.get("description", "")
if description:
    st.markdown(description)

id_cols = st.columns(4)
with id_cols[0]:
    st.metric("Metric", pack["metric"])
with id_cols[1]:
    st.metric("Version", pack["version"])
with id_cols[2]:
    st.metric("Pass/fail threshold", f"{pack['pass_fail_threshold']:.1f}")
with id_cols[3]:
    st.metric("Evidence cases", len(evidence_items))

st.info(
    "**Evidence chain:** rubric pack -> constitution principles -> reference-set "
    "ground truth -> source paragraphs -> calibration anchors. A score at or above "
    f"**{pack['pass_fail_threshold']:.1f}** passes this rubric."
)

st.subheader("Constitution Principles")
st.caption(
    "These are the judge principles from `data/constitution.yaml` covered by "
    "the selected rubric pack."
)
if selected_principles:
    st.dataframe(
        pd.DataFrame(_principle_rows(selected_principles)),
        hide_index=True,
        width="stretch",
    )
    for principle in selected_principles:
        title = (
            f"{principle.get('id')} · "
            f"{str(principle.get('name', '')).replace('_', ' ')}"
        )
        with st.expander(title, expanded=False):
            st.markdown(str(principle.get("description", "")).strip())
            st.caption(f"Source: {principle.get('source_citation', '—')}")
            anchors = principle.get("scoring_rubric") or {}
            anchor_rows = [
                {"Score": key.replace("score_", ""), "Anchor": value}
                for key, value in anchors.items()
            ]
            if anchor_rows:
                st.dataframe(
                    pd.DataFrame(anchor_rows),
                    hide_index=True,
                    width="stretch",
                )
            if principle.get("example_violation"):
                st.markdown("**Example violation**")
                st.markdown(str(principle.get("example_violation", "")).strip())
else:
    st.info("This rubric pack does not declare constitution principle IDs.")

st.subheader("Ground-Truth Reference Evidence")
st.caption(
    "Reference cases come from `data/reference_set.yaml`. They define the "
    "expected safety action, triage label, referral action, factual checklist, "
    "wrong-answer anchors, and source paragraph."
)
if evidence_items:
    source_count = len({item.get("source_url") for item in evidence_items})
    external_count = sum(
        "EXTERNAL" in str(item.get("source_paragraph") or "")
        for item in evidence_items
    )
    evidence_cols = st.columns(3)
    with evidence_cols[0]:
        st.metric("Reference cases shown", len(evidence_items))
    with evidence_cols[1]:
        st.metric("Unique source URLs", source_count)
    with evidence_cols[2]:
        st.metric("External source notes", external_count)

    st.dataframe(
        pd.DataFrame(_reference_summary_rows(evidence_items)),
        hide_index=True,
        width="stretch",
    )
    for item in evidence_items:
        title = (
            f"{item.get('id')} · {item.get('expected_safety_action')} · "
            f"{_short_text(item.get('hindi_text', ''), 90)}"
        )
        with st.expander(title, expanded=False):
            detail_cols = st.columns(4)
            with detail_cols[0]:
                st.metric("Safety action", str(item.get("expected_safety_action", "—")))
            with detail_cols[1]:
                st.metric("Triage", str(item.get("expected_triage_label", "—")))
            with detail_cols[2]:
                st.metric("Referral", str(item.get("expected_referral_action", "—")))
            with detail_cols[3]:
                st.metric(
                    "Refusal expected",
                    "yes" if item.get("refusal_expected") else "no",
                )
            st.markdown("**Prompt**")
            st.markdown(str(item.get("hindi_text", "")).strip())
            checklist = item.get("factual_checklist") or []
            if checklist:
                st.markdown("**Factual checklist**")
                for point in checklist:
                    st.markdown(f"- {point}")
            wrong_answers = item.get("wrong_answer_examples") or []
            if wrong_answers:
                st.markdown("**Wrong-answer anchors**")
                for point in wrong_answers:
                    st.markdown(f"- {point}")
            st.markdown("**Source paragraph**")
            st.markdown(str(item.get("source_paragraph", "")).strip())
            if item.get("source_url"):
                st.caption(f"Source URL: {item.get('source_url')}")
else:
    st.info(
        "No reference cases are linked from this rubric text or its calibration anchors."
    )

st.subheader("Calibration Anchors")
st.caption(
    "These draft or reviewed examples are the judge-memory references for the selected "
    "metric. The full searchable list lives on Judge Memory."
)
if metric_calibration_examples:
    cal_cols = st.columns(2)
    with cal_cols[0]:
        st.metric("Anchors for this metric", len(metric_calibration_examples))
    with cal_cols[1]:
        st.metric(
            "Failure categories covered",
            len({ex.get("failure_category") for ex in metric_calibration_examples}),
        )
    for ex in metric_calibration_examples:
        title = (
            f"{ex.get('id')} · score {ex.get('human_score', ex.get('reference_score'))} · "
            f"{ex.get('failure_category') or 'positive anchor'}"
        )
        with st.expander(title, expanded=False):
            st.caption(f"Reference case: `{ex.get('ref_id', '—')}`")
            st.markdown("**Prompt**")
            st.code(str(ex.get("prompt", "")).strip(), language="markdown")
            st.markdown("**Answer being scored**")
            st.code(str(ex.get("actual_answer", "")).strip(), language="markdown")
            st.markdown("**Expected behavior**")
            st.markdown(str(ex.get("expected_behaviour", "")).strip())
            st.markdown("**Score provenance and reason**")
            st.markdown(str(ex.get("human_reason") or ex.get("reference_reason", "")).strip())
else:
    st.info("No calibration anchors currently target this metric.")

# Scoring scale.
st.subheader("Scoring scale")
scoring_scale = pack["scoring_scale"]
scale_label = scoring_scale.get("scale", "")
if scale_label:
    st.caption(scale_label)
scale_rows = []
for k, v in scoring_scale.items():
    if k == "scale":
        continue
    scale_rows.append({"score": k, "anchor": v})
if scale_rows:
    st.dataframe(
        pd.DataFrame(scale_rows),
        hide_index=True,
        width="stretch",
    )
# Score examples — anchored to real ref-IDs in the seed packs.
st.subheader("Score examples")
examples_df = pd.DataFrame(pack["score_examples"])
# Sort high→low so reviewers see the "good" anchors before the failures.
if "score" in examples_df.columns:
    examples_df = examples_df.sort_values("score", ascending=False).reset_index(
        drop=True
    )
# Use a vertical card layout for legibility — score_examples often have
# multi-line "why" explanations that don't render well in a tight grid.
for _, row in examples_df.iterrows():
    with st.container(border=True):
        head_cols = st.columns([1, 5])
        with head_cols[0]:
            st.markdown(f"### Score {row['score']}")
        with head_cols[1]:
            st.markdown(f"**Why this score**\n\n{row.get('why', '').strip()}")
        st.markdown(f"**Example response**\n\n{row.get('example_response', '').strip()}")
# False positives / negatives — common reviewer mistakes.
st.subheader("Common Review Mistakes")
fp_col, fn_col = st.columns(2)
with fp_col:
    st.markdown("**False alarms** (marked unsafe but actually fine)")
    fps = pack.get("common_false_positives") or []
    if fps:
        for item in fps:
            st.markdown(f"- {item}")
    else:
        st.info("No entries.")
with fn_col:
    st.markdown("**Missed risks** (marked safe but actually problematic)")
    fns = pack.get("common_false_negatives") or []
    if fns:
        for item in fns:
            st.markdown(f"- {item}")
    else:
        st.info("No entries.")
# Domain + language rules.
rule_cols = st.columns(2)
with rule_cols[0]:
    st.subheader("Domain-specific rules")
    for item in pack.get("domain_specific_rules", []) or []:
        st.markdown(f"- {item}")
with rule_cols[1]:
    st.subheader("Language / script-specific rules")
    for item in pack.get("language_specific_rules", []) or []:
        st.markdown(f"- {item}")
# Safety policy + failure categories.
st.subheader("Safety policy")
st.markdown(pack["safety_policy"].strip())

st.subheader("Failure Categories")
fc_list = pack["failure_categories"]
st.caption(
    f"{len(fc_list)} categories. The Human Review Queue uses this list when "
    "a reviewer labels why an answer failed."
)
fc_cols = st.columns(2)
for i, cat in enumerate(fc_list):
    with fc_cols[i % 2]:
        st.markdown(f"- `{cat}`")
# Provenance footer — tie-out to the underlying YAML for audit.
st.divider()
st.caption(
    f"Source file: `{pack_path.relative_to(RUBRICS_DIR.parent.parent)}`  ·  "
    "validated before rendering."
)
