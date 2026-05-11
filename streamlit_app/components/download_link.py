"""Small wrapper around Streamlit downloads."""
from __future__ import annotations

import streamlit as st


def render_download_link(
    label: str,
    data: bytes,
    *,
    file_name: str,
    mime: str,
    disabled: bool = False,
) -> None:
    """Render a download button with consistent sizing."""
    st.download_button(
        label,
        data=data,
        file_name=file_name,
        mime=mime,
        disabled=disabled,
        width="content",
    )


__all__ = ["render_download_link"]
