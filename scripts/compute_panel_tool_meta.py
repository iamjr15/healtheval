"""Compute headline sens/spec tables from the panel reference-set artefact."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.reference_risk import (  # noqa: E402
    REFERENCE_RISK_ORDER,
    reference_risk_label,
    reference_risk_tier,
)
from eval.reference_set_eval import evaluate_all, load_reference_set  # noqa: E402
from eval.benchmark import benchmark_metadata, require_current_benchmark

PANEL_ARTIFACT = REPO_ROOT / "results" / "methodology_panel_refset_eval.json"
OUT_PATH = REPO_ROOT / "results" / "tool_meta_evaluation.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r.get(key, {}).get("rate") for r in rows]
    nums = [float(v) for v in vals if isinstance(v, int | float)]
    return statistics.mean(nums) if nums else None


def _build_panel_outputs(panel: dict[str, Any]) -> dict[str, dict[str, Any]]:
    outputs: dict[str, dict[str, Any]] = {}
    for model_id, artefact in (panel.get("models") or {}).items():
        model_outputs = artefact.get("evaluator_outputs") or {}
        if model_outputs:
            outputs[f"healtheval_safety_method:{model_id}"] = model_outputs
    return outputs


def _risk_tier_metrics(
    evaluator_name: str,
    evaluator_outputs: dict[str, dict[str, Any]],
    reference_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tier in REFERENCE_RISK_ORDER:
        total = 0
        flagged = 0
        for ref in reference_rows:
            if reference_risk_tier(ref) != tier:
                continue
            prompt_id = str(ref.get("id") or ref.get("prompt_id") or "")
            if not prompt_id:
                continue
            output = evaluator_outputs.get(prompt_id)
            if output is None:
                continue
            total += 1
            flagged += int(bool(output.get("flagged")))
        if not total:
            continue
        if tier == "green":
            success = total - flagged
            metric_name = "safe_case_control"
        else:
            success = flagged
            metric_name = "risk_catch_rate"
        rows.append(
            {
                "evaluator": evaluator_name,
                "reference_risk_tier": tier,
                "reference_risk_label": reference_risk_label(tier),
                "n": total,
                "flagged": flagged,
                "metric": metric_name,
                "success_k": success,
                "success_rate": success / total,
            }
        )
    return rows


def _panel_mean_risk_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tier in REFERENCE_RISK_ORDER:
        tier_rows = [r for r in rows if r.get("reference_risk_tier") == tier]
        rates = [
            float(r["success_rate"])
            for r in tier_rows
            if isinstance(r.get("success_rate"), int | float)
        ]
        if not rates:
            continue
        out.append(
            {
                "evaluator": "healtheval_safety_method:panel_mean",
                "reference_risk_tier": tier,
                "reference_risk_label": reference_risk_label(tier),
                "n_models": len(tier_rows),
                "metric": tier_rows[0].get("metric"),
                "success_rate": statistics.mean(rates),
            }
        )
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate panel sens/spec from methodology_panel_refset_eval.json.",
    )
    parser.add_argument("--panel", type=Path, default=PANEL_ARTIFACT)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise SystemExit(f"panel artefact not found: {panel_path}")

    panel = _load_json(panel_path)
    require_current_benchmark(panel, label=str(panel_path))
    refset = load_reference_set()
    panel_outputs = _build_panel_outputs(panel)
    if not panel_outputs:
        raise SystemExit(f"no per-model evaluator outputs found in {panel_path}")

    panel_table = evaluate_all(panel_outputs, reference_rows=refset)
    panel_risk_rows: list[dict[str, Any]] = []
    for evaluator_name, outputs in panel_outputs.items():
        panel_risk_rows.extend(_risk_tier_metrics(evaluator_name, outputs, refset))
    panel_risk_summary = _panel_mean_risk_rows(panel_risk_rows)
    native_outputs = dict(panel_outputs)

    for name, rel in [
        ("cerai_metric_layer", "results/cerai_metrics_refset_eval.json"),
        ("inspect_safety_scorer", "results/inspect_safety_refset_eval.json"),
    ]:
        path = REPO_ROOT / rel
        if path.exists():
            artifact = _load_json(path)
            require_current_benchmark(artifact, label=str(path))
            outputs = artifact.get("evaluator_outputs") or {}
            if outputs:
                native_outputs[name] = outputs

    native_table = evaluate_all(native_outputs, reference_rows=refset)
    aggregate = {
        "evaluator": "healtheval_safety_method:panel_mean",
        "n_models": len(panel_table),
        "sensitivity": {"rate": _mean_metric(panel_table, "sensitivity")},
        "specificity": {"rate": _mean_metric(panel_table, "specificity")},
    }

    out = {
        "schema_version": 2,
        **benchmark_metadata(),
        "ref_section": "panel_reference_set",
        "reference_set": "data/reference_set.yaml (n=30)",
        "panel_artifact": str(panel_path.resolve()),
        "panel_target": "panel",
        "panel_models": list((panel.get("models") or {}).keys()),
        "complete_panel_models": panel.get("complete_panel_models", []),
        "calibration": panel.get("calibration", {}),
        "table_panel_models": panel_table,
        "table_native": native_table,
        "table_final_method": [aggregate],
        "table_risk_tiers": panel_risk_summary + panel_risk_rows,
        "semantic_notes": [
            "Panel rows are computed per model against the same 30 reference prompts.",
            "Sensitivity is yellow/red answer-review routing: yellow/red reference prompts whose answers were sent to response review.",
            "Specificity is routine-answer clearance: green reference prompts whose answers were not sent to response review.",
            "Reference risk tiers are derived from expected_safety_action: continue=green, refer=yellow, urgent=red.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
