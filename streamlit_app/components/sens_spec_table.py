"""Response-review rate table component (with bootstrap + Beta-Binomial CIs).

Renders a tabular summary of one or more evaluators' sensitivity/specificity
rates plus the two confidence-interval flavours the methodology pipeline emits
(``bootstrap_95ci`` and ``beta_binomial_95ci`` per
``results/tool_meta_evaluation.json``).  Used by:

* Page 1 (Overview) — NATIVE table mini bar chart caption + side-by-side
  sens/spec readout for the 3 native evaluators.
* Page 5 (Threshold Tuning) — live recomputed sens/spec under alternative
  config; rates colour-coded so reviewers can eyeball improvements.

Routing rates describe workload, so they are not tinted as clinical pass/fail.

The component never reads evidence files — it takes a list of dicts the
page already loaded.  This keeps cache locality on the page (one
``data_loaders.load_*`` per render) and keeps the function unit-testable
without a Streamlit runtime.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import pandas as pd
import streamlit as st

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
        "independent_methodology": "HealthEval Safety Method",
        "cerai_metric_layer": "CeRAI",
        "inspect_safety_scorer": "Inspect scorer",
        "healtheval_safety_method:panel_mean": "HealthEval Safety Method",
    }
    return labels.get(name, name.replace("_", " "))


def _row_for_evaluator(row: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one evaluator row from tool_meta into a tabular dict."""
    sens = row.get("sensitivity") or {}
    spec = row.get("specificity") or {}
    sens_rate = sens.get("rate")
    spec_rate = spec.get("rate")
    return {
        "Evaluator": _display_evaluator_name(row.get("evaluator", "—")),
        "n": row.get("n", "—"),
        "Safety-probe answers routed": _format_rate(sens_rate),
        "Safety-probe routed k/n": f"{sens.get('k', '?')}/{sens.get('n', '?')}",
        "Routing 95% CI": _format_ci(sens.get("bootstrap_95ci")),
        "Routing 95% CrI": _format_ci(sens.get("beta_binomial_95ci")),
        "Other answers cleared": _format_rate(spec_rate),
        "Other cleared k/n": f"{spec.get('k', '?')}/{spec.get('n', '?')}",
        "Other-clear 95% CI": _format_ci(spec.get("bootstrap_95ci")),
        "Other-clear 95% CrI": _format_ci(spec.get("beta_binomial_95ci")),
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

    if not show_credible_intervals:
        df = df.drop(
            columns=[c for c in df.columns if "CrI" in c],
            errors="ignore",
        )

    st.dataframe(df, hide_index=True, width="stretch")

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

    ``delta_*`` are signed deltas vs the baseline (not clinical improvements);
    we surface them through ``st.metric``'s native delta affordance.
    """
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            f"{label} safety-probe routed",
            _format_rate(sens_rate),
            delta_color="off",
            delta=(
                f"{delta_sens * 100:+.1f} pts"
                if delta_sens is not None
                else None
            ),
        )
    with cols[1]:
        st.metric(
            f"{label} other answers cleared",
            _format_rate(spec_rate),
            delta_color="off",
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
