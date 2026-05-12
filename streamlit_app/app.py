"""Streamlit navigation entry point."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from streamlit_app.config import (
    GITHUB_REPO_URL,
    PROJECT_ID,
)
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
            title="Live Demo",
            url_path="Live_Demo",
        ),
        st.Page(
            PAGE_DIR / "3_Case_Explorer.py",
            title="Case Explorer",
            url_path="Case_Explorer",
        ),
        st.Page(
            PAGE_DIR / "4_Human_Review_Queue.py",
            title="Human Review Queue",
            url_path="Human_Review_Queue",
        ),
        st.Page(
            PAGE_DIR / "5_Safety_Thresholds.py",
            title="Safety Thresholds",
            url_path="Safety_Thresholds",
        ),
        st.Page(
            PAGE_DIR / "6_Judge_Memory.py",
            title="Judge Memory",
            url_path="Judge_Memory",
        ),
        st.Page(
            PAGE_DIR / "7_Scoring_Rubrics.py",
            title="Scoring Rubrics",
            url_path="Scoring_Rubrics",
        ),
        st.Page(
            PAGE_DIR / "8_Audit_Trace.py",
            title="Audit Trace",
            url_path="Audit_Trace",
        ),
        st.Page(
            PAGE_DIR / "9_Real_World_Robustness.py",
            title="Real-World Robustness",
            url_path="Real_World_Robustness",
        ),
    ]


def main() -> None:
    st.set_page_config(
        page_title="MaaSwasth Evaluation Workbench",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "Get Help": GITHUB_REPO_URL or None,
            "Report a bug": (
                f"{GITHUB_REPO_URL}/issues" if GITHUB_REPO_URL else None
            ),
            "About": (
                "MaaSwasth Evaluation Workbench — checks whether Hindi "
                "maternal-health chatbot answers are safe, source-grounded, "
                "and easy to audit. Automated evidence stays unchanged; "
                "live runs and human reviews are added on top. "
                f"Cloud Run project: `{PROJECT_ID}`."
            ),
        },
    )

    # Phase 0 validator — fail fast with a clear message rather than
    # rendering half-loaded pages downstream.
    try:
        validate_evidence()
    except EvidenceMissing as err:
        _render_validator_failure(err)
        st.stop()
        return  # for type-checkers; st.stop() raises

    st.navigation({"": _pages()}, position="sidebar", expanded=True).run()


if __name__ == "__main__":
    main()
