"""Typed loaders for immutable evidence files and JSONL overlays."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml
from eval.benchmark import benchmark_metadata, require_current_benchmark
from eval.final_method import final_safety_method_config
from .config import RESULTS_DIR

from .canonical_selector import select_complete_methodology_artifact
from .config import (
    JSONL_CACHE_TTL_SECONDS,
    PATH_BUDGET_TODAY_JSONL,
    PATH_CALIBRATION_EXAMPLES,
    PATH_CERAI_DB_SCORES,
    PATH_CONSTITUTION,
    PATH_HITL_REVIEWS_JSONL,
    PATH_INSPECT,
    PATH_JUDGE_TRACE_JSONL,
    PATH_REFERENCE_SET,
    PATH_THRESHOLD_SWEEPS_JSONL,
    PATH_TOOL_META,
    RUBRICS_DIR,
)
from .schemas import (
    CalibrationPack,
    CeRaiOrInspectArtifact,
    Constitution,
    HITLReview,
    JudgeTraceRow,
    MethodologyArtifact,
    ReferenceSet,
    RubricPack,
    ThresholdSweep,
    ToolMetaArtifact,
)
try:  # pragma: no cover — exercised at runtime, not in unit tests
    import streamlit as st  # type: ignore[import-not-found]

    _cache_data = st.cache_data
except ImportError:  # streamlit absent (pytest-only environment)

    def _cache_data(*dargs: Any, **dkwargs: Any) -> Any:
        """No-op replacement for ``st.cache_data`` when streamlit is missing.

        The signature mirrors ``st.cache_data`` so call-sites work whether
        they pass kwargs (``ttl=60``, ``show_spinner=False``) or wrap the
        function bare.  Tests rely on this behaviour to import the module.
        """

        def _decorator(fn):  # type: ignore[no-untyped-def]
            return fn

        if dargs and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        return _decorator


def _mtime(path: Path) -> float:
    """Return ``path.stat().st_mtime`` or ``0.0`` if the file doesn't exist."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _path_str(path: Path) -> str:
    return str(path)


@_cache_data(show_spinner=False)
def _read_json(path: str, mtime: float) -> dict[str, Any]:
    """Internal: parse JSON.  ``mtime`` is in the cache key — never read here."""
    del mtime  # bound for caching, not used at runtime
    with open(path) as f:
        return cast(dict[str, Any], json.load(f))


@_cache_data(show_spinner=False)
def _read_yaml(path: str, mtime: float) -> dict[str, Any]:
    del mtime
    with open(path) as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def load_methodology_artifact() -> tuple[MethodologyArtifact, Path, str]:
    """Return (artefact, selected_path, suffix).

    The suffix is retained as an empty compatibility value for older page
    call-sites; the shipped dashboard uses a single final safety method.
    """
    selected = select_complete_methodology_artifact()
    if selected is None:
        return cast(MethodologyArtifact, {
            **benchmark_metadata(), "status": "not_run", "rows": [], "models": {},
            "panel_models": [], "jury": [], "n_prompts_done": 0,
            "n_prompts_total": 0, "calibration": final_safety_method_config(),
            "evaluator_outputs": {},
        }), RESULTS_DIR / "methodology_panel_refset_eval.json", ""
    artefact = cast(
        MethodologyArtifact,
        _read_json(_path_str(selected), _mtime(selected)),
    )
    return artefact, selected, ""


def load_tool_meta_evaluation() -> ToolMetaArtifact:
    if not PATH_TOOL_META.exists() or select_complete_methodology_artifact() is None:
        return cast(ToolMetaArtifact, {"table_final_method": [], "table_panel_models": [], "table_native": [], "table_risk_tiers": []})
    return cast(
        ToolMetaArtifact,
        _read_json(_path_str(PATH_TOOL_META), _mtime(PATH_TOOL_META)),
    )


