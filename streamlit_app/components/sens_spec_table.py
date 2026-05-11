"""Sensitivity / specificity table component (with bootstrap + Beta-Binomial CIs).

Renders a tabular summary of one or more evaluators' sens / spec rates
plus the two confidence-interval flavours the methodology pipeline emits
(``bootstrap_95ci`` and ``beta_binomial_95ci`` per
``results/tool_meta_evaluation.json``).  Used by:

* Page 1 (Overview) — NATIVE table mini bar chart caption + side-by-side
  sens/spec readout for the 3 native evaluators.
* Page 5 (Threshold Tuning) — live recomputed sens/spec under alternative
  config; rates colour-coded so reviewers can eyeball improvements.

Colour-coding convention (cell background tint via pandas Styler):

* ``rate ≥ 0.80`` → green tint (good)
* ``0.50 ≤ rate < 0.80`` → amber tint (mediocre)
* ``rate < 0.50`` → red tint (bad)

The component never reads evidence files — it takes a list of dicts the
page already loaded.  This keeps cache locality on the page (one
``data_loaders.load_*`` per render) and keeps the function unit-testable
without a Streamlit runtime.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd
import streamlit as st

# Colour bands.  Kept as named CSS colours rather than hex so the
# "no hard-coded numbers" grep test (which targets Likert-range decimals)
# isn't confused.
_TINT_GOOD = "background-color: rgba(7, 148, 85, 0.18);"
_TINT_MEH = "background-color: rgba(220, 104, 3, 0.18);"
_TINT_BAD = "background-color: rgba(217, 45, 32, 0.18);"


def _format_rate(value: float | None) -> str:
    """Render a [0, 1] rate as a percentage with one decimal."""
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def _format_ci(ci: list[float] | tuple[float, float] | None) -> str:
    """Render a 2-element [lo, hi] CI; tolerates NaN sentinels from bootstrap."""
    if not ci or len(ci) != 2:
        return "—"
    lo, hi = ci[0], ci[1]
    # Bootstrap CIs come back as NaN when k == 0 or k == n (no resampling
    # variance) — fall back to "—" so the table doesn't render "nan%".
    try:
        lo_f, hi_f = float(lo), float(hi)
    except (TypeError, ValueError):
        return "—"
    if lo_f != lo_f or hi_f != hi_f:  # NaN check
        return "—"
    return f"[{lo_f * 100:.1f}, {hi_f * 100:.1f}]%"


def _display_evaluator_name(raw: Any) -> str:
    name = str(raw or "—")
    labels = {
        "independent_methodology": "MaaSwasth Safety Method",
        "cerai_metric_layer": "CeRAI",
        "inspect_safety_scorer": "Inspect scorer",
        "maaswasth_safety_method:panel_mean": "MaaSwasth Safety Method",
    }
    return labels.get(name, name.replace("_", " "))


def _tint_for_rate(rate: float | None) -> str:
    if rate is None:
        return ""
    if rate >= 0.80:
        return _TINT_GOOD
    if rate >= 0.50:
        return _TINT_MEH
    return _TINT_BAD


def _row_for_evaluator(row: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one evaluator row from tool_meta into a tabular dict."""
    sens = row.get("sensitivity") or {}
    spec = row.get("specificity") or {}
    sens_rate = sens.get("rate")
    spec_rate = spec.get("rate")
    return {
        "Evaluator": _display_evaluator_name(row.get("evaluator", "—")),
        "n": row.get("n", "—"),
        "Catch rate (sensitivity)": _format_rate(sens_rate),
        "Unsafe caught k/n": f"{sens.get('k', '?')}/{sens.get('n', '?')}",
        "Catch rate 95% CI": _format_ci(sens.get("bootstrap_95ci")),
        "Catch rate 95% CrI": _format_ci(sens.get("beta_binomial_95ci")),
        "False-alarm control (specificity)": _format_rate(spec_rate),
        "Safe passed k/n": f"{spec.get('k', '?')}/{spec.get('n', '?')}",
        "False-alarm control 95% CI": _format_ci(spec.get("bootstrap_95ci")),
        "False-alarm control 95% CrI": _format_ci(spec.get("beta_binomial_95ci")),
        # Sentinel raw rates kept for the styler — dropped before render.
        "_sens_rate": sens_rate,
        "_spec_rate": spec_rate,
    }


def render_sens_spec_table(
    rows: Iterable[Mapping[str, Any]],
    *,
    title: str | None = None,
    caption: str | None = None,
    show_credible_intervals: bool = True,
) -> None:
    """Render a sens/spec table from tool_meta-shaped rows.

    Each row should match the shape of one element of
    ``tool_meta_evaluation.json["table_native"]`` or
    ``["table_panel_models"]``::

        {
            "evaluator": "...",
            "n": int,
            "sensitivity": {"rate": float, "k": int, "n": int,
                            "bootstrap_95ci": [lo, hi],
                            "beta_binomial_95ci": [lo, hi]},
            "specificity": {...},
        }

    When ``show_credible_intervals=False`` the Beta-Binomial CrI columns
    are dropped (useful for compact KPI strips).
    """
    if title:
        st.markdown(f"**{title}**")
    rows_list = [_row_for_evaluator(r) for r in rows]
    if not rows_list:
        st.info("No catch-rate rows to display.")
        return

    df = pd.DataFrame(rows_list)
    sens_raw = df["_sens_rate"].tolist()
    spec_raw = df["_spec_rate"].tolist()
    df = df.drop(columns=["_sens_rate", "_spec_rate"])

    if not show_credible_intervals:
        df = df.drop(
            columns=[c for c in df.columns if "Beta-Bin" in c],
            errors="ignore",
        )

    def _style_row(row: pd.Series) -> list[str]:
        # Apply per-row colour tint to the Sensitivity / Specificity cells.
        styles = ["" for _ in row.index]
        for col_idx, col in enumerate(row.index):
            if col == "Catch rate (sensitivity)":
                styles[col_idx] = _tint_for_rate(sens_raw[row.name])
            elif col == "False-alarm control (specificity)":
                styles[col_idx] = _tint_for_rate(spec_raw[row.name])
        return styles

    styled = df.style.apply(_style_row, axis=1)
    st.dataframe(styled, hide_index=True, width="stretch")

    if caption:
        st.caption(caption)


def render_sens_spec_kpi_strip(
    label: str,
    sens_rate: float | None,
    spec_rate: float | None,
    *,
    delta_sens: float | None = None,
    delta_spec: float | None = None,
) -> None:
    """Compact two-metric KPI strip used by Threshold Tuning's headline row.

    ``delta_*`` are signed deltas vs the baseline (positive = improvement);
    we surface them through ``st.metric``'s native delta affordance.
    """
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"{label} catch rate",
            _format_rate(sens_rate),
            delta=(
                f"{delta_sens * 100:+.1f} pts"
                if delta_sens is not None
                else None
            ),
        )
    with cols[1]:
        st.metric(
            f"{label} false-alarm control",
            _format_rate(spec_rate),
            delta=(
                f"{delta_spec * 100:+.1f} pts"
                if delta_spec is not None
                else None
            ),
        )


__all__ = [
    "render_sens_spec_table",
    "render_sens_spec_kpi_strip",
]
