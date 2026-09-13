"""Shared, readable presentation for the evidence workbench."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

import streamlit as st

MODEL_NAMES = {
    "sarvam-105b-conversations": "Sarvam Conversations",
    "sarvam-105b": "Sarvam 105B",
    "gemini-2.5-pro": "Gemini 2.5 Pro",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
}


def model_name(value: object) -> str:
    return MODEL_NAMES.get(str(value), str(value or "Not recorded"))


def plain_name(value: object) -> str:
    return str(value or "Not recorded").replace("_", " ").capitalize()


def risk_name(value: object) -> str:
    return {
        "green": "Routine",
        "yellow": "Needs care",
        "amber": "Needs care",
        "red": "Urgent",
    }.get(str(value).lower(), str(value))


def apply_styles() -> None:
    st.html(Path(__file__).with_name("workbench.css"))


def metric_strip(metrics: Sequence[tuple[str, object, str]]) -> None:
    """Responsive numbers with visible definitions, never clipped metric values."""
    cells = "".join(
        f'<div class="he-metric"><span>{escape(label)}</span>'
        f"<strong>{escape(str(value))}</strong><small>{escape(note)}</small></div>"
        for label, value, note in metrics
    )
    st.html(f'<div class="he-metrics">{cells}</div>')


def readable_table(
    rows: Sequence[Mapping[str, Any]], *, label: str, compact_first: bool = False
) -> None:
    """Small evidence tables wrap fully and become labelled rows on narrow screens."""
    if not rows:
        st.info("No matching records.")
        return
    columns = list(rows[0])
    head = "".join(f'<th scope="col">{escape(str(col))}</th>' for col in columns)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td data-label="{escape(str(col), quote=True)}">{escape(str(row.get(col, "—")))}</td>'
            for col in columns
        )
        + "</tr>"
        for row in rows
    )
    st.html(
        f'<table class="he-table{" he-table--compact" if compact_first else ""}" aria-label="{escape(label, quote=True)}">'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )
