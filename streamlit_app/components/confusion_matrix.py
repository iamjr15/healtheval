"""2×2 confusion-matrix plot via plotly.

Used by Page 5 (Threshold Tuning) — one matrix per evaluator under the
current slider config.  Inputs are raw counts the page computed against
the n=30 reference set; this component is render-only and never reads
evidence files itself.

Cell layout (per epidemiology convention, ``positive`` = expected
violation per ``data/reference_set.yaml``):

                          Predicted POS    Predicted NEG
    Actual POS  (15)          TP               FN
    Actual NEG  (15)          FP               TN

``sensitivity = TP / (TP + FN)`` and ``specificity = TN / (TN + FP)``;
the helper :func:`compute_confusion` derives both so callers don't have to
re-implement the math next to every render call.
"""
from __future__ import annotations

from dataclasses import dataclass

import plotly.graph_objects as go
import streamlit as st


@dataclass(frozen=True)
class ConfusionCounts:
    """Tally of TP / FP / FN / TN for one evaluator on one prompt set."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def sensitivity(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None

    @property
    def specificity(self) -> float | None:
        denom = self.tn + self.fp
        return self.tn / denom if denom else None


def compute_confusion(
    pairs: list[tuple[bool, bool]],
) -> ConfusionCounts:
    """Tally ``(actual_positive, predicted_positive)`` pairs.

    ``actual_positive`` = the reference-set ground truth (``expected_safety
    _action`` ∈ {refer, urgent}); ``predicted_positive`` = the evaluator
    flagged the response.
    """
    tp = fp = fn = tn = 0
    for actual, predicted in pairs:
        if actual and predicted:
            tp += 1
        elif actual and not predicted:
            fn += 1
        elif (not actual) and predicted:
            fp += 1
        else:
            tn += 1
    return ConfusionCounts(tp=tp, fp=fp, fn=fn, tn=tn)


def render_confusion_matrix(
    counts: ConfusionCounts,
    *,
    title: str = "Confusion matrix",
    height: int = 320,
) -> None:
    """Render a coloured 2×2 confusion matrix with cell counts annotated."""
    z = [[counts.tp, counts.fn], [counts.fp, counts.tn]]
    annotations = [
        [f"TP\n{counts.tp}", f"FN\n{counts.fn}"],
        [f"FP\n{counts.fp}", f"TN\n{counts.tn}"],
    ]
    text_z = [[annotations[i][j] for j in range(2)] for i in range(2)]

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=["Sent to response review", "Not sent to review"],
            y=["Yellow/red reference case", "Green reference case"],
            text=text_z,
            texttemplate="%{text}",
            textfont={"size": 18, "color": "white"},
            colorscale=[
                [0, "#475467"],
                [0.5, "#3b82f6"],
                [1, "#1d4ed8"],
            ],
            showscale=False,
            hovertemplate=(
                "<b>%{y}</b><br>%{x}<br>count=%{z}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        title=title,
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, width="stretch")

    # Sens / spec readout right below the plot — kept as caption so it
    # doesn't compete with neighbouring plots' titles.
    sens = counts.sensitivity
    spec = counts.specificity
    sens_str = f"{sens * 100:.1f}%" if sens is not None else "—"
    spec_str = f"{spec * 100:.1f}%" if spec is not None else "—"
    st.caption(
        f"Yellow/red routed = {sens_str}  ·  Routine cleared = {spec_str}  ·  "
        f"n = {counts.tp + counts.fp + counts.fn + counts.tn}"
    )


__all__ = [
    "ConfusionCounts",
    "compute_confusion",
    "render_confusion_matrix",
]
