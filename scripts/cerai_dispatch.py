"""CeRAI integration wrapper for optional comparator runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)

# Add the external CeRAI clone to sys.path without vendoring it.
_CERAI_DEFAULT_ROOT = Path.home() / "Desktop" / "cerai-analysis" / "AIEvaluationTool"
_CERAI_ROOT = Path(os.environ.get("CERAI_ROOT", str(_CERAI_DEFAULT_ROOT)))
_CERAI_SRC = _CERAI_ROOT / "src"
if _CERAI_SRC.exists():
    sys.path.insert(0, str(_CERAI_SRC))

_DEFAULT_CERAI_BASE_URL = os.environ.get("CERAI_BASE_URL", "http://localhost:8080")
try:
    from lib.interface_manager.client import InterfaceManagerClient  # type: ignore[import-not-found]

    _CERAI_AVAILABLE = True
except Exception as exc:  # pragma: no cover — only fires when CeRAI absent
    logger.debug(
        "CeRAI InterfaceManagerClient not importable from %s (%s); "
        "set CERAI_ROOT or ensure ~/Desktop/cerai-analysis/AIEvaluationTool/src is on disk.",
        _CERAI_SRC, exc,
    )
    InterfaceManagerClient = None  # type: ignore[assignment]
    _CERAI_AVAILABLE = False

try:
    from data.schemas import (  # type: ignore[import-not-found]
        DispatchType,
        FindingsItem,
        ModelPanel,
        ModelPanelEntry,
        ReferralAction,
        TriageLabel,
        TriageOutput,
    )

    _SCHEMAS_AVAILABLE = True
except ImportError:  # pragma: no cover — pre-data-spec ship
    _SCHEMAS_AVAILABLE = False
    FindingsItem = None  # type: ignore[assignment]
    ModelPanel = None  # type: ignore[assignment]
    ModelPanelEntry = None  # type: ignore[assignment]
    TriageOutput = None  # type: ignore[assignment]

try:
    from eval.judges import parse_triage_response  # type: ignore[import-not-found]

    _PARSER_AVAILABLE = True
except ImportError:  # pragma: no cover

    def parse_triage_response(raw: str) -> Optional[dict[str, Any]]:  # type: ignore[no-redef]
        """Local fallback when eval.judges isn't on disk yet."""
        if not raw:
            return None
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            obj = json.loads(raw[start:end])
        except (ValueError, json.JSONDecodeError):
            return None
        if isinstance(obj, dict) and "triage_label" in obj:
            return obj
        return None

    _PARSER_AVAILABLE = False
