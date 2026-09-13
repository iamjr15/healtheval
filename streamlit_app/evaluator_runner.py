"""Live Demo dispatch helper — wraps ``eval.judges.judge_panel`` for Streamlit.

Mirrors the offline ``scripts/run_panel_refset_eval.py`` flow at
single-prompt granularity:

1. Send the user's Hindi prompt to the selected panel model with the shared
   system prompt loaded from ``data/system_prompt_health.yaml``.
2. Parse the schema-first triage block via
   ``eval.judges.parse_triage_response``.
3. Score the response with the configured cross-family jury, with
   self-judging avoidance applied when the target model is also a judge.
4. Aggregate the jury into the single final HealthEval response-evaluation
   decision used by the saved n=30 x panel evidence.

**Scoring contracts:**

- **Jury is never hard-coded.**  The selected canonical methodology
  artefact carries a ``jury: list[str]`` field listing the judge ids
  used for the frozen reference-set run; we resolve those ids against
  ``eval.judges.DEFAULT_JURY`` to build the live ``JudgeConfig`` tuple.
  If the artefact's jury can't be resolved, the dispatch fails fast
  with a clear error rather than silently using a different jury than
  the evidence files were scored with.
- **60-second timeout per vendor call.**  Each judge call is wrapped
  in a ``ThreadPoolExecutor.future.result(timeout=60)`` so a hung
  vendor doesn't pin the Streamlit server.  Timeouts surface as a
  failed cell (score=1.0, the conservative parse-failure default).
- **Decision settings come from one shared config.**  The live demo and
  offline panel runner both import ``eval.final_method`` so the dashboard
  cannot drift from the measured artefacts.

This module is import-safe in test environments without API keys —
the actual vendor calls are deferred until ``dispatch_one`` runs.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, Sequence

from .config import REPO_ROOT
from .data_loaders import load_methodology_artifact

# Make the eval/ + data/ packages importable from the Streamlit container.
# scripts/run_panel_refset_eval.py uses the same trick.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import judges as _judges_mod  # noqa: E402
from eval.final_method import final_safety_method_config  # noqa: E402
from eval.panel_clients import (  # noqa: E402
    DEFAULT_LIVE_PANEL_MODEL_ID,
    PANEL_MODEL_IDS,
    call_panel_model,
)

VENDOR_CALL_TIMEOUT_SEC: int = 60
DEFAULT_PANEL_MODEL_ID: str = DEFAULT_LIVE_PANEL_MODEL_ID
LIVE_PANEL_MODEL_IDS: tuple[str, ...] = PANEL_MODEL_IDS
_DOTENV_LOADED = False


def _load_local_env_once() -> None:
    """Load local ``.env`` for Streamlit without overriding real env vars."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv  # type: ignore[import-not-found]

            load_dotenv(env_path, override=False)
        except Exception:  # noqa: BLE001
            # If python-dotenv is unavailable, the page still shows the
            # standard missing-key state instead of failing at import time.
            pass
    _DOTENV_LOADED = True
# Live API key probing — surface-level "is the demo dispatchable" check.
@dataclass(frozen=True)
class LiveApiStatus:
    sarvam_ok: bool
    google_ok: bool
    anthropic_ok: bool

    @property
    def all_ok(self) -> bool:
        return self.sarvam_ok and self.google_ok and self.anthropic_ok

    @property
    def missing(self) -> list[str]:
        miss: list[str] = []
        if not self.sarvam_ok:
            miss.append("SARVAM_API_KEY")
        if not self.google_ok:
            miss.append("GOOGLE_API_KEY")
        if not self.anthropic_ok:
            miss.append("ANTHROPIC_API_KEY")
        return miss


