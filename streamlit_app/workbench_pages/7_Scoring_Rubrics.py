"""Page 7 — Rubric Packs.

Renders ``data/rubrics/{metric}_v{N}.yaml`` for the reviewer.  Per main
plan the rubric-pack contract the layout has:

* Sidebar — rubric-pack selector + "show all versions" toggle.
* Main panel sections:
  * Identity (metric, version, scoring scale, pass/fail threshold)
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

import pandas as pd
import streamlit as st

from streamlit_app.config import RUBRIC_PACKS_V1, RUBRICS_DIR
from streamlit_app.rubric_loader import (
    RubricValidationError,
    list_all_pack_keys,
    list_available_pack_keys,
    load_validated_rubric_pack,
)

st.title("Scoring Rubrics")
st.caption(
    "Read the rules the judge jury uses when scoring answers. Each score is "
    "tagged with a rubric version, so older scoring rules remain auditable "
    "even after a rubric is updated."
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
# Load + validate the chosen pack — fail loudly on contract miss.
pack_path = RUBRICS_DIR / f"{pack_key}.yaml"
try:
    pack = load_validated_rubric_pack(pack_path)
except RubricValidationError as err:
    st.error(f"Rubric validation failed: {err}", icon="🚫")
    st.stop()
st.header(f"{pack['metric']} · {pack['version']}")
description = pack.get("description", "")
if description:
    st.markdown(description)

id_cols = st.columns(3)
with id_cols[0]:
    st.metric("Metric", pack["metric"])
with id_cols[1]:
    st.metric("Version", pack["version"])
with id_cols[2]:
    st.metric("Pass/fail threshold", f"{pack['pass_fail_threshold']:.1f}")

principle_ids = pack.get("constitution_principle_ids")
if principle_ids:
    st.caption(
        "Clusters constitution principles: " + ", ".join(str(i) for i in principle_ids)
    )
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