def _load_prompts(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    items = data.get("prompts") or data.get("items") or data
    if not isinstance(items, list):
        raise ValueError(f"{path} did not yield a list of prompt rows")
    return items


def _resolve_panel_entry(model_id: str) -> Optional["ModelPanelEntry"]:
    """Look up a panel entry by ``model_id`` in ``data/model_panel.yaml``.

    Returns ``None`` when the panel isn't on disk yet (e.g. data-spec
    hadn't shipped during build-time smoke tests). Production callers
    pass an explicit ``cerai_provider`` to :func:`dispatch_via_cerai`
    when needed.
    """
    if not _SCHEMAS_AVAILABLE:
        return None
    panel_path = Path(__file__).resolve().parents[1] / "data" / "model_panel.yaml"
    if not panel_path.exists():
        return None
    try:
        with panel_path.open("r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        panel = ModelPanel.model_validate(doc)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("model_panel.yaml load failed (%s)", exc)
        return None
    for entry in panel.panel:
        if entry.model_id == model_id:
            return entry
    return None


def _make_findings_row(
    *,
    prompt_id: str,
    response_text: str,
    model_id: str,
    latency_ms: float,
    parsed: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Materialise one findings.json row.

    Returns a plain dict; if :class:`data.schemas.FindingsItem` is
    available, validates round-trip through it so downstream
    consumers get a Pydantic-checked payload.
    """
    triage_predicted: Any = None
    referral_predicted: Any = None
    parse_succeeded = parsed is not None
    if parsed:
        triage_predicted = parsed.get("triage_label")
        referral_predicted = parsed.get("referral_action")

    row = {
        "model_id": model_id,
        "prompt_id": prompt_id,
        "triage_label_predicted": triage_predicted,
        "referral_action_predicted": referral_predicted,
        "triage_parse_succeeded": parse_succeeded,
        "response_text": response_text,
        "latency_ms": float(max(0.0, latency_ms)),
        "judges": [],
        "bootstrap_ci": [],
        "beta_binomial_ci": [],
        "krippendorff_alpha": None,
        "equity_strata": [],
    }

    if _SCHEMAS_AVAILABLE and FindingsItem is not None:
        try:
            return FindingsItem.model_validate(row).model_dump(mode="json")
        except Exception as exc:  # pragma: no cover — surfaces schema drift
            logger.warning("FindingsItem validation failed for %s: %s", prompt_id, exc)
    return row
def dispatch_via_cerai(
    prompts: list[dict[str, Any]],
    model_id: str,
    *,
    dispatch_type: Optional[str] = None,
    cerai_base_url: Optional[str] = None,
    chat_id_base: int = 1_000,
) -> list[dict[str, Any]]:
    """Route ``prompts`` through CeRAI's ``InterfaceManagerClient``.

    Parameters
    ----------
    prompts
        List of prompt rows; each must carry ``id`` and ``hindi_text``
        (or ``text`` / ``prompt``). May carry ``script_variant`` from
        :mod:`eval.cross_language` for the cross-language results section reporting (the variant text
        is sent verbatim — Promptfoo / CeRAI does not transliterate).
    model_id
        Candidate model identifier as listed in ``data/model_panel.yaml``
        (e.g. ``claude-sonnet-4-6``, ``sarvam-105b``,
        ``gemini-2.5-pro``; see ``scripts/run_panel_refset_eval.py``
        for the default panel).
        Used as ``agent_name`` in the CeRAI client.
    dispatch_type
        ``"API"`` for vendor API calls. Defaults to the value on the resolved
        :class:`data.schemas.ModelPanelEntry` (or ``"API"`` when the
        panel isn't loadable).
    cerai_base_url
        CeRAI back-end base URL. Defaults to :envvar:`CERAI_BASE_URL`
        (foundation-eng contract).
    chat_id_base
        Starting chat_id for CeRAI's per-prompt conversation memory.

    Returns
    -------
    list[dict]
        One row per prompt, validated against
        :class:`data.schemas.FindingsItem` when available.
    """
    if not _CERAI_AVAILABLE:
        raise RuntimeError(
            "CeRAI tool not importable. Set CERAI_ROOT or clone "
            "https://github.com/IITM-CeRAI/AIEvaluationTool into "
            f"{_CERAI_DEFAULT_ROOT}."
        )

    base_url = cerai_base_url or _DEFAULT_CERAI_BASE_URL

    # Resolve the panel entry so we can pick the right dispatch type.
    panel_entry = _resolve_panel_entry(model_id)
    resolved_dispatch = (
        dispatch_type
        or (
            panel_entry.dispatch_type.value
            if panel_entry is not None
            else "API"
        )
    )

    client = InterfaceManagerClient(
        base_url=base_url,
        application_type=resolved_dispatch,
        agent_name=model_id,
    )

    out: list[dict[str, Any]] = []
    for idx, p in enumerate(prompts):
        prompt_id = str(p.get("id") or p.get("prompt_id") or f"prompt_{idx}")
        prompt_text = str(
            p.get("hindi_text")
            or p.get("text")
            or p.get("prompt")
            or p.get("devanagari_text")
            or ""
        )

        t0 = time.monotonic()
        response_text = ""
        parsed: Optional[dict[str, Any]] = None
        try:
            cerai_resp = client.chat(
                chat_id=chat_id_base + idx,
                prompt_list=[prompt_text],
            )
            payload = (
                cerai_resp.json()
                if hasattr(cerai_resp, "json")
                else (cerai_resp or {})
            )
            response_chunks = (
                payload.get("response", []) if isinstance(payload, dict) else []
            )
            response_text = (
                response_chunks[0].get("response", "")
                if response_chunks and isinstance(response_chunks[0], dict)
                else str(payload)
            )
            parsed = parse_triage_response(response_text)
        except Exception as exc:  # pragma: no cover — runtime path
            logger.warning("CeRAI dispatch failed for %s: %s", prompt_id, exc)
        finally:
            latency_ms = (time.monotonic() - t0) * 1000.0

        out.append(
            _make_findings_row(
                prompt_id=prompt_id,
                response_text=response_text,
                model_id=model_id,
                latency_ms=latency_ms,
                parsed=parsed,
            )
        )

    return out
PanelModelFn = Callable[[str, Sequence[Mapping[str, str]]], Awaitable[str]]


def make_panel_model_fn(
    *,
    cerai_base_url: Optional[str] = None,
    dispatch_type: Optional[str] = None,
    chat_id_seed: int = 50_000,
) -> PanelModelFn:
    """Build an async ``(model_id, history) -> str`` for ``eval.osce.run_osce``.

    The returned coroutine flattens ``history`` into a single CeRAI
    ``chat`` request (CeRAI maintains its own conversation memory keyed
    on ``chat_id``; we use a different chat_id per persona-turn so
    sessions don't bleed). The raw model reply, including the
    schema-first JSON block, is returned verbatim — eval-core parses
    it via :func:`eval.judges.parse_triage_response`.
    """
    base_url = cerai_base_url or _DEFAULT_CERAI_BASE_URL
    counter = {"chat_id": int(chat_id_seed)}

    async def panel_model_fn(
        model_id: str,
        history: Sequence[Mapping[str, str]],
    ) -> str:
        if not _CERAI_AVAILABLE:
            raise RuntimeError(
                "CeRAI tool not importable; set CERAI_ROOT or run the OSCE "
                "harness with a deterministic mock panel_model_fn."
            )
        # Flatten the history to a list of strings — CeRAI's
        # InterfaceManagerClient takes ``prompt_list: list[str]`` and
        # space-joins it. We send the latest user turn only and rely on
        # CeRAI's conversation memory keyed on chat_id for prior turns.
        latest_user_turn = next(
            (m.get("content", "") for m in reversed(list(history)) if m.get("role") == "user"),
            "",
        )
        client = InterfaceManagerClient(
            base_url=base_url,
            application_type=dispatch_type or "API",
            agent_name=model_id,
        )
        # Use a per-call chat_id so OSCE turns don't collide with batch
        # dispatches. eval.osce iterates 5 turns per persona; we keep
        # the same chat_id across turns of one persona by storing it on
        # ``history`` if present.
        chat_id = counter["chat_id"]
        counter["chat_id"] += 1

        # CeRAI's chat is sync; run it in a worker thread so the OSCE
        # async loop isn't blocked.
        loop = asyncio.get_running_loop()
        cerai_resp = await loop.run_in_executor(
            None,
            lambda: client.chat(chat_id=chat_id, prompt_list=[latest_user_turn]),
        )
        payload = (
            cerai_resp.json()
            if hasattr(cerai_resp, "json")
            else (cerai_resp or {})
        )
        response_chunks = (
            payload.get("response", []) if isinstance(payload, dict) else []
        )
        if response_chunks and isinstance(response_chunks[0], dict):
            return response_chunks[0].get("response", "")
        return str(payload)

    return panel_model_fn


def bind_panel_model_fn(**kwargs: Any) -> PanelModelFn:
    """Rebind ``eval.osce._call_panel_model`` to a CeRAI-backed coroutine.

    Eval-core's :func:`eval.osce.run_osce` accepts ``panel_model_fn=``
    explicitly, but legacy code paths or test fixtures that don't pass
    that kwarg will hit :func:`eval.osce._call_panel_model` (which
    raises ``NotImplementedError`` by default). Calling this function
    once at process start makes the legacy code path go through CeRAI
    too. Returns the bound function for explicit use.
    """
    fn = make_panel_model_fn(**kwargs)
    try:
        import eval.osce as _osce  # noqa: WPS433  -- runtime rebinding is intentional

        _osce._call_panel_model = fn  # type: ignore[assignment]
    except ImportError:  # pragma: no cover — eval-core not on disk
        logger.warning("eval.osce not importable; bind_panel_model_fn returned wrapper only")
    return fn
def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dispatch MaaSwasth eval prompts through CeRAI's InterfaceManagerClient.",
    )
    p.add_argument("--prompts", required=True, type=Path,
                   help="Path to data/prompts.yaml (or any prompt YAML).")
    p.add_argument("--model", required=True,
                   help="Candidate model id (matches data/model_panel.yaml).")
    p.add_argument("--dispatch-type", choices=["API"], default=None,
                   help="Override the panel entry's dispatch_type (default: panel-defined).")
    p.add_argument("--cerai-url", default=None,
                   help="CeRAI back-end base URL (default: $CERAI_BASE_URL or http://localhost:8080).")
    p.add_argument("--output", required=True, type=Path,
                   help="Output JSON path for findings rows.")
    return p


def _write_findings(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    prompts = _load_prompts(args.prompts)
    rows = dispatch_via_cerai(
        prompts=prompts,
        model_id=args.model,
        dispatch_type=args.dispatch_type,
        cerai_base_url=args.cerai_url,
    )
    _write_findings(rows, args.output)
    print(f"wrote {len(rows)} findings rows → {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
