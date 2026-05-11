"""Session-local threshold sweep log."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

# Streamlit is the runtime store — the same import pattern the data
# loaders use (no-op fallback so the writer is unit-testable headless).
try:  # pragma: no cover — exercised at runtime, not in unit tests
    import streamlit as st  # type: ignore[import-not-found]
except ImportError:
    st = None  # type: ignore[assignment]


SWEEPS_SESSION_KEY = "threshold_sweeps"
CLIENT_SESSION_KEY = "client_session_id"


def _ensure_session_state() -> None:
    if st is None:
        return
    if SWEEPS_SESSION_KEY not in st.session_state:
        st.session_state[SWEEPS_SESSION_KEY] = []
    if CLIENT_SESSION_KEY not in st.session_state:
        st.session_state[CLIENT_SESSION_KEY] = f"anon-{uuid.uuid4().hex[:12]}"


def append_sweep(
    *,
    config: Mapping[str, Any],
    results: Mapping[str, Mapping[str, float]],
    cases_changed_vs_baseline: list[str],
) -> dict[str, Any]:
    """Append one sweep record and return it."""
    _ensure_session_state()
    record: dict[str, Any] = {
        "sweep_id": f"sweep-{int(time.time() * 1000)}",
        "config": dict(config),
        "results": {k: dict(v) for k, v in results.items()},
        "cases_changed_vs_baseline": list(cases_changed_vs_baseline),
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "client_session_id": (
            st.session_state[CLIENT_SESSION_KEY] if st is not None else "headless"
        ),
    }
    if st is not None:
        existing = list(st.session_state.get(SWEEPS_SESSION_KEY, []))
        st.session_state[SWEEPS_SESSION_KEY] = [*existing, record]
    return record


def list_sweeps() -> list[dict[str, Any]]:
    """Return the in-session sweep log."""
    if st is None:
        return []
    _ensure_session_state()
    return list(st.session_state[SWEEPS_SESSION_KEY])


def clear_sweeps() -> None:
    """Reset the in-session sweep log."""
    if st is None:
        return
    _ensure_session_state()
    st.session_state[SWEEPS_SESSION_KEY] = []


def sweeps_to_jsonl_bytes(sweeps: list[Mapping[str, Any]] | None = None) -> bytes:
    """Serialise sweeps to JSONL bytes."""
    if sweeps is None:
        sweeps = list_sweeps()
    payload = "\n".join(json.dumps(s, ensure_ascii=False) for s in sweeps)
    if payload:
        payload += "\n"
    return payload.encode("utf-8")


__all__ = [
    "SWEEPS_SESSION_KEY",
    "CLIENT_SESSION_KEY",
    "append_sweep",
    "list_sweeps",
    "clear_sweeps",
    "sweeps_to_jsonl_bytes",
]
