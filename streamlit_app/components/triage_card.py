"""RED / AMBER / GREEN triage badge component.

Renders a parsed ``triage_json`` block (per ``data/system_prompt_mnh.yaml``
output schema: ``{triage_label, referral_action, red_flags_detected}``)
as a colour-coded badge with the label, referral action, and any red
flags surfaced.  Used by Live Demo (Step 1 of the dispatch flow) and
Case Detail Modal (Case Explorer drill-down).

The component takes a parsed ``dict`` (or ``None`` for a parse failure)
rather than a raw string — parsing belongs to ``eval.judges
.parse_triage_response``, not the UI layer.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

# Color anchors per the WHO ANC 2016 + MoHFW PMSMA triage taxonomy as
# encoded in ``data/system_prompt_mnh.yaml``.  Keeping these as text /
# emoji semantics rather than hex literals so the dashboard's
# "no hard-coded numbers" grep test (which targets Likert-range decimals)
# isn't confused.
_TRIAGE_VISUAL: dict[str, dict[str, str]] = {
    "RED": {
        "emoji": "🔴",
        "color": "#d92d20",
        "label": "RED — immediate emergency referral",
    },
    "AMBER": {
        "emoji": "🟡",
        "color": "#dc6803",
        "label": "AMBER — needs health-worker review within 24h",
    },
    "GREEN": {
        "emoji": "🟢",
        "color": "#079455",
        "label": "GREEN — routine pregnancy guidance",
    },
}


def render_triage_card(triage: Mapping[str, Any] | None) -> None:
    """Render the badge.  ``triage=None`` ⇔ parse failure (axis 11 INCORRECT)."""
    if triage is None:
        st.error(
            "**Triage JSON did not parse.** The model did not return a valid "
            "triage block, so this case is treated as incorrect for automated "
            "triage scoring and should be reviewed.",
            icon="🚫",
        )
        return

    label_raw = triage.get("triage_label", "")
    label = str(label_raw).upper() if isinstance(label_raw, str) else ""
    visual = _TRIAGE_VISUAL.get(
        label,
        {
            "emoji": "⚪",
            "color": "#475467",
            "label": f"{label or 'UNKNOWN'} — unrecognised triage label",
        },
    )
    referral = triage.get("referral_action", "(missing)")
    red_flags = triage.get("red_flags_detected") or []

    badge_html = (
        f'<div style="display:inline-block;padding:0.4rem 0.9rem;'
        f"border-radius:0.5rem;background:{visual['color']};color:white;"
        f'font-weight:600;font-size:0.95rem;">'
        f"{visual['emoji']} {visual['label']}"
        f"</div>"
    )
    st.markdown(badge_html, unsafe_allow_html=True)

    cols = st.columns(2)
    with cols[0]:
        st.markdown(f"**Recommended action:** `{referral}`")
    with cols[1]:
        st.markdown(f"**Red flags found:** {len(red_flags)}")

    if red_flags:
        with st.expander("Red flags quoted from the model", expanded=False):
            for rf in red_flags:
                st.markdown(f"- {rf}")


__all__ = ["render_triage_card"]
