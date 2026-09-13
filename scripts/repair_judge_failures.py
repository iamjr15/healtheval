"""Retry unusable judge cells in saved panel artifacts."""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval import judges as judges_mod  # noqa: E402
from scripts.run_panel_refset_eval import (  # noqa: E402
    TRACE_PATH,
    _artifact_path,
    _combine_panel_artifacts,
    _decision_from_scores,
    _load_constitution_subset,
    _load_existing_model_artifact,
    _load_final_calibration,
    _load_reference_set,
    _model_artifact_payload,
    _parse_models,
    _serialise_scores,
    _write_json,
    OUT_PANEL,
)

FAILURE_PREFIXES = (
    "empty judge response",
    "unparseable judge response",
    "judge call failed",
)


def _score_is_failed(score: Mapping[str, Any]) -> bool:
    if score.get("judge_parse_succeeded") is False:
        return True
    rationale = str(score.get("rationale") or "")
    return rationale.startswith(FAILURE_PREFIXES)


def _judge_for_model(model_id: str) -> judges_mod.JudgeConfig:
    for judge in judges_mod.DEFAULT_JURY:
        if judge.model_id == model_id:
            return judge
    raise ValueError(f"No configured judge model named {model_id!r}")


def _trace_key(
    model_id: str,
    prompt_id: str,
    judge_model_id: str,
    principle_id: int,
) -> tuple[str, str, str, int]:
    return (model_id, prompt_id, judge_model_id, int(principle_id))


def _model_from_strategy(strategy_version: str) -> str | None:
    if not strategy_version.startswith("health_reference_risk"):
        return None
    if ":" not in strategy_version:
        return None
    return strategy_version.rsplit(":", 1)[-1]


def _trace_score(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "judge_model_id": row.get("judge_model"),
        "principle_id": int(row.get("principle_id") or 0),
        "score": float(row.get("score")),
        "rationale": row.get("rationale"),
        "self_judging_dropped": False,
        "judge_parse_succeeded": True,
        "judge_error_type": None,
    }


def _load_trace_replacements(
    model_ids: Sequence[str],
) -> dict[tuple[str, str, str, int], dict[str, Any]]:
    if not TRACE_PATH.exists():
        return {}

    allowed = set(model_ids)
    replacements: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    with TRACE_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            model_id = _model_from_strategy(str(row.get("strategy_version") or ""))
            if model_id not in allowed:
                continue
            score = _trace_score(row)
            if _score_is_failed(score):
                continue
            key = _trace_key(
                model_id,
                str(row.get("prompt_id") or ""),
                str(row.get("judge_model") or ""),
                int(row.get("principle_id") or 0),
            )
            replacements[key] = score
    return replacements


def _replace_score(
    scores: list[dict[str, Any]],
    replacement: Mapping[str, Any],
) -> None:
    judge_id = str(replacement["judge_model_id"])
    principle_id = int(replacement["principle_id"])
    for index, score in enumerate(scores):
        if (
            str(score.get("judge_model_id")) == judge_id
            and int(score.get("principle_id") or 0) == principle_id
        ):
            scores[index] = dict(replacement)
            return
    raise RuntimeError(f"Could not replace {judge_id} principle {principle_id}")


def _retry_one_score(
    *,
    row: Mapping[str, Any],
    judge_model_id: str,
    principle_id: int,
    max_attempts: int,
    trace_writer: Any,
) -> dict[str, Any]:
    principle = _load_constitution_subset([principle_id])
    if len(principle) != 1:
        raise RuntimeError(f"Principle {principle_id} was not found")

    judge = _judge_for_model(judge_model_id)
    scores = judges_mod.judge_panel(
        prompt=str(row.get("prompt") or ""),
        response_dict={
            "response": str(row.get("response") or ""),
            "triage_json": row.get("triage_parsed") or {},
            "triage_parse_succeeded": bool(row.get("parse_succeeded")),
            "reference_risk_tier": row.get("reference_risk_tier"),
            "reference_context": next((r for r in _load_reference_set() if r["id"] == row.get("prompt_id")), {}),
        },
        panel_model_id=str(row.get("model_id") or ""),
        constitution=principle,
        jury=[judge],
        rubric_pack_version="health_safety_v1",
        retrieve_calibration=True,
        calibration_k=3,
        trace_writer=trace_writer,
        prompt_id=str(row.get("prompt_id") or ""),
        prompt_template_version="health_reference_risk_retry_v1",
        dataset_version="healtheval_health_v1",
        strategy_version=f"health_reference_risk_retry_v1:{row.get('model_id')}",
        max_workers=1,
        max_judge_attempts=max_attempts,
    )
    if len(scores) != 1:
        raise RuntimeError(
            f"Expected one retry score for {row.get('prompt_id')} / "
            f"{judge_model_id} / P{principle_id}, got {len(scores)}"
        )
    serialised = _serialise_scores(scores)[0]
    if _score_is_failed(serialised):
        raise RuntimeError(
            f"Retry still failed for {row.get('model_id')} / "
            f"{row.get('prompt_id')} / {judge_model_id} / P{principle_id}: "
            f"{serialised.get('rationale')}"
        )
    return serialised


