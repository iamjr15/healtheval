"""Score all 35 cells (5 bases + 30 perturbed) through MaaSwasth's existing jury panel.

This calls eval.judges.judge_panel directly with the same arguments scripts/run_panel_refset_eval.py
uses for the canonical 30-prompt run. We are testing the EXISTING evaluator's stability under
perturbed inputs — no judge-side changes.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import judges as judges_mod  # noqa: E402
from eval.final_method import final_safety_method_config  # noqa: E402

BASE_PATH = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"
PERT_PATH = REPO_ROOT / "data" / "perturbations" / "perturbed_responses.jsonl"
CONSTITUTION_PATH = REPO_ROOT / "data" / "constitution.yaml"
OUT_PATH = REPO_ROOT / "results" / "perturbation_scores_maaswasth.json"
TRACE_PATH = REPO_ROOT / "results" / "perturbation_judge_trace.jsonl"

PANEL_MODEL_ID = "sarvam-105b"  # base responses originate from this panel target


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.open(encoding="utf-8")]


def _load_constitution_subset(principle_ids: Sequence[int]) -> list[dict[str, Any]]:
    with CONSTITUTION_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    principles = list(doc.get("principles") or [])
    wanted = {int(pid) for pid in principle_ids}
    return [dict(p) for p in principles if int(p.get("id", 0)) in wanted]


def _decision_from_scores(
    scores: Sequence[Any],
    triage: Mapping[str, Any] | None,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    """Replicates scripts/run_panel_refset_eval._decision_from_scores."""
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


def _score_cell(
    *,
    prompt_id: str,
    perturbation_type: str,
    user_prompt: str,
    response_text: str,
    constitution_subset: list[dict[str, Any]],
    calibration: Mapping[str, Any],
    trace_writer,
) -> dict[str, Any]:
    triage = judges_mod.parse_triage_response(response_text)
    parse_ok = triage is not None

    judge_scores = judges_mod.judge_panel(
        prompt=user_prompt,
        response_dict={
            "response": response_text,
            "triage_json": triage or {},
            "triage_parse_succeeded": parse_ok,
        },
        panel_model_id=PANEL_MODEL_ID,
        constitution=constitution_subset,
        rubric_pack_version="mnh_safety_v1",
        retrieve_calibration=True,
        calibration_k=3,
        trace_writer=trace_writer,
        prompt_id=prompt_id,
        prompt_template_version="perturbation_v1",
        dataset_version=f"perturbations_v1:{perturbation_type}",
        strategy_version=f"perturbation_v1:{PANEL_MODEL_ID}:{perturbation_type}",
        max_workers=1,
    )
    decision = _decision_from_scores(judge_scores, triage, calibration)
    jury_mean = (
        statistics.mean(float(getattr(s, "score", 0.0)) for s in judge_scores)
        if judge_scores else None
    )
    return {
        "prompt_id": prompt_id,
        "perturbation_type": perturbation_type,
        "response_text": response_text,
        "parse_succeeded": parse_ok,
        "triage_parsed": triage,
        "jury_safety_mean": jury_mean,
        "n_cells": len(judge_scores),
        "decision": decision,
        "flagged": bool(decision.get("flagged")),
        "triage_label": decision.get("triage_label"),
        "judge_scores": [
            (s.model_dump(mode="json") if hasattr(s, "model_dump") else
             {"judge_model_id": getattr(s, "judge_model_id", ""),
              "principle_id": int(getattr(s, "principle_id", 0)),
              "score": float(getattr(s, "score", 0.0))})
            for s in judge_scores
        ],
    }


def main() -> int:
    calibration = final_safety_method_config()
    constitution_subset = _load_constitution_subset(calibration["principle_ids"])
    bases = _load_jsonl(BASE_PATH)
    perts = _load_jsonl(PERT_PATH) if PERT_PATH.exists() else []
    base_lookup = {b["prompt_id"]: b for b in bases}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    trace_writer = judges_mod.make_jsonl_trace_writer(TRACE_PATH)

    cells: list[dict[str, Any]] = []

    # Originals first
    for b in bases:
        t0 = time.perf_counter()
        cell = _score_cell(
            prompt_id=b["prompt_id"],
            perturbation_type="original",
            user_prompt=b["user_prompt"],
            response_text=b["base_response"],
            constitution_subset=constitution_subset,
            calibration=calibration,
            trace_writer=trace_writer,
        )
        cells.append(cell)
        print(
            f"{cell['prompt_id']} original           "
            f"flagged={cell['flagged']} mean={cell['jury_safety_mean']:.2f} "
            f"triage={cell['triage_label']} dt={time.perf_counter()-t0:.1f}s",
            flush=True,
        )

    # Perturbed cells
    for p in perts:
        base = base_lookup[p["prompt_id"]]
        t0 = time.perf_counter()
        cell = _score_cell(
            prompt_id=p["prompt_id"],
            perturbation_type=p["perturbation_type"],
            user_prompt=base["user_prompt"],
            response_text=p["perturbed_response"],
            constitution_subset=constitution_subset,
            calibration=calibration,
            trace_writer=trace_writer,
        )
        cells.append(cell)
        print(
            f"{cell['prompt_id']} {cell['perturbation_type']:<18} "
            f"flagged={cell['flagged']} mean={cell['jury_safety_mean']:.2f} "
            f"triage={cell['triage_label']} dt={time.perf_counter()-t0:.1f}s",
            flush=True,
        )

    out = {
        "schema_version": 1,
        "evaluator_name": "maaswasth_safety_method",
        "panel_target": PANEL_MODEL_ID,
        "calibration": dict(calibration),
        "cells": cells,
    }
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
