"""Run the real n=30 x panel HealthEval reference-set evaluation.

This supersedes the older single-target Gemini Flash scripts.  It evaluates the
30 fixed prompts in ``data/reference_set.yaml`` against every selected API panel
model, scores each response with the final HealthEval safety rule, and writes:

* ``results/panel_refset_eval/<model_id>.json`` — one complete artefact per model
* ``results/methodology_panel_refset_eval.json`` — flattened panel artefact for UI

The default panel is read from ``data/model_panel.yaml`` and currently contains
Sarvam 105B Conversations, Sarvam 105B, Claude Sonnet 4.6, and Gemini 2.5 Pro.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import judges as judges_mod  # noqa: E402
from eval.benchmark import benchmark_metadata, require_current_benchmark, DATASET_VERSION, PROMPT_VERSION
from eval.final_method import final_safety_method_config  # noqa: E402
from eval.panel_clients import (  # noqa: E402
    PANEL_MODEL_IDS,
    call_panel_model,
    load_panel_model_ids,
    load_system_prompt,
    model_generation_config,
    validate_panel_env,
)
from eval.reference_risk import reference_risk_tier  # noqa: E402

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
                    "judge_parse_succeeded": bool(
                        getattr(score, "judge_parse_succeeded", True)
                    ),
                    "judge_error_type": getattr(score, "judge_error_type", None),
                }
            )
    return out


def _decision_from_scores(
    scores: Sequence[Any],
    triage: Mapping[str, Any] | None,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    del triage
    decision = judges_mod.jury_to_section_5_8_decision(
        scores,
        principle_ids=[int(p) for p in calibration["principle_ids"]],
        green_threshold=float(calibration["green_threshold"]),
        amber_threshold=float(calibration["amber_threshold"]),
    )
    decision["calibration_id"] = calibration.get("id", "")
    decision["union_with_response_triage"] = False
    return decision


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
    require_current_benchmark(data, label=str(path))
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
        "schema_version": 2,
        **benchmark_metadata(),
        "export_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evaluator_name": "healtheval_safety_method",
        "dataset": "reference_set",
        "dataset_path": "data/reference_set.yaml",
        "panel_target": model_id,
        "generation_config": model_generation_config(model_id),
        "panel_models": [model_id],
        "n_prompts_done": len(rows),
        "n_prompts_total": total,
        "jury": jury_ids,
        "judge_mode": judge_mode,
        "rubric_pack_version": "health_safety_v1",
        "retrieval_enabled": True,
        "reference_risk_context_enabled": True,
        "reference_risk_tier_mapping": {
            "derived_from": "data/reference_set.yaml expected_safety_action",
            "continue": "green",
            "refer": "yellow",
            "urgent": "red",
        },
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
        jury_ids = list(dict.fromkeys(jury_ids + list(artifact.get("jury", []) or [])))

    default_model = complete_models[0] if complete_models else (model_ids[0] if model_ids else "")
    default_outputs = (
        models.get(default_model, {}).get("evaluator_outputs", {}) if default_model else {}
    )
    total_cells = total_prompts * len(model_ids)
    return {
        "schema_version": 2,
        **benchmark_metadata(),
        "export_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evaluator_name": "healtheval_panel_safety_method",
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
        "rubric_pack_version": "health_safety_v1",
        "retrieval_enabled": True,
        "reference_risk_context_enabled": True,
        "reference_risk_tier_mapping": {
            "derived_from": "data/reference_set.yaml expected_safety_action",
            "continue": "green",
            "refer": "yellow",
            "urgent": "red",
        },
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
    reuse_responses: bool,
    resume: bool,
    fill_missing_responses: bool,
    judge_workers: int,
    jury: Sequence[Any] | None = None,
) -> None:
    path = _artifact_path(model_id)
    if force and reuse_responses:
        raise ValueError("--force cannot be combined with --reuse-responses")
    if force and path.exists():
        path.unlink()

    existing = _load_existing_model_artifact(model_id)
    active_jury = list(jury) if jury is not None else judges_mod.configured_jury()
    jury_ids = [j.judge_id for j in active_jury if not judges_mod.same_model_family(j.model_id, model_id)]
    if not jury_ids:
        raise ValueError(f"No independent judge remains for {model_id}")
    if existing and (existing.get("jury") != jury_ids or existing.get("calibration") != dict(calibration)):
        raise ValueError("Saved scoring configuration differs; use a separate output directory or --force.")
    if existing and existing.get("generation_config") != model_generation_config(model_id):
        raise ValueError("Saved generation settings differ; use a separate output directory or --force.")
    wanted = {str(item['id']) for item in refset}
    rows: list[dict[str, Any]] = (
        list((existing or {}).get("rows", []) or [])
        if (resume or not reuse_responses)
        else []
    )
    evaluator_outputs: dict[str, dict[str, Any]] = (
        dict((existing or {}).get("evaluator_outputs", {}) or {})
        if (resume or not reuse_responses)
        else {}
    )
    done_ids = (
        {str(row.get("prompt_id")) for row in rows if row.get("prompt_id")}
        if (resume or not reuse_responses)
        else set()
    )
    rows = [row for row in rows if str(row.get('prompt_id')) in wanted]
    evaluator_outputs = {key: value for key, value in evaluator_outputs.items() if key in wanted}
    done_ids &= wanted

    trace_writer = judges_mod.make_jsonl_trace_writer(TRACE_PATH)
    judge_mode = "final_safety_method"

    print(f"\n=== {model_id}: {len(done_ids)}/{len(refset)} already complete ===", flush=True)
    existing_rows_by_id = {
        str(row.get("prompt_id")): dict(row)
        for row in ((existing or {}).get("rows", []) or [])
        if row.get("prompt_id")
    }
    for idx, item in enumerate(refset, start=1):
        prompt_id = str(item.get("id") or "")
        if not prompt_id or prompt_id in done_ids:
            continue
        prompt_text = str(item.get("hindi_text") or item.get("devanagari_text") or "")
        risk_tier = reference_risk_tier(item)
        print(f"[{model_id} {idx}/{len(refset)}] {prompt_id}", flush=True)

        saved_row = existing_rows_by_id.get(prompt_id, {})
        if reuse_responses:
            saved_response = str(saved_row.get("response") or "")
            if not saved_response:
                if not fill_missing_responses:
                    raise RuntimeError(
                        f"--reuse-responses requested but {model_id}/{prompt_id} "
                        "has no saved response"
                    )
                panel = call_panel_model(model_id, system_prompt, prompt_text)
                response_text = panel.response
                latency_sec = panel.latency_sec
                print(
                    f"  filled missing panel response ({len(response_text)} chars in "
                    f"{latency_sec:.1f}s)",
                    flush=True,
                )
            else:
                response_text = saved_response
                latency_sec = float(saved_row.get("latency_sec") or 0.0)
                print(f"  reused saved panel response ({len(response_text)} chars)", flush=True)
        else:
            panel = call_panel_model(model_id, system_prompt, prompt_text)
            response_text = panel.response
            latency_sec = panel.latency_sec
        triage = judges_mod.parse_triage_response(response_text)
        parse_ok = triage is not None
        if not reuse_responses:
            print(
                f"  panel {len(response_text)} chars in {latency_sec:.1f}s; "
                f"parse_succeeded={parse_ok}",
                flush=True,
            )

        judge_scores_raw: Sequence[Any] = []
        judge_scores_raw = judges_mod.judge_panel(
            prompt=prompt_text,
            response_dict={
                "response": response_text,
                "triage_json": triage or {},
                "triage_parse_succeeded": parse_ok,
                "reference_risk_tier": risk_tier,
                "reference_context": {
                    key: item.get(key) for key in (
                        "factual_checklist", "expected_referral_action", "source_url",
                        "source_paragraph", "refusal_expected", "review_status",
                    )
                },
            },
            panel_model_id=model_id,
            jury=active_jury,
            constitution=constitution_subset,
            rubric_pack_version="health_safety_v1",
            retrieve_calibration=True,
            calibration_k=3,
            trace_writer=trace_writer,
            prompt_id=prompt_id,
            prompt_template_version=PROMPT_VERSION,
            dataset_version=DATASET_VERSION,
            strategy_version=f"{PROMPT_VERSION}:{model_id}",
            max_workers=judge_workers,
        )
        decision = _decision_from_scores(judge_scores_raw, triage, calibration)
        judge_mean = decision.get("jury_safety_mean")
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
            "response": response_text,
            "response_len": len(response_text),
            "reference_risk_tier": risk_tier,
            "latency_sec": round(latency_sec, 3),
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
            "reference_risk_tier": risk_tier,
            "n_cells": decision.get("n_cells", 0),
            "n_total_cells": decision.get("n_total_cells", 0),
            "n_failed_judge_cells": decision.get("n_failed_judge_cells", 0),
            "judge_score_incomplete": bool(decision.get("judge_score_incomplete", False)),
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
        description="Run n=30 x panel HealthEval Safety Method evaluation.",
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
        "--reuse-responses",
        action="store_true",
        help=(
            "Reuse saved model responses and rerun only judge scoring. "
            "Requires existing results/panel_refset_eval/<model>.json files."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Keep completed rows in existing artefacts and continue missing prompts.",
    )
    parser.add_argument(
        "--fill-missing-responses",
        action="store_true",
        help=(
            "With --reuse-responses, call the panel model only for prompts whose "
            "saved response is missing."
        ),
    )
    parser.add_argument(
        "--reset-trace",
        action="store_true",
        help="Overwrite results/judge_trace.jsonl before running.",
    )
    parser.add_argument(
        "--judge-workers",
        type=int,
        default=6,
        help="Parallel judge calls per response. Use 1 for fully sequential replay.",
    )
    parser.add_argument("--model-workers", type=int, default=1,
                        help="Maximum panel models evaluated concurrently.")
    parser.add_argument("--judges", default=None, help="Explicit comma-separated judge subset; recorded in each model artifact.")
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR,
                        help="Isolate smoke or experimental runs from dashboard evidence.")
    return parser


def main(argv: list[str] | None = None) -> int:
    global PANEL_DIR, OUT_PANEL, TRACE_PATH
    args = _build_arg_parser().parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    model_ids = _parse_models(args.models)
    jury = judges_mod.configured_jury(args.judges)
    validate_panel_env(list(set(model_ids) | {j.model_id for j in jury}))
    for model_id in model_ids:
        if not any(not judges_mod.same_model_family(j.model_id, model_id) for j in jury):
            raise ValueError(f"No independent judge remains for {model_id}")
    PANEL_DIR = args.output_dir / "panel_refset_eval"
    OUT_PANEL = args.output_dir / "methodology_panel_refset_eval.json"
    TRACE_PATH = args.output_dir / "judge_trace.jsonl"

    refset = _load_reference_set()
    if args.limit and args.limit > 0:
        refset = refset[: args.limit]
    calibration = _load_final_calibration()
    constitution_subset = _load_constitution_subset(calibration["principle_ids"])
    if not constitution_subset:
        raise RuntimeError("No constitution principles available for final calibration")

    print("=== HealthEval n=30 x panel reference-set run ===", flush=True)
    print(f"Models: {model_ids}", flush=True)
    print(f"Prompts: {len(refset)}", flush=True)
    print(f"Final calibration: {calibration}", flush=True)
    print("Judge mode: final safety method")

    system_prompt = load_system_prompt()
    PANEL_DIR.mkdir(parents=True, exist_ok=True)
    if args.reset_trace:
        TRACE_PATH.write_text("", encoding="utf-8")
    def run_model(model_id: str) -> None:
        _run_one_model(
            model_id=model_id,
            refset=refset,
            system_prompt=system_prompt,
            constitution_subset=constitution_subset,
            calibration=calibration,
            force=args.force,
            reuse_responses=bool(args.reuse_responses),
            resume=bool(args.resume),
            fill_missing_responses=bool(args.fill_missing_responses),
            judge_workers=max(1, int(args.judge_workers)),
            jury=jury,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(args.model_workers, len(model_ids)))) as pool:
        list(pool.map(run_model, model_ids))

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