def _update_row_decision(
    row: dict[str, Any],
    calibration: Mapping[str, Any],
) -> dict[str, Any]:
    decision = _decision_from_scores(
        row.get("judge_scores", []),
        row.get("triage_parsed") or {},
        calibration,
    )
    row["decision"] = decision
    row["judge_mean"] = decision.get("jury_safety_mean")
    return {
        "model_id": row.get("model_id"),
        "flagged": bool(decision.get("flagged", False)),
        "triage_label": decision.get("triage_label"),
        "jury_safety_mean": decision.get("jury_safety_mean"),
        "reference_risk_tier": row.get("reference_risk_tier"),
        "n_cells": decision.get("n_cells", 0),
        "n_total_cells": decision.get("n_total_cells", 0),
        "n_failed_judge_cells": decision.get("n_failed_judge_cells", 0),
        "judge_score_incomplete": bool(decision.get("judge_score_incomplete", False)),
        "parse_succeeded": bool(row.get("parse_succeeded")),
        "calibration_id": calibration.get("id", ""),
    }


def _count_failures(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in rows
        for score in row.get("judge_scores", [])
        if _score_is_failed(score)
    )


def repair_model(
    *,
    model_id: str,
    calibration: Mapping[str, Any],
    total_prompts: int,
    max_attempts: int,
    sleep_sec: float,
    dry_run: bool,
    workers: int,
    trace_replacements: Mapping[tuple[str, str, str, int], dict[str, Any]],
) -> int:
    artifact = _load_existing_model_artifact(model_id)
    if not artifact:
        print(f"{model_id}: no artifact found; skipped")
        return 0

    rows = [dict(row) for row in artifact.get("rows", [])]
    evaluator_outputs = dict(artifact.get("evaluator_outputs", {}) or {})
    trace_writer = judges_mod.make_jsonl_trace_writer(TRACE_PATH)
    repaired = 0
    jobs: list[tuple[dict[str, Any], str, int]] = []

    for row in rows:
        scores = [dict(score) for score in row.get("judge_scores", [])]
        row["judge_scores"] = scores
        failed = [
            dict(score)
            for score in scores
            if _score_is_failed(score)
        ]
        if not failed:
            continue

        for score in failed:
            judge_model_id = str(score.get("judge_model_id") or "")
            principle_id = int(score.get("principle_id") or 0)
            key = _trace_key(
                model_id,
                str(row.get("prompt_id") or ""),
                judge_model_id,
                principle_id,
            )
            if key in trace_replacements:
                _replace_score(scores, trace_replacements[key])
                repaired += 1
                continue

            print(
                f"{model_id} {row.get('prompt_id')} {judge_model_id} "
                f"P{principle_id}: retrying",
                flush=True,
            )
            if dry_run:
                repaired += 1
            else:
                jobs.append((row, judge_model_id, principle_id))

    if jobs and not dry_run:
        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
            futures = {
                pool.submit(
                    _retry_one_score,
                    row=row,
                    judge_model_id=judge_model_id,
                    principle_id=principle_id,
                    max_attempts=max_attempts,
                    trace_writer=trace_writer,
                ): (row, judge_model_id, principle_id)
                for row, judge_model_id, principle_id in jobs
            }
            for future in as_completed(futures):
                row, judge_model_id, principle_id = futures[future]
                try:
                    replacement = future.result()
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        f"{model_id} {row.get('prompt_id')} {judge_model_id} "
                        f"P{principle_id}: {exc}"
                    )
                    print(errors[-1], flush=True)
                    continue
                _replace_score(row["judge_scores"], replacement)
                repaired += 1
                if sleep_sec > 0:
                    time.sleep(sleep_sec)
                print(
                    f"{model_id} {row.get('prompt_id')} {judge_model_id} "
                    f"P{principle_id}: repaired",
                    flush=True,
                )
        if errors:
            print(
                f"{model_id}: {len(errors)} retry jobs still failed; "
                "successful jobs will still be saved.",
                flush=True,
            )

    for row in rows:
        evaluator_outputs[str(row.get("prompt_id"))] = _update_row_decision(
            row,
            calibration,
        )

    remaining = _count_failures(rows)
    if not dry_run:
        _write_json(
            _artifact_path(model_id),
            _model_artifact_payload(
                model_id=model_id,
                rows=rows,
                evaluator_outputs=evaluator_outputs,
                total=total_prompts,
                jury_ids=list(artifact.get("jury", []) or []),
                calibration=calibration,
                judge_mode=str(artifact.get("judge_mode") or "final_safety_method"),
            ),
        )
    print(f"{model_id}: repaired={repaired}, remaining={remaining}", flush=True)
    if remaining and not dry_run:
        raise RuntimeError(f"{model_id} still has {remaining} failed judge cells")
    return repaired


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Retry failed judge cells in saved HealthEval panel artifacts.",
    )
    parser.add_argument("--models", default=None, help="Comma-separated panel subset.")
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--sleep-sec", type=float, default=0.5)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    load_dotenv(REPO_ROOT / ".env")
    model_ids = _parse_models(args.models)
    refset = _load_reference_set()
    calibration = _load_final_calibration()
    trace_replacements = _load_trace_replacements(model_ids)
    if trace_replacements:
        print(
            f"Found {len(trace_replacements)} usable judge cells in trace.",
            flush=True,
        )

    total_repaired = 0
    for model_id in model_ids:
        total_repaired += repair_model(
            model_id=model_id,
            calibration=calibration,
            total_prompts=len(refset),
            max_attempts=max(1, int(args.max_attempts)),
            sleep_sec=max(0.0, float(args.sleep_sec)),
            dry_run=bool(args.dry_run),
            workers=max(1, int(args.workers)),
            trace_replacements=trace_replacements,
        )

    if not args.dry_run:
        combined = _combine_panel_artifacts(
            model_ids,
            total_prompts=len(refset),
            calibration=calibration,
        )
        _write_json(OUT_PANEL, combined)
    print(f"Total repaired judge cells: {total_repaired}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
