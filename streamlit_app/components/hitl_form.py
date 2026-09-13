"""Reusable HITL review form widget.

Renders a single per-case adjudication form for Page 4 (HITL Queue).
The form's submission is *not* implicitly persisted — :func:`render_hitl_form`
returns a fully-built ``HITLReview`` dict (or ``None`` when the form
hasn't been submitted yet).  The page decides whether to:

* append to ``st.session_state["hitl_reviews"]`` (always, both modes)
* POST to the Cloudflare Pages Function endpoint when persistent mode
  is on AND the reviewer-entered token matched ``HITL_ADMIN_TOKEN``
  via ``hmac.compare_digest`` (per the shipped workbench design the HITL persistence contract Codex r2 #1)

Server-side validation that runs inside the form callback (per the shipped workbench design
the HITL persistence contract "Required protections — always on, both modes"):

* ``failure_category`` must be a member of the rubric pack's
  ``failure_categories`` (passed in by the caller; we fall back to
  ``CANONICAL_FAILURE_CATEGORIES`` if the caller didn't supply one).
* ``human_decision`` is constrained by the radio enum (Streamlit enforces).
* Comment ≤ ``HITL_COMMENT_MAX_CHARS`` chars, promote-reasoning ≤
  ``HITL_PROMOTE_REASONING_MAX_CHARS``; HTML stripped from both.

The page owns queue routing and persistence; this component only builds
and validates one review record.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Mapping

import streamlit as st
from streamlit_app.presentation import risk_name

from streamlit_app.config import (
    CANONICAL_FAILURE_CATEGORIES,
    CERAI_DB_SCORE_CUTOFF,
    HITL_COMMENT_MAX_CHARS,
    HITL_PROMOTE_REASONING_MAX_CHARS,
)

# Closed enums for the form — kept here rather than imported from schemas.py
# because the radio's display order matters (UX), and the enum order in
# the TypedDict is alphabetical-by-author rather than UX-prioritised.
HUMAN_DECISION_OPTIONS: tuple[str, ...] = (
    "correct",
    "incorrect",
    "safe",
    "unsafe",
    "escalate",
)
"""Radio options for ``human_decision``.  Matches HITLReview Literal."""

REVIEWER_ROLE_OPTIONS: tuple[str, ...] = ("developer", "clinician", "panel", "other")

EVALUATOR_TARGETS: tuple[str, ...] = (
    "healtheval_safety_method",
    "cerai",
    "inspect",
)
"""Evaluator targets a human verdict can apply to."""

_HUMAN_DECISION_HELP: dict[str, str] = {
    "correct": "All flagged evaluators got this case right.",
    "incorrect": "One or more evaluators were wrong.  Use the targets multi-select to pin which.",
    "safe": "Model response was actually safe (regardless of evaluator output).",
    "unsafe": "Model response was actually unsafe.",
    "escalate": "Needs clinician sign-off — flag this case for the medical panel.",
}

_HUMAN_DECISION_LABEL: dict[str, str] = {
    "correct": "Automated decision was correct",
    "incorrect": "Automated decision was wrong",
    "safe": "Response is safe",
    "unsafe": "Response is unsafe",
    "escalate": "Needs clinician review",
}

_EVALUATOR_TARGET_LABEL: dict[str, str] = {
    "healtheval_safety_method": "HealthEval",
    "cerai": "CeRAI",
    "inspect": "Inspect scorer",
}

_LEADING_THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_TRIAGE_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\{.*?\"triage_label\".*?\}\s*```\s*",
    re.DOTALL,
)


def _visible_response_text(response: str) -> str:
    text = _LEADING_THINK_RE.sub("", response or "", count=1)
    return _TRIAGE_BLOCK_RE.sub("", text, count=1).strip()


def _human_decision_label(value: str) -> str:
    return _HUMAN_DECISION_LABEL.get(value, value)


def _target_label(value: str) -> str:
    return _EVALUATOR_TARGET_LABEL.get(value, value)


def _plain_label(value: str) -> str:
    return str(value).replace("_", " ").strip().capitalize()


def _route_reason_label(reason: str) -> str:
    if reason.startswith("judge_variance_"):
        parts = reason.split("_")
        score = parts[2] if len(parts) > 2 else "high"
        return f"Judge jury disagreed strongly ({score})"
    labels = {
        "manual_review": "added from Cases",
        "cerai_vs_methodology_disagree": "CeRAI DB score disagreed with HealthEval Safety Method",
        "inspect_vs_methodology_disagree": "Inspect scorer disagreed with HealthEval Safety Method",
        "expected_urgent": "Reference expected urgent referral",
        "near_threshold": "Score was near a decision threshold",
    }
    return labels.get(reason, reason.replace("_", " "))


def _strip_html(text: str) -> str:
    """Drop HTML tags + escape entities to neutralise injection vectors."""
    if not text:
        return ""
    no_tags = re.sub(r"<[^>]+>", "", text)
    return html.unescape(no_tags).strip()


def _evaluator_safety_label(decision_dict: Mapping[str, Any] | None) -> str:
    """Map an evaluator decision dict to ``'safe'`` / ``'unsafe'`` for the record.

    Per the shipped workbench design the HITL persistence contract schema: ``original_evaluators`` is just the binary
    "safe vs unsafe" claim, not the full evaluator decision row.  We
    derive it from the ``flagged`` field shared across evaluators.
    """
    if decision_dict is None:
        return "unsafe"  # missing decision is conservative
    flagged = decision_dict.get("flagged")
    return "unsafe" if flagged else "safe"


def _format_score(value: Any, digits: int = 2) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "?"


def _render_automated_decision(name: str, decision: Mapping[str, Any] | None) -> None:
    st.markdown(f"`{name}`")
    if name == "healtheval_safety_method":
        verdict = _evaluator_safety_label(decision)
        tag = "🚩 needs review" if verdict == "unsafe" else "✅ passes"
        st.markdown(f"**{tag}**")
        if decision is not None and decision.get("jury_safety_mean") is not None:
            st.caption(f"jury_mean = {_format_score(decision['jury_safety_mean'])}")
        return

    if name == "cerai":
        scores = dict((decision or {}).get("db_scores") or {})
        st.markdown(f"**DB mean score = {_format_score(scores.get('mean'))}**")
        st.caption(
            "accuracy = "
            f"{_format_score(scores.get('accuracy'))} · relevance = "
            f"{_format_score(scores.get('relevance'))} · hallucination = "
            f"{_format_score(scores.get('hallucination'))} · cutoff = "
            f"{CERAI_DB_SCORE_CUTOFF:.2f}"
        )
        return

    if name == "inspect":
        st.markdown(
            "**composite score = "
            f"{_format_score((decision or {}).get('composite_score'))}**"
        )
        st.caption(
            "refusal = "
            f"{_format_score((decision or {}).get('refusal_correct'))} · red-flag recall = "
            f"{_format_score((decision or {}).get('red_flag_recall'))}"
        )
        return

    verdict = _evaluator_safety_label(decision)
    st.markdown(f"**{'needs review' if verdict == 'unsafe' else 'passes'}**")


def render_hitl_form(
    *,
    prompt_id: str,
    rubric_version: str = "health_safety_v1",
    failure_categories: list[str] | None = None,
    calibration_example_ids: list[str] | None = None,
    healtheval_decision: Mapping[str, Any] | None = None,
    cerai_decision: Mapping[str, Any] | None = None,
    inspect_decision: Mapping[str, Any] | None = None,
    auto_route_reasons: list[str] | None = None,
    expected_safety_action: str | None = None,
    reference_risk_tier: str | None = None,
    panel_response_excerpt: str | None = None,
    persistence_mode_label: str = "session_local",
) -> dict[str, Any] | None:
    """Render the per-case HITL form.  Returns the review dict on submit, else None.

    The caller is expected to wrap each form in a ``st.expander`` (one per
    queued case) and pass per-case keys derived from ``prompt_id``.

    ``persistence_mode_label`` is recorded into the returned dict's
    ``persistence_mode`` field; the caller decides whether to actually
    persist (POST to Cloudflare endpoint).  We accept it as a parameter
    because the form is rendered per-case but the persistent-mode toggle
    lives on the sidebar — passing it down keeps the side-effect bookkeeping
    near the form.
    """
    fc_options = (
        list(failure_categories)
        if failure_categories
        else list(CANONICAL_FAILURE_CATEGORIES)
    )

    form_key = f"hitl_form__{prompt_id}"

    # Surface the auto-routing reason(s) ABOVE the form (not inside) — that
    # way reviewers see why the case was queued without scrolling.
    if auto_route_reasons:
        st.caption(
            "Sent to human review because: "
            + " · ".join(_route_reason_label(r) for r in auto_route_reasons)
        )

    st.caption(
        f"Patient urgency: {risk_name(reference_risk_tier)} · {rubric_version} · {'Persistent saving' if persistence_mode_label == 'github_api' else 'Session saving'}"
    )
    if panel_response_excerpt:
        st.markdown("**Model answer**")
        st.write(_visible_response_text(panel_response_excerpt))
    eval_specs = [
        ("healtheval_safety_method", healtheval_decision),
        ("cerai", cerai_decision),
        ("inspect", inspect_decision),
    ]
    available = [
        (name, decision)
        for name, decision in eval_specs
        if decision and isinstance(decision.get("flagged"), bool)
    ]
    original_eval_payload = {
        name: _evaluator_safety_label(decision) for name, decision in available
    }
    for name, decision in available:
        st.markdown(
            f"**{_target_label(name)}: {'Flagged' if decision['flagged'] else 'Unflagged'}**"
            + (
                f" · {_format_score(decision['jury_safety_mean'])} / 5"
                if decision.get("jury_safety_mean") is not None
                else ""
            )
        )
    with st.form(key=form_key, clear_on_submit=False):
        reviewer_role = st.selectbox(
            "Reviewer role",
            options=REVIEWER_ROLE_OPTIONS,
            index=0,
            key=f"{form_key}__role",
            format_func=_plain_label,
            help="Tag your role so the audit trail can weight clinician verdicts.",
        )

        human_decision = st.selectbox(
            "Your verdict",
            options=HUMAN_DECISION_OPTIONS,
            index=None,
            placeholder="Choose a verdict",
            key=f"{form_key}__decision",
            format_func=_human_decision_label,
        )
        target_options = [name for name, _ in available]
        if len(target_options) > 1:
            human_decision_targets = st.multiselect(
                "Evaluators reviewed",
                options=target_options,
                default=target_options[:1],
                key=f"{form_key}__targets",
                format_func=_target_label,
            )
        else:
            human_decision_targets = target_options
        failure_category = st.selectbox(
            "Failure category, if any",
            options=[""] + fc_options,
            key=f"{form_key}__category",
            format_func=lambda v: _plain_label(v) if v else "Not specified",
        )
        with st.expander("Additional assessment and future scoring example"):
            model_response_safe = st.checkbox(
                "I also confirm the answer is safe",
                value=False,
                key=f"{form_key}__safe",
                help="Use when assessing the automated decision. A ‘Response is safe/unsafe’ verdict takes precedence.",
            )
            needs_clinician_review = st.checkbox(
                "Request clinician follow-up", value=False, key=f"{form_key}__escalate"
            )
            promote = st.checkbox(
                "Propose as a future scoring example",
                value=False,
                key=f"{form_key}__promote",
            )
            promote_reasoning_raw = st.text_area(
                "Reason for proposing this example",
                max_chars=HITL_PROMOTE_REASONING_MAX_CHARS,
                key=f"{form_key}__promote_reason",
                placeholder="Required only when proposing a scoring example.",
            )

        comment_raw = st.text_area(
            "Review notes",
            value="",
            max_chars=HITL_COMMENT_MAX_CHARS,
            key=f"{form_key}__comment",
            placeholder="Explain the human decision briefly.",
        )

        submitted = st.form_submit_button(
            "Submit review",
            type="primary",
            width="content",
        )

    if not submitted:
        return None
    if failure_category and failure_category not in fc_options:
        st.error(
            f"failure_category `{failure_category}` not in rubric pack — refusing.",
            icon="🚫",
        )
        return None
    if human_decision not in HUMAN_DECISION_OPTIONS:
        st.error(
            f"human_decision `{human_decision}` not in allowed enum — refusing.",
            icon="🚫",
        )
        return None
    if human_decision in {"safe", "unsafe"}:
        model_response_safe = human_decision == "safe"
    needs_clinician_review = needs_clinician_review or human_decision == "escalate"
    if not human_decision_targets:
        st.error("Pick at least one evaluator target for this verdict.", icon="🚫")
        return None
    promote_reasoning_clean = _strip_html(promote_reasoning_raw)
    comment_clean = _strip_html(comment_raw)
    if promote and not promote_reasoning_clean:
        st.error(
            "Adding this case to judge memory requires a short explanation.",
            icon="🚫",
        )
        return None
    if len(comment_clean) > HITL_COMMENT_MAX_CHARS:
        st.error(
            f"Comment exceeds {HITL_COMMENT_MAX_CHARS} chars after sanitisation.",
            icon="🚫",
        )
        return None

    record: dict[str, Any] = {
        "review_id": f"hitl-{prompt_id}-{int(time.time())}",
        "prompt_id": prompt_id,
        "reference_risk_tier": reference_risk_tier,
        "reviewer_role": reviewer_role,
        "original_evaluators": original_eval_payload,
        "human_decision": human_decision,
        "human_decision_targets": list(human_decision_targets),
        "model_response_safe": bool(model_response_safe),
        "needs_clinician_review": bool(needs_clinician_review),
        "failure_category": failure_category,
        "promote_to_calibration": bool(promote),
        "promote_reasoning": promote_reasoning_clean if promote else None,
        "comment": comment_clean,
        "rubric_version_at_review": rubric_version,
        "calibration_example_ids_at_review": list(calibration_example_ids or []),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "client_session_id": st.session_state.get("client_session_id", "anonymous"),
        "persistence_mode": persistence_mode_label,
    }
    return record


__all__ = [
    "HUMAN_DECISION_OPTIONS",
    "REVIEWER_ROLE_OPTIONS",
    "EVALUATOR_TARGETS",
    "render_hitl_form",
]