def load_cerai_db_scores() -> dict[str, Any]:
    if not PATH_CERAI_DB_SCORES.exists():
        return {}
    artifact = _read_json(_path_str(PATH_CERAI_DB_SCORES), _mtime(PATH_CERAI_DB_SCORES))
    require_current_benchmark(artifact, label="CeRAI scores")
    return artifact


def load_inspect_safety() -> CeRaiOrInspectArtifact:
    if not PATH_INSPECT.exists():
        return cast(CeRaiOrInspectArtifact, {"evaluator_outputs": {}})
    return cast(
        CeRaiOrInspectArtifact,
        _read_json(_path_str(PATH_INSPECT), _mtime(PATH_INSPECT)),
    )


def load_reference_set() -> ReferenceSet:
    return cast(
        ReferenceSet,
        _read_yaml(_path_str(PATH_REFERENCE_SET), _mtime(PATH_REFERENCE_SET)),
    )


def load_constitution() -> Constitution:
    return cast(
        Constitution,
        _read_yaml(_path_str(PATH_CONSTITUTION), _mtime(PATH_CONSTITUTION)),
    )


def load_rubric_pack(metric: str, version: str = "v1") -> RubricPack:
    """Load ``data/rubrics/{metric}_{version}.yaml``."""
    path = RUBRICS_DIR / f"{metric}_{version}.yaml"
    return cast(RubricPack, _read_yaml(_path_str(path), _mtime(path)))


def load_all_rubric_packs(version: str = "v1") -> dict[str, RubricPack]:
    """Convenience: read every ``data/rubrics/*_{version}.yaml`` into a dict."""
    out: dict[str, RubricPack] = {}
    for path in sorted(RUBRICS_DIR.glob(f"*_{version}.yaml")):
        metric = path.stem[: -(len(version) + 1)]  # strip ``_v1``
        out[metric] = cast(RubricPack, _read_yaml(_path_str(path), _mtime(path)))
    return out


def load_judge_calibration_examples() -> CalibrationPack:
    return cast(
        CalibrationPack,
        _read_yaml(
            _path_str(PATH_CALIBRATION_EXAMPLES),
            _mtime(PATH_CALIBRATION_EXAMPLES),
        ),
    )


def _read_jsonl(path: str, mtime: float) -> list[dict[str, Any]]:
    del mtime
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Tolerate partial trailing line during a concurrent append.
                continue
    return rows


@_cache_data(show_spinner=False, ttl=JSONL_CACHE_TTL_SECONDS)
def _read_jsonl_cached(path: str, mtime: float) -> list[dict[str, Any]]:
    return _read_jsonl(path, mtime)


def load_hitl_reviews() -> list[HITLReview]:
    return cast(
        list[HITLReview],
        _read_jsonl_cached(
            _path_str(PATH_HITL_REVIEWS_JSONL),
            _mtime(PATH_HITL_REVIEWS_JSONL),
        ),
    )


def load_threshold_sweeps() -> list[ThresholdSweep]:
    return cast(
        list[ThresholdSweep],
        _read_jsonl_cached(
            _path_str(PATH_THRESHOLD_SWEEPS_JSONL),
            _mtime(PATH_THRESHOLD_SWEEPS_JSONL),
        ),
    )


def load_judge_trace() -> list[JudgeTraceRow]:
    return cast(
        list[JudgeTraceRow],
        _read_jsonl_cached(
            _path_str(PATH_JUDGE_TRACE_JSONL),
            _mtime(PATH_JUDGE_TRACE_JSONL),
        ),
    )


def load_budget_today() -> list[dict[str, Any]]:
    """Live Demo dispatch ledger — read fresh, no caching (small file, hot path)."""
    return _read_jsonl(_path_str(PATH_BUDGET_TODAY_JSONL), _mtime(PATH_BUDGET_TODAY_JSONL))