def probe_live_api_keys() -> LiveApiStatus:
    """Return which keys are present in the container env.

    Cloud Run injects these via Secret Manager bindings; locally they're
    set in ``.env``.  We never *use* the keys here — we just check they
    exist so the Live Demo page can render a clear "Live demo disabled"
    banner before the user clicks the dispatch button.
    """
    _load_local_env_once()
    return LiveApiStatus(
        sarvam_ok=bool(os.environ.get("SARVAM_API_KEY")),
        google_ok=bool(os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")),
        anthropic_ok=bool(os.environ.get("ANTHROPIC_API_KEY")),
    )
# Jury resolution — driven by the canonical artefact metadata, not a hard-
# coded tuple.  If a future re-run swaps in a different judge family the
# Live Demo follows automatically.
def _resolve_jury_from_artifact(
    judge_ids: Sequence[str],
) -> tuple[_judges_mod.JudgeConfig, ...]:
    """Map artefact ``jury`` ids to the ``DEFAULT_JURY`` ``JudgeConfig`` slots.

    ``eval.judges.DEFAULT_JURY`` is the canonical registry of judge
    routing records (vendor, model_id, family).  Each artefact stores
    just the ``judge_id`` strings (e.g. ``"anthropic-claude-sonnet-4-6"``);
    we look those up against the registry so the live jury exactly
    matches the offline jury that produced the frozen evidence.
    """
    by_id = {j.judge_id: j for j in _judges_mod.DEFAULT_JURY}
    resolved: list[_judges_mod.JudgeConfig] = []
    missing: list[str] = []
    for jid in judge_ids:
        slot = by_id.get(jid)
        if slot is None:
            missing.append(jid)
        else:
            resolved.append(slot)
    if missing:
        raise RuntimeError(
            "Cannot resolve canonical-artefact jury against DEFAULT_JURY: "
            f"missing {missing}.  Add a JudgeConfig for each missing id "
            "in eval/judges.py before dispatching live."
        )
    if not resolved:
        raise RuntimeError(
            "Selected methodology artefact lists an empty jury — the live "
            "demo refuses to dispatch with no judges."
        )
    return tuple(resolved)


def jury_from_canonical() -> tuple[tuple[_judges_mod.JudgeConfig, ...], list[str]]:
    """Return ``(jury_tuple, judge_ids)`` resolved from the canonical artefact.

    Raises ``FileNotFoundError`` when the canonical selector returns
    nothing (no complete methodology run on disk yet).
    """
    artefact, _selected, _suffix = load_methodology_artifact()
    judge_ids_raw = artefact.get("jury", []) or [j.judge_id for j in _judges_mod.configured_jury()]
    judge_ids = [str(j) for j in judge_ids_raw]
    return _resolve_jury_from_artifact(judge_ids), judge_ids
# Final method config.
def load_final_safety_method_config() -> dict[str, Any]:
    """Return the same final method config used by the offline panel runner."""
    cfg = final_safety_method_config()
    cfg.setdefault("union_with_response_triage", False)
    return cfg


def _constitution_subset(principle_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Return constitution rows for the final method's principle ids."""
    wanted = {int(pid) for pid in principle_ids}
    subset = [
        dict(principle)
        for principle in _judges_mod.load_constitution()
        if int(principle.get("id", principle.get("principle_id", 0))) in wanted
    ]
    if len(subset) != len(wanted):
        found = {
            int(principle.get("id", principle.get("principle_id", 0)))
            for principle in subset
        }
        raise RuntimeError(
            "Final method principle ids are not fully present in constitution: "
            f"missing {sorted(wanted - found)}"
        )
    return subset


def _decision_under_calibration(
    jury_scores: Sequence[Any],
    calib_cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate jury scores under one calibration variant's params."""
    pids = [int(p) for p in calib_cfg.get("principle_ids") or ()]
    green_t = float(calib_cfg.get("green_threshold"))  # type: ignore[arg-type]
    amber_t = float(calib_cfg.get("amber_threshold"))  # type: ignore[arg-type]

    decision = _judges_mod.jury_to_section_5_8_decision(
        jury_scores,
        principle_ids=pids,
        green_threshold=green_t,
        amber_threshold=amber_t,
    )
    decision["calibration_id"] = calib_cfg.get("id", "")
    decision["principle_ids_used"] = pids
    decision["green_threshold"] = green_t
    decision["amber_threshold"] = amber_t
    decision["union_with_response_triage"] = False
    return decision
# Vendor calls.
def _call_selected_panel(
    model_id: str, system_prompt: str, user_prompt: str
) -> tuple[str, float]:
    """Synchronous selected-panel call (mirrors the offline panel runner)."""
    _load_local_env_once()
    panel = call_panel_model(model_id, system_prompt, user_prompt)
    return panel.response, panel.latency_sec


def _wrap_safe_call_with_timeout(
    timeout_sec: int = VENDOR_CALL_TIMEOUT_SEC,
):
    """Monkey-patch ``eval.judges._safe_call_judge`` for one dispatch."""
    original = _judges_mod._safe_call_judge

    def _call_original(judge, prompt):  # type: ignore[no-untyped-def]
        # Streamlit can reload modules while a long live run is in flight.
        # eval.judges._safe_call_judge intentionally looks itself up through
        # sys.modules, so make that lookup resilient inside worker threads.
        sys.modules.setdefault(_judges_mod.__name__, _judges_mod)
        try:
            return original(judge, prompt)
        except KeyError as exc:
            if str(exc).strip("'") != _judges_mod.__name__:
                raise
            sys.modules[_judges_mod.__name__] = _judges_mod
            return original(judge, prompt)

    def _wrapped(judge, prompt):  # type: ignore[no-untyped-def]
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_call_original, judge, prompt)
        try:
            return future.result(timeout=timeout_sec)
        except _TimeoutError:
            future.cancel()
            # Match the original's "judge call failed" return contract
            # (None) so judge_panel falls back to the worst-Likert score.
            return None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    return original, _wrapped
# Public dispatch.
@dataclass
class DispatchResult:
    """Container the Live Demo page consumes.

    Kept as a dataclass (not a TypedDict) so the page sees attribute access
    + IDE completion at the ``.``-call site rather than ``["..."]`` lookups.
    """

    response: str
    response_latency_sec: float
    triage_parsed: dict[str, Any] | None
    judge_scores: list[dict[str, Any]]  # [{judge_model_id, principle_id, score, rationale?}]
    judge_mean: float | None
    final_decision: dict[str, Any] | None
    panel_model_id: str
    judge_ids: list[str]
    reference_risk_tier: str | None = None
    error: str | None = None


def dispatch_one(
    prompt: str,
    system_prompt: str,
    *,
    panel_model_id: str = DEFAULT_PANEL_MODEL_ID,
    jury: Sequence[_judges_mod.JudgeConfig] | None = None,
    judge_ids: Sequence[str] | None = None,
    reference_risk_tier: str | None = None,
    timeout_sec: int = VENDOR_CALL_TIMEOUT_SEC,
    progress_cb: Any | None = None,
    principle_ids_override: Sequence[int] | None = None,
    max_judge_workers: int = 1,
    max_judge_attempts: int | None = None,
    calibration_k: int = 3,
    guarantee_decision: bool = False,
) -> DispatchResult:
    """Dispatch one Hindi prompt end-to-end for the live Safety Method demo.

    Parameters
    ----------
    prompt:
        The Hindi user prompt the reviewer entered.  Length validation
        belongs to the page; this layer trusts the caller.
    system_prompt:
        The shared health system prompt body (loaded from
        ``data/system_prompt_health.yaml``).
    jury:
        Override the resolved jury — passing ``None`` loads from the
        canonical methodology artefact.  Tests pass an explicit fake.
    judge_ids:
        Echoed into the result for telemetry.  When ``None`` the resolved
        jury's ``judge_id`` attributes are used.
    reference_risk_tier:
        Optional test-case risk context: ``green``, ``yellow``, or ``red``.
        This is reference metadata for response scoring, not model triage.
    timeout_sec:
        Per-vendor-call timeout (default 60s).
    progress_cb:
        Optional ``callable(stage: str, payload: dict)`` invoked at each
        sub-step (panel done, per-judge call done, etc.) so the page
        can update a progress bar.
    principle_ids_override:
        Optional safety-principle subset.  The full single-prompt demo leaves
        this unset; the live multi-turn tab uses a smaller subset for latency.
    max_judge_workers:
        Parallel judge-cell workers passed through to ``judge_panel``.
    max_judge_attempts:
        Retry cap per judge cell.  ``None`` keeps the judge module default.
    calibration_k:
        Number of retrieved calibration anchors per judge cell.
    guarantee_decision:
        When true, a judge-layer outage becomes an explicit AMBER review
        decision instead of a missing result.  Panel-call failures still surface
        as errors because there is no response to score.
    """
    if jury is None:
        jury, resolved_ids = jury_from_canonical()
        if judge_ids is None:
            judge_ids = resolved_ids
    if judge_ids is None:
        judge_ids = [j.judge_id for j in jury]

    if panel_model_id not in LIVE_PANEL_MODEL_IDS:
        raise ValueError(f"Unsupported panel model: {panel_model_id}")

    # 1. Panel call, with timeout.
    panel_text = ""
    panel_latency = 0.0
    panel_err: str | None = None

    def _panel_runner() -> tuple[str, float]:
        return _call_selected_panel(panel_model_id, system_prompt, prompt)

    try:
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(_panel_runner)
        try:
            panel_text, panel_latency = fut.result(timeout=timeout_sec)
        except _TimeoutError:
            fut.cancel()
            raise
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    except _TimeoutError:
        panel_err = (
            f"{panel_model_id} panel call exceeded {timeout_sec}s timeout — "
            "vendor may be rate-limited.  Try again later."
        )
    except Exception as exc:  # noqa: BLE001
        panel_err = f"{type(exc).__name__}: {exc}"

    if progress_cb:
        progress_cb(
            "panel_done",
            {"text_len": len(panel_text), "latency_sec": panel_latency, "error": panel_err},
        )

    triage = _judges_mod.parse_triage_response(panel_text) if panel_text else None

    method_cfg: dict[str, Any] | None = None
    constitution_subset: list[dict[str, Any]] | None = None
    jury_err: str | None = None
    if panel_err is None:
        try:
            method_cfg = load_final_safety_method_config()
            if principle_ids_override is not None:
                method_cfg = dict(method_cfg)
                method_cfg["principle_ids"] = [
                    int(pid) for pid in principle_ids_override
                ]
            constitution_subset = _constitution_subset(
                [int(p) for p in method_cfg.get("principle_ids") or ()]
            )
        except Exception as exc:  # noqa: BLE001
            jury_err = (
                f"Failed to load HealthEval Safety Method config: "
                f"{type(exc).__name__}: {exc}"
            )

    # 2. Jury — wrap _safe_call_judge with a per-call timeout + progress hook.
    original, wrapped = _wrap_safe_call_with_timeout(timeout_sec)

    call_state = {"n": 0}
    call_lock = Lock()
    defer_progress_events = int(max_judge_workers) > 1
    deferred_progress_events: list[dict[str, Any]] = []

    def _wrapped_with_progress(judge, judge_prompt):  # type: ignore[no-untyped-def]
        with call_lock:
            call_state["n"] += 1
            call_n = call_state["n"]
        t0 = time.time()
        result = wrapped(judge, judge_prompt)
        if progress_cb:
            payload = {
                "n": call_n,
                "judge_id": judge.judge_id,
                "latency_sec": time.time() - t0,
                "ok": result is not None,
            }
            if defer_progress_events:
                with call_lock:
                    deferred_progress_events.append(payload)
            else:
                progress_cb("judge_call_done", payload)
        return result

    judge_scores_raw: list[Any] = []
    if panel_err is None and jury_err is None:
        try:
            judge_scores_raw = list(
                _judges_mod.judge_panel(
                    prompt=prompt,
                    response_dict={
                        "response": panel_text,
                        "triage_json": triage or {},
                        "reference_risk_tier": reference_risk_tier,
                    },
                    panel_model_id=panel_model_id,
                    jury=jury,
                    constitution=constitution_subset,
                    rubric_pack_version="health_safety_v1",
                    retrieve_calibration=True,
                    calibration_k=calibration_k,
                    prompt_template_version="health_live_v1",
                    dataset_version="healtheval_health_v1",
                    strategy_version=f"health_live_v1:{panel_model_id}",
                    max_workers=max(1, int(max_judge_workers)),
                    max_judge_attempts=max_judge_attempts,
                    call_judge_fn=_wrapped_with_progress,
                )
            )
        except Exception as exc:  # noqa: BLE001
            jury_err = f"{type(exc).__name__}: {exc}"
        if progress_cb and deferred_progress_events:
            for payload in sorted(
                deferred_progress_events,
                key=lambda item: int(item.get("n", 0)),
            ):
                progress_cb("judge_call_done", payload)

    # 3. Serialise per-cell to plain dicts so the UI doesn't depend on the
    #    Pydantic vs dataclass branch in eval.judges.
    judge_scores_dicts: list[dict[str, Any]] = []
    for cell in judge_scores_raw:
        # JudgeScore (Pydantic or dataclass) always carries ``score`` —
        # we never invent a fallback Likert value, so the no-hard-coded-
        # Likert grep test stays happy.  A missing attr raises and we
        # drop the cell rather than silently fabricating a score.
        if isinstance(cell, Mapping):
            score_attr = cell.get("score")
            judge_model_id = cell.get("judge_model_id", "")
            principle_id = cell.get("principle_id", 0)
            rationale = cell.get("rationale", "") or ""
            judge_parse_succeeded = bool(cell.get("judge_parse_succeeded", True))
            judge_error_type = cell.get("judge_error_type")
        else:
            score_attr = getattr(cell, "score", None)
            judge_model_id = getattr(cell, "judge_model_id", "")
            principle_id = getattr(cell, "principle_id", 0)
            rationale = getattr(cell, "rationale", "") or ""
            judge_parse_succeeded = bool(getattr(cell, "judge_parse_succeeded", True))
            judge_error_type = getattr(cell, "judge_error_type", None)
        if score_attr is None:
            continue
        try:
            judge_scores_dicts.append(
                {
                    "judge_model_id": judge_model_id,
                    "principle_id": int(principle_id),
                    "score": float(score_attr),
                    "rationale": rationale,
                    "judge_parse_succeeded": judge_parse_succeeded,
                    "judge_error_type": judge_error_type,
                }
            )
        except (TypeError, ValueError):
            continue

    # 4. Compute the one final safety decision used by the saved panel run.
    final_decision: dict[str, Any] | None = None
    if judge_scores_raw and not jury_err and method_cfg is not None:
        try:
            final_decision = _decision_under_calibration(judge_scores_raw, method_cfg)
        except Exception as exc:  # noqa: BLE001
            final_decision = {
                "calibration_id": method_cfg.get("id", "healtheval_safety_method"),
                "error": f"{type(exc).__name__}: {exc}",
            }
    elif (
        guarantee_decision
        and panel_err is None
        and method_cfg is not None
        and constitution_subset is not None
    ):
        principle_ids = [int(p) for p in method_cfg.get("principle_ids") or ()]
        expected_cells = max(1, len(jury)) * max(1, len(principle_ids))
        final_decision = {
            "triage_label": "AMBER",
            "flagged": True,
            "jury_safety_mean": None,
            "n_cells": 0,
            "n_total_cells": expected_cells,
            "n_failed_judge_cells": expected_cells,
            "judge_score_incomplete": True,
            "missing_principle_ids": principle_ids,
            "routing_reason": "judge_layer_unavailable",
            "judgment_degraded": True,
            "judgment_degraded_reason": jury_err or "no judge scores returned",
            "calibration_id": method_cfg.get("id", "healtheval_safety_method"),
            "principle_ids": principle_ids,
            "principle_ids_used": principle_ids,
            "green_threshold": method_cfg.get("green_threshold"),
            "amber_threshold": method_cfg.get("amber_threshold"),
            "union_with_response_triage": False,
        }
    judge_mean = (
        final_decision.get("jury_safety_mean")
        if isinstance(final_decision, dict)
        else None
    )

    err_msg = panel_err or (
        None if guarantee_decision and final_decision is not None else jury_err
    )
    return DispatchResult(
        response=panel_text,
        response_latency_sec=panel_latency,
        triage_parsed=triage,
        judge_scores=judge_scores_dicts,
        judge_mean=judge_mean,
        final_decision=final_decision,
        panel_model_id=panel_model_id,
        judge_ids=list(judge_ids),
        reference_risk_tier=reference_risk_tier,
        error=err_msg,
    )


def load_system_prompt_v2() -> str:
    """Read the v2 system prompt body from ``data/system_prompt_health.yaml``."""
    import yaml  # noqa: PLC0415

    path = Path(REPO_ROOT) / "data" / "system_prompt_health.yaml"
    with path.open() as f:
        doc = yaml.safe_load(f)
    sp = doc.get("system_prompt") or doc.get("prompt") or ""
    if isinstance(sp, dict):
        sp = sp.get("text") or sp.get("body") or ""
    return str(sp).strip()


__all__ = [
    "DispatchResult",
    "LiveApiStatus",
    "DEFAULT_PANEL_MODEL_ID",
    "LIVE_PANEL_MODEL_IDS",
    "VENDOR_CALL_TIMEOUT_SEC",
    "probe_live_api_keys",
    "jury_from_canonical",
    "load_final_safety_method_config",
    "load_system_prompt_v2",
    "dispatch_one",
]
