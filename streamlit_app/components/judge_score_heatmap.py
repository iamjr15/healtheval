"""Per-(judge × principle) Likert heatmap.

Plotly heatmap whose row count = number of judges, col count = number
of constitutional principles, both **derived from the artefact** at
render time.  The brief calls out: "cell count read from artifact (no
hard-coded 24)" — so the function never assumes 2 judges or 12
principles.  If self-judging avoidance dropped a row, the heatmap
shows fewer judges automatically.

Inputs:
    judge_scores -- list of ``{judge_model_id, principle_id, score}`` dicts
        (or any mapping with those keys; matches ``MethodologyRow.judge_scores``
        and ``eval.judges.JudgeScore`` shape).
    principles -- the 12-item ``data/constitution.yaml`` principles list, used
        to map ``principle_id`` -> human-readable name.  Pass ``None`` to fall
        back to numeric labels.

Likert range is 1..5 (also derived from the score values themselves rather
than hard-coded — the ``zmin`` / ``zmax`` reflect actual data range).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st


def _principle_label(pid: int, principles: Sequence[Mapping[str, Any]] | None) -> str:
    if principles is None:
        return f"P{pid}"
    for p in principles:
        if int(p.get("id", -1)) == int(pid):
            name = p.get("name", "")
            return f"P{pid} · {name}" if name else f"P{pid}"
    return f"P{pid}"


def _short_judge_label(judge_model_id: str) -> str:
    """Truncate ``claude-sonnet-4-6`` style ids for axis labels."""
    if not judge_model_id:
        return "?"
    # Drop a vendor prefix like ``anthropic-`` if present.
    parts = judge_model_id.split("-", 1)
    return parts[1] if parts[0] in {"anthropic", "google", "sarvam"} else judge_model_id


def render_judge_heatmap(
    judge_scores: Sequence[Mapping[str, Any]],
    principles: Sequence[Mapping[str, Any]] | None = None,
    *,
    title: str | None = None,
    key: str | None = None,
) -> None:
    """Render a Plotly heatmap of (judge × principle) Likert cells.

    Parameters
    ----------
    judge_scores:
        The flat per-cell list from ``MethodologyRow.judge_scores`` — any
        mapping with ``judge_model_id``, ``principle_id``, and ``score``.
    principles:
        Optional ``Constitution.principles`` list for human-readable axis
        labels.  When ``None``, falls back to ``P{n}`` numeric labels.
    title:
        Optional figure title (default: empty).
    key:
        Streamlit element key (avoid collisions when multiple heatmaps
        appear on the same page, e.g. inside a modal).
    """
    if not judge_scores:
        st.info(
            "No judge scores are available for this case.",
            icon="ℹ️",
        )
        return

    # Build the score grid by collecting unique judges + principles in
    # the order they appear in the artefact (stable across renders).
    judges_seen: list[str] = []
    principles_seen: list[int] = []
    grid: dict[tuple[str, int], float] = {}
    for cell in judge_scores:
        jid = str(cell.get("judge_model_id", ""))
        try:
            pid = int(cell.get("principle_id"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        try:
            score = float(cell.get("score"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if jid and jid not in judges_seen:
            judges_seen.append(jid)
        if pid not in principles_seen:
            principles_seen.append(pid)
        grid[(jid, pid)] = score

    if not judges_seen or not principles_seen:
        st.info("Score grid is empty — no parseable judge scores.", icon="ℹ️")
        return

    principles_seen.sort()
    z = [
        [grid.get((jid, pid)) for pid in principles_seen]
        for jid in judges_seen
    ]
    x_labels = [_principle_label(pid, principles) for pid in principles_seen]
    y_labels = [_short_judge_label(j) for j in judges_seen]

    # Lazy plotly import so headless tests don't pay the cost.
    import plotly.graph_objects as go  # noqa: PLC0415

    # Likert anchor points come from the actual data range; if the artefact
    # ever ships a wider scale we'd see it without code changes.
    flat_scores = [s for row in z for s in row if s is not None]
    if not flat_scores:
        st.info("Score grid is empty — no scores parsed.", icon="ℹ️")
        return
    zmin = min(flat_scores)
    zmax = max(flat_scores)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x_labels,
            y=y_labels,
            zmin=zmin,
            zmax=zmax,
            colorscale="RdYlGn",
            colorbar=dict(title="Score"),
            hovertemplate=(
                "judge: %{y}<br>principle: %{x}<br>score: %{z}<extra></extra>"
            ),
            text=[[f"{v:.1f}" if v is not None else "·" for v in row] for row in z],
            texttemplate="%{text}",
        )
    )
    fig.update_layout(
        title=title or "",
        xaxis=dict(title="Scoring principle", tickangle=-45),
        yaxis=dict(title="Judge"),
        height=max(220, 60 * len(y_labels) + 120),
        margin=dict(l=10, r=10, t=40 if title else 10, b=80),
    )
    st.plotly_chart(fig, width="stretch", key=key)
    st.caption(
        f"{len(y_labels)} judges × {len(x_labels)} principles "
        f"= {len([s for row in z for s in row if s is not None])} scores."
    )


__all__ = ["render_judge_heatmap"]
