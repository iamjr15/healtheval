"""Run the real n=30 x panel MaaSwasth reference-set evaluation.

This supersedes the older single-target Gemini Flash scripts.  It evaluates the
30 fixed prompts in ``data/reference_set.yaml`` against every selected API panel
model, scores each response with the final MaaSwasth safety rule, and writes:

* ``results/panel_refset_eval/<model_id>.json`` — one complete artefact per model
* ``results/methodology_panel_refset_eval.json`` — flattened panel artefact for UI

The default panel is read from ``data/model_panel.yaml`` and currently contains
Sarvam 30B, Sarvam 105B, Claude Sonnet 4.6, and Gemini 2.5 Pro.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import judges as judges_mod  # noqa: E402
from eval.final_method import final_safety_method_config  # noqa: E402
from eval.panel_clients import (  # noqa: E402
    PANEL_MODEL_IDS,
    call_panel_model,
    load_panel_model_ids,
    load_system_prompt,
    validate_panel_env,
)

RESULTS_DIR = REPO_ROOT / "results"
PANEL_DIR = RESULTS_DIR / "panel_refset_eval"
REFERENCE_SET_PATH = REPO_ROOT / "data" / "reference_set.yaml"
CONSTITUTION_PATH = REPO_ROOT / "data" / "constitution.yaml"
OUT_PANEL = RESULTS_DIR / "methodology_panel_refset_eval.json"
TRACE_PATH = RESULTS_DIR / "judge_trace.jsonl"

def _load_reference_set() -> list[dict[str, Any]]:
    with REFERENCE_SET_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    items = doc.get("items") or doc.get("prompts") or doc
    if not isinstance(items, list):
        raise ValueError(f"{REFERENCE_SET_PATH} did not yield a list of items")
    return [dict(item) for item in items]


def _load_constitution_subset(principle_ids: Sequence[int]) -> list[dict[str, Any]]:
    with CONSTITUTION_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    principles = list(doc.get("principles") or [])
    wanted = {int(pid) for pid in principle_ids}
    return [dict(p) for p in principles if int(p.get("id", 0)) in wanted]


def _load_final_calibration() -> dict[str, Any]:
    return final_safety_method_config()


def _serialise_scores(scores: Sequence[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for score in scores:
        if hasattr(score, "model_dump"):
            out.append(score.model_dump(mode="json"))
        else:
            out.append(
                {
                    "judge_model_id": getattr(score, "judge_model_id", ""),
                    "principle_id": int(getattr(score, "principle_id", 0)),
                    "score": float(getattr(score, "score", 0.0)),
                    "rationale": getattr(score, "rationale", None),
                }
            )
    return out


def _decision_from_scores(
    scores: Sequence[Any],
    triage: Mapping[str, Any] | None,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    decision = judges_mod.jury_to_section_5_8_decision(
        scores,
        principle_ids=[int(p) for p in calibration["principle_ids"]],
        green_threshold=float(calibration["green_threshold"]),
        amber_threshold=float(calibration["amber_threshold"]),
    )
    if bool(calibration.get("union_with_response_triage", False)):
        label = str((triage or {}).get("triage_label", "")).upper()
        if label in {"AMBER", "RED"}:
            decision = dict(decision)
            decision["flagged"] = True
            decision["union_triggered_by"] = "response_triage"
    decision["calibration_id"] = calibration.get("id", "")
    decision["union_with_response_triage"] = bool(
        calibration.get("union_with_response_triage", False)
    )
    return decision


def _response_triage_decision(
    triage: Mapping[str, Any] | None,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    label = str((triage or {}).get("triage_label", "")).upper()
    flagged = label in {"AMBER", "RED"}
    return {
        "triage_label": label if label in {"GREEN", "AMBER", "RED"} else "PARSE_FAILED",
        "flagged": flagged,
        "jury_safety_mean": None,
        "n_cells": 0,
        "principle_ids": [int(p) for p in calibration["principle_ids"]],
        "calibration_id": calibration.get("id", ""),
        "union_with_response_triage": bool(
            calibration.get("union_with_response_triage", False)
        ),
        "decision_source": "response_triage_only",
    }


def _artifact_path(model_id: str) -> Path:
    return PANEL_DIR / f"{model_id}.json"


def _load_existing_model_artifact(model_id: str) -> dict[str, Any] | None:
    path = _artifact_path(model_id)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return None
    return data


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    os.replace(tmp, path)


def _model_artifact_payload(
    *,
    model_id: str,
    rows: list[dict[str, Any]],
    evaluator_outputs: dict[str, dict[str, Any]],
    total: int,
    jury_ids: list[str],
    calibration: Mapping[str, Any],
    judge_mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "export_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evaluator_name": "maaswasth_safety_method",
        "dataset": "reference_set",
        "dataset_path": "data/reference_set.yaml",
        "panel_target": model_id,
        "panel_models": [model_id],
        "n_prompts_done": len(rows),
        "n_prompts_total": total,
        "jury": jury_ids,
        "judge_mode": judge_mode,
        "rubric_pack_version": "mnh_safety_v1",
        "retrieval_enabled": judge_mode != "response_triage_only",
        "calibration": dict(calibration),
        "evaluator_outputs": evaluator_outputs,
        "rows": rows,
    }


def _combine_panel_artifacts(
    model_ids: Sequence[str],
    *,
    total_prompts: int,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    models: dict[str, dict[str, Any]] = {}
    flat_rows: list[dict[str, Any]] = []
    complete_models: list[str] = []
    jury_ids: list[str] = []
    for model_id in model_ids:
        artifact = _load_existing_model_artifact(model_id)
        if not artifact:
            continue
        models[model_id] = artifact
        flat_rows.extend(dict(row, model_id=model_id) for row in artifact.get("rows", []))
        if artifact.get("n_prompts_done") == artifact.get("n_prompts_total") == total_prompts:
            complete_models.append(model_id)
        if not jury_ids:
            jury_ids = list(artifact.get("jury", []) or [])

    default_model = complete_models[0] if complete_models else (model_ids[0] if model_ids else "")
    default_outputs = (
        models.get(default_model, {}).get("evaluator_outputs", {}) if default_model else {}
    )
    total_cells = total_prompts * len(model_ids)
    return {
        "schema_version": 1,
        "export_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evaluator_name": "maaswasth_panel_safety_method",
        "dataset": "reference_set",
        "dataset_path": "data/reference_set.yaml",
        "panel_target": "panel",
        "panel_models": list(model_ids),
        "complete_panel_models": complete_models,
        "default_model": default_model,
        "n_models_done": len(complete_models),
        "n_models_total": len(model_ids),
        "n_prompts_done": len(flat_rows),
        "n_prompts_total": total_cells,
        "jury": jury_ids,
        "judge_mode": "final_safety_method",
        "rubric_pack_version": "mnh_safety_v1",
        "retrieval_enabled": True,
        "calibration": dict(calibration),
        "evaluator_outputs": default_outputs,
        "models": models,
        "rows": flat_rows,
    }


def _parse_models(raw: str | None) -> list[str]:
    if raw:
        model_ids = [m.strip() for m in raw.split(",") if m.strip()]
    else:
        model_ids = load_panel_model_ids()
    allowed = set(PANEL_MODEL_IDS)
    unknown = [m for m in model_ids if m not in allowed]
    if unknown:
        raise ValueError(f"Unsupported panel model(s): {', '.join(unknown)}")
    return model_ids


def _run_one_model(
    *,
    model_id: str,
    refset: list[dict[str, Any]],
    system_prompt: str,
    constitution_subset: list[dict[str, Any]],
    calibration: Mapping[str, Any],
    force: bool,
    skip_judges: bool,
    judge_workers: int,
) -> None:
    path = _artifact_path(model_id)
    if force and path.exists():
        path.unlink()

    existing = _load_existing_model_artifact(model_id)
    rows: list[dict[str, Any]] = list((existing or {}).get("rows", []) or [])
    evaluator_outputs: dict[str, dict[str, Any]] = dict(
        (existing or {}).get("evaluator_outputs", {}) or {}
    )
    done_ids = {str(row.get("prompt_id")) for row in rows if row.get("prompt_id")}

    trace_writer = judges_mod.make_jsonl_trace_writer(TRACE_PATH)
    jury_ids = [j.judge_id for j in judges_mod.DEFAULT_JURY if j.model_id != model_id]
    judge_mode = "response_triage_only" if skip_judges else "final_safety_method"

    print(f"\n=== {model_id}: {len(done_ids)}/{len(refset)} already complete ===", flush=True)
    for idx, item in enumerate(refset, start=1):
        prompt_id = str(item.get("id") or "")
        if not prompt_id or prompt_id in done_ids:
            continue
        prompt_text = str(item.get("hindi_text") or item.get("devanagari_text") or "")
        print(f"[{model_id} {idx}/{len(refset)}] {prompt_id}", flush=True)

        panel = call_panel_model(model_id, system_prompt, prompt_text)
        triage = judges_mod.parse_triage_response(panel.response)
        parse_ok = triage is not None
        print(
            f"  panel {len(panel.response)} chars in {panel.latency_sec:.1f}s; "
            f"parse_succeeded={parse_ok}",
            flush=True,
        )

        judge_scores_raw: Sequence[Any] = []
        if skip_judges:
            decision = _response_triage_decision(triage, calibration)
            judge_mean = None
        else:
            judge_scores_raw = judges_mod.judge_panel(
                prompt=prompt_text,
                response_dict={
                    "response": panel.response,
                    "triage_json": triage or {},
                    "triage_parse_succeeded": parse_ok,
                },
                panel_model_id=model_id,
                constitution=constitution_subset,
                rubric_pack_version="mnh_safety_v1",
                retrieve_calibration=True,
                calibration_k=3,
                trace_writer=trace_writer,
                prompt_id=prompt_id,
                prompt_template_version="panel_final_v1",
                dataset_version="reference_set_v2",
                strategy_version=f"panel_final_v1:{model_id}",
                max_workers=judge_workers,
            )
            decision = _decision_from_scores(judge_scores_raw, triage, calibration)
            judge_mean = (
                statistics.mean(float(getattr(s, "score", 0.0)) for s in judge_scores_raw)
                if judge_scores_raw
                else None
            )
            print(
                f"  judged {len(judge_scores_raw)} cells; "
                f"flagged={decision.get('flagged')} mean={decision.get('jury_safety_mean')}",
                flush=True,
            )

        judge_scores = _serialise_scores(judge_scores_raw)
        row = {
            "model_id": model_id,
            "prompt_id": prompt_id,
            "prompt": prompt_text,
            "response": panel.response,
            "response_len": len(panel.response),
            "latency_sec": round(panel.latency_sec, 3),
            "parse_succeeded": parse_ok,
            "triage_parsed": triage,
            "judge_scores": judge_scores,
            "judge_mean": judge_mean,
            "decision": decision,
        }
        rows.append(row)
        evaluator_outputs[prompt_id] = {
            "model_id": model_id,
            "flagged": bool(decision.get("flagged", False)),
            "triage_label": decision.get("triage_label"),
            "jury_safety_mean": decision.get("jury_safety_mean"),
            "n_cells": decision.get("n_cells", 0),
            "parse_succeeded": parse_ok,
            "calibration_id": calibration.get("id", ""),
        }
        _write_json(
            path,
            _model_artifact_payload(
                model_id=model_id,
                rows=rows,
                evaluator_outputs=evaluator_outputs,
                total=len(refset),
                jury_ids=jury_ids,
                calibration=calibration,
                judge_mode=judge_mode,
            ),
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run n=30 x panel MaaSwasth Safety Method evaluation.",
    )
    parser.add_argument(
        "--models",
        default=None,
        help=(
            "Comma-separated panel subset. Default reads all API panel models "
            "from data/model_panel.yaml."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional prompt limit for smoke runs. 0 means all 30 prompts.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete existing per-model artefacts before running.",
    )
    parser.add_argument(
        "--skip-judges",
        action="store_true",
        help="Smoke mode: call panel models but derive decisions from response triage only.",
    )
    parser.add_argument(
        "--judge-workers",
        type=int,
        default=6,
        help="Parallel judge calls per response. Use 1 for fully sequential replay.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    model_ids = _parse_models(args.models)
    validate_panel_env(model_ids)

    refset = _load_reference_set()
    if args.limit and args.limit > 0:
        refset = refset[: args.limit]
    calibration = _load_final_calibration()
    constitution_subset = _load_constitution_subset(calibration["principle_ids"])
    if not constitution_subset and not args.skip_judges:
        raise RuntimeError("No constitution principles available for final calibration")

    print("=== MaaSwasth n=30 x panel reference-set run ===", flush=True)
    print(f"Models: {model_ids}", flush=True)
    print(f"Prompts: {len(refset)}", flush=True)
    print(f"Final calibration: {calibration}", flush=True)
    print(f"Judge mode: {'response triage only' if args.skip_judges else 'final safety method'}")

    system_prompt = load_system_prompt()
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    for model_id in model_ids:
        _run_one_model(
            model_id=model_id,
            refset=refset,
            system_prompt=system_prompt,
            constitution_subset=constitution_subset,
            calibration=calibration,
            force=args.force,
            skip_judges=args.skip_judges,
            judge_workers=max(1, int(args.judge_workers)),
        )

    combined = _combine_panel_artifacts(
        model_ids,
        total_prompts=len(refset),
        calibration=calibration,
    )
    _write_json(OUT_PANEL, combined)
    print(f"\nWrote panel artefact: {OUT_PANEL}", flush=True)
    print(
        f"Complete models: {combined['n_models_done']}/{combined['n_models_total']} "
        f"({combined['complete_panel_models']})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
