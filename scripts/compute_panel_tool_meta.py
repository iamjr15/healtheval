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

from eval.reference_set_eval import evaluate_all, load_reference_set  # noqa: E402

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
            outputs[f"maaswasth_safety_method:{model_id}"] = model_outputs
    return outputs


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
    refset = load_reference_set()
    panel_outputs = _build_panel_outputs(panel)
    if not panel_outputs:
        raise SystemExit(f"no per-model evaluator outputs found in {panel_path}")

    panel_table = evaluate_all(panel_outputs, reference_rows=refset)
    native_outputs = dict(panel_outputs)

    for name, rel in [
        ("cerai_metric_layer", "results/cerai_metrics_refset_eval.json"),
        ("inspect_safety_scorer", "results/inspect_safety_refset_eval.json"),
    ]:
        path = REPO_ROOT / rel
        if path.exists():
            artifact = _load_json(path)
            outputs = artifact.get("evaluator_outputs") or {}
            if outputs:
                native_outputs[name] = outputs

    native_table = evaluate_all(native_outputs, reference_rows=refset)
    aggregate = {
        "evaluator": "maaswasth_safety_method:panel_mean",
        "n_models": len(panel_table),
        "sensitivity": {"rate": _mean_metric(panel_table, "sensitivity")},
        "specificity": {"rate": _mean_metric(panel_table, "specificity")},
    }

    out = {
        "schema_version": 2,
        "ref_section": "panel_reference_set",
        "reference_set": "data/reference_set.yaml (n=30)",
        "panel_artifact": str(panel_path.relative_to(REPO_ROOT)),
        "panel_target": "panel",
        "panel_models": list((panel.get("models") or {}).keys()),
        "complete_panel_models": panel.get("complete_panel_models", []),
        "calibration": panel.get("calibration", {}),
        "table_panel_models": panel_table,
        "table_native": native_table,
        "table_final_method": [aggregate],
        "semantic_notes": [
            "Panel rows are computed per model against the same 30 reference prompts.",
            "Catch rate is sensitivity: unsafe/reference-risk cases flagged by the method.",
            "False-alarm control is specificity: safe cases not over-routed to review.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
