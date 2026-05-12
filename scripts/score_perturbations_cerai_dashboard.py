"""Score 35 perturbation cells through CeRAI's actual dashboard analyzer.

Rather than reimplementing CeRAI's LLM-judge in-process, this script:

1. Inserts 105 new TestCases (35 cells × 3 metrics: Accuracy, Relevance, Hallucination)
   into CeRAI's docker database, mirroring the existing run 25/26/27 structure.
2. Creates 3 new TestRuns (one per metric) using target_id=13 (sarvam-105b-neutral-mnh).
3. Creates 105 TestRunDetails linking testcases to runs.
4. Inserts 105 Conversations rows with `agent_response` pre-filled to the cell's response text
   (original or perturbed). `evaluation_score` stays NULL until the analyzer fills it.
5. Invokes CeRAI's `response_analyzer/analyze.py` via `docker exec` for each new run.
6. Pulls back the resulting evaluation_score values from Conversations.

The analyzer uses CeRAI's own LLM-as-judge stack (DeepEval llm_judge_positive / hallucination_haluqa)
with the same prompts and judge configuration that produced run 25/26/27. This makes the
robustness comparison apples-to-apples: every score in `results/perturbation_scores_cerai.json`
comes from the same scoring pipeline that produced CeRAI's existing baseline runs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"
PERT_PATH = REPO_ROOT / "data" / "perturbations" / "perturbed_responses.jsonl"
OUT_PATH = REPO_ROOT / "results" / "perturbation_scores_cerai.json"

DOCKER_DB = "aiet-db"
DOCKER_APP = "aiet-app-backend"
DB_USER = "aiet_user"
DB_PASS = "aiet_password"
DB_NAME = "aievaluationtool"

TARGET_ID = 13  # sarvam-105b-neutral-mnh

# Existing testcase ids in CeRAI's DB, mapping ref_id -> (acc_tc, rel_tc, hall_tc)
EXISTING_TESTCASE_TEMPLATES = {
    "ref-001": (572, 602, 633),
    "ref-007": (None, None, None),  # filled at runtime via DB query
    "ref-009": (None, None, None),
    "ref-012": (None, None, None),
    "ref-024": (None, None, None),
}

METRIC_CONFIG = {
    "accuracy": {
        "metric_id": 36,
        "plan_id": 5,
        "strategy_id": 14,  # llm_judge_positive
        "judge_prompt_id": 19,
        "run_name_suffix": "perturbation_audit_accuracy_20260513",
    },
    "relevance": {
        "metric_id": 13,
        "plan_id": 2,
        "strategy_id": 14,
        "judge_prompt_id": 20,
        "run_name_suffix": "perturbation_audit_relevance_20260513",
    },
    "hallucination": {
        "metric_id": 27,
        "plan_id": 3,
        "strategy_id": 36,  # hallucination_haluqa
        "judge_prompt_id": None,
        "run_name_suffix": "perturbation_audit_hallucination_20260513",
    },
}

REF_ID_TO_PROMPT_ID = {
    "ref-001": 483,
    "ref-007": 489,
    "ref-009": 491,
    "ref-012": 494,
    "ref-024": 506,
}


def _sql(query: str, *, fetch: bool = True) -> str:
    """Run a SQL query inside the aiet-db container and return raw output."""
    cmd = [
        "docker", "exec", DOCKER_DB,
        "mariadb", f"-u{DB_USER}", f"-p{DB_PASS}", DB_NAME,
        "-N", "-B", "-e", query,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def _sql_execute(query: str) -> None:
    """Execute a write query."""
    _sql(query, fetch=False)


def _escape_sql(s: str) -> str:
    """Minimal SQL string escape for MariaDB single-quoted strings."""
    return s.replace("\\", "\\\\").replace("'", "''")


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.open(encoding="utf-8")]


def _lookup_existing_testcase_ids() -> None:
    """Fill EXISTING_TESTCASE_TEMPLATES by querying the DB for ref-007/009/012/024 testcases."""
    for ref_id in REF_ID_TO_PROMPT_ID:
        pid = REF_ID_TO_PROMPT_ID[ref_id]
        # Find one testcase_id per metric for this prompt
        rows = _sql(
            f"""SELECT tc.testcase_id, m.metric_name
                FROM TestCases tc
                JOIN TestRunDetails trd ON trd.testcase_id=tc.testcase_id
                JOIN Metrics m ON m.metric_id=trd.metric_id
                WHERE tc.prompt_id={pid} AND trd.run_id IN (25,26,27)
                GROUP BY tc.testcase_id, m.metric_name"""
        )
        acc_tc = rel_tc = hall_tc = None
        for line in rows.splitlines():
            parts = line.split("\t")
            if len(parts) != 2:
                continue
            tc_id, mname = parts
            if mname == "Accuracy":
                acc_tc = int(tc_id)
            elif mname == "Relevance_and_Information":
                rel_tc = int(tc_id)
            elif mname == "Hallucination_Rate":
                hall_tc = int(tc_id)
        EXISTING_TESTCASE_TEMPLATES[ref_id] = (acc_tc, rel_tc, hall_tc)
        print(f"  template testcases for {ref_id}: acc={acc_tc} rel={rel_tc} hall={hall_tc}")


def _get_response_id_for_testcase(tc_id: int) -> int | None:
    out = _sql(f"SELECT response_id FROM TestCases WHERE testcase_id={tc_id}")
    if not out or out == "NULL":
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _create_run(run_name: str, plan_id: int) -> int:
    """Insert a new TestRun and return its run_id."""
    _sql_execute(
        f"""INSERT INTO TestRuns (run_name, target_id, status, start_ts)
            VALUES ('{run_name}', {TARGET_ID}, 'NEW', NOW())"""
    )
    out = _sql(f"SELECT run_id FROM TestRuns WHERE run_name='{run_name}'")
    return int(out.strip())


def _create_testcase(*, name: str, prompt_id: int, response_id: int | None,
                     strategy_id: int, judge_prompt_id: int | None,
                     metric_id: int) -> int:
    rid = f"{response_id}" if response_id is not None else "NULL"
    jpid = f"{judge_prompt_id}" if judge_prompt_id is not None else "NULL"
    _sql_execute(
        f"""INSERT INTO TestCases (testcase_name, prompt_id, response_id, strategy_id, judge_prompt_id)
            VALUES ('{name}', {prompt_id}, {rid}, {strategy_id}, {jpid})"""
    )
    out = _sql(f"SELECT testcase_id FROM TestCases WHERE testcase_name='{name}'")
    tc_id = int(out.strip())
    # CeRAI's analyzer reads metric via MetricTestCaseMapping — required for get_testcase_by_name.
    _sql_execute(
        f"INSERT INTO MetricTestCaseMapping (testcase_id, metric_id) VALUES ({tc_id}, {metric_id})"
    )
    return tc_id


def _create_detail(*, run_id: int, plan_id: int, metric_id: int, testcase_id: int) -> int:
    _sql_execute(
        f"""INSERT INTO TestRunDetails (run_id, plan_id, metric_id, testcase_id, testcase_status)
            VALUES ({run_id}, {plan_id}, {metric_id}, {testcase_id}, 'NEW')"""
    )
    out = _sql(
        f"SELECT detail_id FROM TestRunDetails WHERE run_id={run_id} AND testcase_id={testcase_id} AND metric_id={metric_id}"
    )
    return int(out.strip())


def _create_conversation(*, detail_id: int, agent_response: str) -> None:
    escaped = _escape_sql(agent_response)
    _sql_execute(
        f"""INSERT INTO Conversations (target_id, detail_id, agent_response, prompt_ts, response_ts)
            VALUES ({TARGET_ID}, {detail_id}, '{escaped}', NOW(), NOW())"""
    )


def _mark_run_completed(run_id: int) -> None:
    _sql_execute(
        f"UPDATE TestRuns SET status='COMPLETED', end_ts=NOW() WHERE run_id={run_id}"
    )
    _sql_execute(
        f"UPDATE TestRunDetails SET testcase_status='COMPLETED' WHERE run_id={run_id}"
    )


def _run_analyzer(run_name: str) -> str:
    """Execute CeRAI's response_analyzer/analyze.py for the run inside the app container."""
    cmd = [
        "docker", "exec", DOCKER_APP,
        "python", "/app/src/app/response_analyzer/analyze.py",
        "--run-name", run_name,
        "--config", "config.json",
        "--verbosity", "3",
    ]
    print(f"  $ docker exec {DOCKER_APP} analyze.py --run-name {run_name}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout + "\n---STDERR---\n" + res.stderr


def _fetch_scores(run_id: int) -> list[dict[str, Any]]:
    """Pull conversation scores for the run."""
    sql = (
        "SELECT tc.testcase_name, c.evaluation_score, "
        "LEFT(COALESCE(c.evaluation_reason,''),200) AS reason "
        f"FROM Conversations c JOIN TestRunDetails trd ON trd.detail_id=c.detail_id "
        f"JOIN TestCases tc ON tc.testcase_id=trd.testcase_id "
        f"WHERE trd.run_id={run_id} ORDER BY c.conversation_id"
    )
    out = _sql(sql)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        name = parts[0]
        score_raw = parts[1]
        reason = parts[2] if len(parts) >= 3 else ""
        score = None if score_raw in ("NULL", "") else float(score_raw)
        rows.append({"testcase_name": name, "evaluation_score": score, "reason": reason})
    return rows


def _parse_cell_from_testcase_name(name: str) -> tuple[str, str] | None:
    """`perturb-ref-001-script_swap-accuracy` -> ('ref-001', 'script_swap')."""
    prefix = "perturb-"
    if not name.startswith(prefix):
        return None
    body = name[len(prefix):]
    # body = ref-XXX-<perturbation>-<metric>
    # but ref-XXX contains a dash; split carefully
    parts = body.split("-")
    if len(parts) < 4 or parts[0] != "ref":
        return None
    ref_id = f"ref-{parts[1]}"
    metric = parts[-1]
    perturbation = "-".join(parts[2:-1])
    return ref_id, perturbation, metric  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-insert", action="store_true",
                        help="Skip DB inserts (use when re-running after a partial failure)")
    parser.add_argument("--skip-analyze", action="store_true",
                        help="Skip the analyzer invocation (just dump current scores)")
    parser.add_argument("--metrics", default="accuracy,relevance,hallucination",
                        help="Comma-separated metric names to run")
    args = parser.parse_args()

    selected = [m.strip() for m in args.metrics.split(",") if m.strip()]
    metrics_to_run = {m: METRIC_CONFIG[m] for m in selected if m in METRIC_CONFIG}
    if not metrics_to_run:
        print(f"No valid metrics in {args.metrics}", file=sys.stderr)
        return 1

    bases = _load_jsonl(BASE_PATH)
    perts = _load_jsonl(PERT_PATH)
    base_lookup = {b["prompt_id"]: b for b in bases}

    print("Looking up existing testcase templates for response_id reuse...")
    _lookup_existing_testcase_ids()

    # Build the (cell_id, response_text) inventory
    cells: list[tuple[str, str, str]] = []  # (ref_id, perturbation_type, agent_response)
    for b in bases:
        cells.append((b["prompt_id"], "original", b["base_response"]))
    for p in perts:
        cells.append((p["prompt_id"], p["perturbation_type"], p["perturbed_response"]))
    print(f"Total cells to score: {len(cells)}")

    results: dict[str, Any] = {
        "schema_version": 1,
        "evaluator_name": "cerai_dashboard_analyzer",
        "judge_pipeline": "CeRAI response_analyzer/analyze.py (DeepEval llm_judge_positive + hallucination_haluqa)",
        "cells": [],
    }

    cell_results: dict[tuple[str, str], dict[str, Any]] = {}

    for metric_name, cfg in metrics_to_run.items():
        run_name = cfg["run_name_suffix"]
        print(f"\n=== Metric: {metric_name} | run_name={run_name} ===")

        if not args.skip_insert:
            run_id = _create_run(run_name, cfg["plan_id"])
            print(f"  created run_id={run_id}")

            for ref_id, ptype, response in cells:
                prompt_id = REF_ID_TO_PROMPT_ID[ref_id]
                template_tc_id = {
                    "accuracy": EXISTING_TESTCASE_TEMPLATES[ref_id][0],
                    "relevance": EXISTING_TESTCASE_TEMPLATES[ref_id][1],
                    "hallucination": EXISTING_TESTCASE_TEMPLATES[ref_id][2],
                }[metric_name]
                response_id = _get_response_id_for_testcase(template_tc_id) if template_tc_id else None

                tc_name = f"perturb-{ref_id}-{ptype}-{metric_name}"
                tc_id = _create_testcase(
                    name=tc_name,
                    prompt_id=prompt_id,
                    response_id=response_id,
                    strategy_id=cfg["strategy_id"],
                    judge_prompt_id=cfg["judge_prompt_id"],
                    metric_id=cfg["metric_id"],
                )
                detail_id = _create_detail(
                    run_id=run_id, plan_id=cfg["plan_id"],
                    metric_id=cfg["metric_id"], testcase_id=tc_id,
                )
                _create_conversation(detail_id=detail_id, agent_response=response)
            print(f"  inserted 35 testcases + details + conversations for {metric_name}")
        else:
            out = _sql(f"SELECT run_id FROM TestRuns WHERE run_name='{run_name}'")
            run_id = int(out.strip())
            print(f"  reusing existing run_id={run_id}")

        # Mark the run COMPLETED first — the analyzer rejects runs in NEW status because
        # CeRAI's dispatcher normally sets status=COMPLETED after dispatch. We pre-fill
        # Conversations.agent_response, so dispatch is logically already done.
        _mark_run_completed(run_id)

        if not args.skip_analyze:
            log = _run_analyzer(run_name)
            print(log[-800:])

        rows = _fetch_scores(run_id)
        for r in rows:
            parsed = _parse_cell_from_testcase_name(r["testcase_name"])
            if not parsed:
                continue
            ref_id, ptype, m = parsed
            key = (ref_id, ptype)
            entry = cell_results.setdefault(key, {
                "prompt_id": ref_id,
                "perturbation_type": ptype,
                "scores": {},
                "reasons": {},
            })
            entry["scores"][m] = r["evaluation_score"]
            entry["reasons"][m] = r["reason"]

    for (ref_id, ptype), entry in cell_results.items():
        scores = entry["scores"]
        valid = [v for v in scores.values() if v is not None]
        entry["mean"] = sum(valid) / len(valid) if valid else None
        entry["run_name"] = "perturbation_audit_20260513"

    results["cells"] = list(cell_results.values())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT_PATH}: {len(results['cells'])} cells")
    return 0


if __name__ == "__main__":
    sys.exit(main())
