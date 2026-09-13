"""Daily-budget ledger for the Live Demo dispatch button."""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

from .config import DAILY_BUDGET_USD, PATH_BUDGET_TODAY_JSONL

# Planning estimate shown before dispatch; actual rows are appended after calls.
EST_DISPATCH_COST_USD: float = 0.25


def _utc_today_iso() -> str:
    """Return today's UTC date as ``YYYY-MM-DD`` for ledger filtering."""
    return _dt.datetime.now(tz=_dt.timezone.utc).date().isoformat()


def _ts_to_utc_date(ts: str) -> str:
    """Best-effort parse of a ledger row's ``ts`` into a ``YYYY-MM-DD`` UTC date."""
    if not isinstance(ts, str) or not ts:
        return ""
    # Tolerate naive, timezone-aware, and "Z" ISO timestamps.
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        parsed = _dt.datetime.fromisoformat(ts)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc).date().isoformat()


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """Read the ledger, tolerating the trailing-partial-line case."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def read_today_total(path: Path = PATH_BUDGET_TODAY_JSONL) -> float:
    """Sum ``cost_usd`` for entries whose ``ts`` UTC date is today."""
    today = _utc_today_iso()
    total = 0.0
    for row in _read_rows(path):
        if _ts_to_utc_date(str(row.get("ts", ""))) != today:
            continue
        try:
            total += float(row.get("cost_usd", 0.0))
        except (TypeError, ValueError):
            continue
    return total


def check_budget_available(
    cost_usd: float = EST_DISPATCH_COST_USD,
    *,
    path: Path = PATH_BUDGET_TODAY_JSONL,
    daily_budget_usd: float = DAILY_BUDGET_USD,
) -> bool:
    """``True`` when (today's spend) + ``cost_usd`` would still fit the cap."""
    return read_today_total(path) + max(0.0, cost_usd) <= daily_budget_usd


def append_dispatch(
    cost_usd: float,
    session_id: str,
    *,
    path: Path = PATH_BUDGET_TODAY_JSONL,
    prompt_id: str | None = None,
    model: str | None = None,
) -> None:
    """Append one dispatch row.  Uses ``fcntl.flock`` for atomic append.

    The lock protects appends on this filesystem only. Checking a budget and
    dispatching a call are not one transaction, and replicas do not share a
    ledger unless the operator supplies shared storage. Use provider-side
    billing controls for an enforceable spending limit.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "ts": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "cost_usd": float(cost_usd),
        "ip_or_session_id": str(session_id),
    }
    if prompt_id is not None:
        row["prompt_id"] = prompt_id
    if model is not None:
        row["model"] = model
    payload = json.dumps(row, ensure_ascii=False) + "\n"

    # POSIX-only file lock; on Streamlit Cloud / Cloud Run the runtime
    # is Linux so this is reachable.  On Windows dev boxes (no fcntl)
    # we fall back to an unlocked append.
    try:
        import fcntl  # noqa: PLC0415
    except ImportError:  # pragma: no cover — Windows dev-only path
        with path.open("a", encoding="utf-8") as f:
            f.write(payload)
        return

    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, payload.encode("utf-8"))
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def remaining_budget_usd(
    *,
    path: Path = PATH_BUDGET_TODAY_JSONL,
    daily_budget_usd: float = DAILY_BUDGET_USD,
) -> float:
    """Return the (non-negative) headroom left in today's daily cap."""
    return max(0.0, daily_budget_usd - read_today_total(path))


__all__ = [
    "DAILY_BUDGET_USD",
    "EST_DISPATCH_COST_USD",
    "read_today_total",
    "check_budget_available",
    "append_dispatch",
    "remaining_budget_usd",
]
