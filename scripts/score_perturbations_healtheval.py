"""Score all 35 cells (5 bases + 30 perturbed) through HealthEval's existing jury panel.

This calls eval.judges.judge_panel with the same calibration used for the
canonical 30-prompt run. The audit tests whether routing stays stable when the
same factual content is expressed in different Hindi surface forms.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from eval import judges as judges_mod  # noqa: E402
from eval.final_method import final_safety_method_config  # noqa: E402
from eval.reference_risk import reference_risk_tier  # noqa: E402

BASE_PATH = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"
PERT_PATH = REPO_ROOT / "data" / "perturbations" / "perturbed_responses.jsonl"
CONSTITUTION_PATH = REPO_ROOT / "data" / "constitution.yaml"
REFERENCE_SET_PATH = REPO_ROOT / "data" / "reference_set.yaml"
OUT_PATH = REPO_ROOT / "results" / "perturbation_scores_healtheval.json"
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


def _load_reference_risk_by_id() -> dict[str, str]:
    with REFERENCE_SET_PATH.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    return {
        str(item["id"]): reference_risk_tier(item)
        for item in list(doc.get("items") or [])
        if item.get("id")
    }


def _decision_from_scores(
    scores: Sequence[Any],
    triage: Mapping[str, Any] | None,
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    """Replicates scripts/run_panel_refset_eval._decision_from_scores."""
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


def _score_cell(
    *,
    prompt_id: str,
    perturbation_type: str,
    user_prompt: str,
    response_text: str,
    reference_risk: str,
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
            "reference_risk_tier": reference_risk,
        },
        panel_model_id=PANEL_MODEL_ID,
        jury=judges_mod.configured_jury(),
        constitution=constitution_subset,
        rubric_pack_version="health_safety_v1",
        retrieve_calibration=True,
        calibration_k=3,
        trace_writer=trace_writer,
        prompt_id=prompt_id,
        prompt_template_version="perturbation_reference_risk_v1",
        dataset_version=f"perturbations_v1:{perturbation_type}",
        strategy_version=f"perturbation_reference_risk_v1:{PANEL_MODEL_ID}:{perturbation_type}",
        max_workers=6,
    )
    decision = _decision_from_scores(judge_scores, triage, calibration)
    jury_mean = decision.get("jury_safety_mean")
    return {
        "prompt_id": prompt_id,
        "perturbation_type": perturbation_type,
        "response_text": response_text,
        "reference_risk_tier": reference_risk,
        "parse_succeeded": parse_ok,
        "triage_parsed": triage,
        "jury_safety_mean": jury_mean,
        "n_cells": decision.get("n_cells", len(judge_scores)),
        "n_total_cells": decision.get("n_total_cells", len(judge_scores)),
        "n_failed_judge_cells": decision.get("n_failed_judge_cells", 0),
        "judge_score_incomplete": bool(decision.get("judge_score_incomplete", False)),
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
    from eval.benchmark import benchmark_metadata, require_current_benchmark
    calibration = final_safety_method_config()
    constitution_subset = _load_constitution_subset(calibration["principle_ids"])
    reference_risk_by_id = _load_reference_risk_by_id()
    bases = _load_jsonl(BASE_PATH)
    perts = _load_jsonl(PERT_PATH) if PERT_PATH.exists() else []
    for record in bases + perts:
        require_current_benchmark(record, label="perturbation input")
    base_lookup = {b["prompt_id"]: b for b in bases}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACE_PATH.unlink(missing_ok=True)
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
            reference_risk=reference_risk_by_id[b["prompt_id"]],
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
            reference_risk=reference_risk_by_id[p["prompt_id"]],
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
        **benchmark_metadata(),
        "evaluator_name": "healtheval_safety_method",
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