def load_canonical_methodology() -> MethodologyArtifact:
    """Return JUST the parsed methodology artefact (drops path + suffix).

    Page-builder-A's overview / threshold pages don't need the path at the
    call site; ``load_methodology_artifact()`` is still available when a
    page needs to show which evidence file is loaded.
    """
    artefact, _path, _suffix = load_methodology_artifact()
    return artefact


def methodology_model_ids(artefact: MethodologyArtifact) -> list[str]:
    """Return model ids available in a methodology artefact.

    Legacy single-target artefacts return a one-item list containing
    ``panel_target``.  Panel artefacts return the keys under ``models``.
    """
    models = artefact.get("models")
    if isinstance(models, dict) and models:
        return [str(model_id) for model_id in models.keys()]
    target = artefact.get("panel_target")
    return [str(target)] if target else []


def methodology_for_model(
    artefact: MethodologyArtifact,
    model_id: str | None,
) -> MethodologyArtifact:
    """Return a single-model view of either a panel or legacy artefact."""
    models = artefact.get("models")
    if isinstance(models, dict) and models:
        chosen = model_id if model_id in models else str(artefact.get("default_model") or "")
        if not chosen:
            chosen = next(iter(models.keys()))
        model_artifact = dict(models[chosen])
        model_artifact.setdefault("selected_from_panel", True)
        model_artifact.setdefault("panel_models", list(models.keys()))
        model_artifact.setdefault("panel_target", chosen)
        return cast(MethodologyArtifact, model_artifact)
    return artefact


def load_tool_meta() -> ToolMetaArtifact:
    """Alias for :func:`load_tool_meta_evaluation` per page-builder-A."""
    return load_tool_meta_evaluation()


def load_inspect() -> CeRaiOrInspectArtifact:
    """Alias for :func:`load_inspect_safety`."""
    return load_inspect_safety()


def load_calibration_examples() -> list[dict[str, Any]]:
    """Return the seed pack ``examples`` list directly (un-wrapped)."""
    return list(load_judge_calibration_examples().get("examples", []))


def load_rubric_packs() -> dict[str, RubricPack]:
    """Alias for :func:`load_all_rubric_packs` (default v1)."""
    return load_all_rubric_packs(version="v1")


def load_reference_items() -> list[dict[str, Any]]:
    """Return ``data/reference_set.yaml["items"]`` directly (un-wrapped)."""
    return list(load_reference_set().get("items", []))


def load_hitl_reviews_repo() -> list[HITLReview]:
    """Alias for :func:`load_hitl_reviews` — emphasises 'repo file, not session state'."""
    return load_hitl_reviews()


def load_jury_cells_by_prompt() -> dict[str, list[JudgeScoreRow]]:
    """Return ``{prompt_id: rows[i].judge_scores}`` for the canonical artefact.

    Threshold Tuning recomputes sens/spec by walking these per-prompt cell
    lists under alternative band configurations; surfacing them here keeps
    the page free of ``rows`` traversal boilerplate.
    """
    artefact = load_canonical_methodology()
    out: dict[str, list[JudgeScoreRow]] = {}
    for row in artefact.get("rows", []):
        prompt_id = row.get("prompt_id")
        cells = row.get("judge_scores", [])
        if isinstance(prompt_id, str) and isinstance(cells, list):
            out[prompt_id] = cells
    return out


__all__ = [
    "load_methodology_artifact",
    "load_tool_meta_evaluation",
    "load_cerai_db_scores",
    "load_inspect_safety",
    "load_reference_set",
    "load_constitution",
    "load_rubric_pack",
    "load_all_rubric_packs",
    "load_judge_calibration_examples",
    "load_hitl_reviews",
    "load_threshold_sweeps",
    "load_judge_trace",
    "load_budget_today",
    "load_canonical_methodology",
    "methodology_model_ids",
    "methodology_for_model",
    "load_tool_meta",
    "load_inspect",
    "load_calibration_examples",
    "load_rubric_packs",
    "load_reference_items",
    "load_hitl_reviews_repo",
    "load_jury_cells_by_prompt",
]
