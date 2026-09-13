"""Streamlit navigation entry point."""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from streamlit_app.config import (
    GITHUB_REPO_URL,
)
from streamlit_app.presentation import apply_styles
from streamlit_app.evidence_validator import EvidenceMissing, validate_evidence

APP_DIR = Path(__file__).parent
PAGE_DIR = APP_DIR / "workbench_pages"


def _render_validator_failure(err: EvidenceMissing) -> None:
    """Render a single-page startup error."""
    st.error("Required evidence file could not be loaded", icon="🚫")
    st.markdown(
        f"""
The workbench could not start because a required result file is missing or
malformed.  All other pages are blocked until this is resolved.

**Reason:**

> {err}

The dashboard reads saved evidence files — it never repairs the
underlying file.  Re-run the named script (or curate the named YAML) and
reload this page; the cache key embeds the file mtime so the validator
will pick up the new file automatically.
        """
    )


def _root_redirect() -> None:
    st.switch_page(PAGE_DIR / "1_Overview.py")


def _pages() -> list[st.Page]:  # type: ignore[name-defined]
    """Return the explicit sidebar page list."""
    return [
        st.Page(
            _root_redirect,
            title="Home",
            default=True,
            visibility="hidden",
        ),
        st.Page(
            PAGE_DIR / "1_Overview.py",
            title="Overview",
            url_path="Overview",
        ),
        st.Page(
            PAGE_DIR / "2_Live_Demo.py",
            title="Live evaluation",
            url_path="Live_Demo",
        ),
        st.Page(
            PAGE_DIR / "3_Case_Explorer.py",
            title="Cases",
            url_path="Case_Explorer",
        ),
        st.Page(
            PAGE_DIR / "4_Human_Review_Queue.py",
            title="Human review",
            url_path="Human_Review_Queue",
        ),
        st.Page(
            PAGE_DIR / "5_Safety_Thresholds.py",
            title="Thresholds",
            url_path="Safety_Thresholds",
        ),
        st.Page(
            PAGE_DIR / "6_Judge_Memory.py",
            title="Judge examples",
            url_path="Judge_Memory",
        ),
        st.Page(
            PAGE_DIR / "7_Scoring_Rubrics.py",
            title="Rubrics",
            url_path="Scoring_Rubrics",
        ),
        st.Page(
            PAGE_DIR / "8_Audit_Trace.py",
            title="Judge trace",
            url_path="Audit_Trace",
        ),
        st.Page(
            PAGE_DIR / "9_Evaluator_Stability.py",
            title="Stability",
            url_path="Evaluator_Stability",
        ),
    ]


def main() -> None:
    st.set_page_config(
        page_title="HealthEval",
        layout="wide",
        initial_sidebar_state="auto",
        menu_items={
            "Get Help": GITHUB_REPO_URL or None,
            "Report a bug": (f"{GITHUB_REPO_URL}/issues" if GITHUB_REPO_URL else None),
            "About": (
                "HealthEval Evaluation Workbench — checks whether Hindi "
                "health chatbot answers are safe, source-grounded, "
                "and easy to audit. Automated evidence stays unchanged; "
                "live runs and human reviews are added on top. "
            ),
        },
    )

    apply_styles()

    # Phase 0 validator — fail fast with a clear message rather than
    # rendering half-loaded pages downstream.
    try:
        validate_evidence()
    except EvidenceMissing as err:
        _render_validator_failure(err)
        st.stop()
        return  # for type-checkers; st.stop() raises

    pages = _pages()
    st.navigation(
        {
            "HealthEval": pages[:4],
            "Review": [pages[4], pages[8]],
            "Method": [pages[5], pages[6], pages[7], pages[9]],
        },
        position="sidebar",
        expanded=True,
    ).run()


if __name__ == "__main__":
    main()
