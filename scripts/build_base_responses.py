"""Pull 5 base responses for the real-world robustness audit.

Source: results/panel_refset_eval/sarvam-105b.json — sarvam-105b's responses to the
30-prompt reference set under the maaswasth system prompt (JSON triage + Hindi prose).
We pick 5 covering: routine-safe (2), unsafe-but-correctly-refused (2), partial-failure (1).

Both robustness-audit evaluators (maaswasth jury, CeRAI metric layer) will score
identical response text. Perturbations modify only the Hindi prose portion; the JSON
triage block is held constant so prose-form variation is the single variable under test.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PANEL_PATH = REPO_ROOT / "results" / "panel_refset_eval" / "sarvam-105b.json"
REFERENCE_SET = REPO_ROOT / "data" / "reference_set.yaml"
OUT_PATH = REPO_ROOT / "data" / "perturbations" / "base_responses.jsonl"

SELECTION = {
    "ref-001": "Routine safe factual: IFA dose question. Tests judge stability on a low-risk informational query.",
    "ref-007": "Routine safe factual: PMSMA scheme info. Tests stability on scheme details.",
    "ref-009": "Unsafe query, correct refusal: home misoprostol abortion. Tests stability of refusal scoring.",
    "ref-012": "Emergency referral: 8-month heavy bleeding + home remedy. Tests stability on emergency-class responses.",
    "ref-024": "Sensitive partial failure: 16-year-old pregnant. Borderline case where evaluators may diverge.",
}

# Match a fenced ```json ... ``` block at the start of the response text.
TRIAGE_BLOCK_RE = re.compile(r"^\s*```json\s*\n(.*?)\n```\s*\n?", re.DOTALL)


def _split_response(response_text: str) -> tuple[str, str]:
    """Return (triage_block, prose). triage_block includes the fences; prose is everything after."""
    m = TRIAGE_BLOCK_RE.match(response_text)
    if not m:
        return "", response_text
    triage_block = response_text[: m.end()].rstrip() + "\n"
    prose = response_text[m.end():].lstrip()
    return triage_block, prose


def _load_reference_set() -> dict[str, dict]:
    with REFERENCE_SET.open(encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    items = doc.get("items") or []
    return {item["id"]: item for item in items}


def main() -> int:
    ref = _load_reference_set()
    panel = json.loads(PANEL_PATH.read_text(encoding="utf-8"))
    rows_by_id = {r["prompt_id"]: r for r in panel.get("rows", [])}

    missing = [p for p in SELECTION if p not in rows_by_id]
    if missing:
        print(f"ERROR: panel data missing prompts: {missing}", file=sys.stderr)
        return 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for ref_id, rationale in SELECTION.items():
            row = rows_by_id[ref_id]
            ref_entry = ref.get(ref_id, {})
            full_response = row["response"]
            triage_block, prose = _split_response(full_response)
            if not triage_block:
                print(f"WARNING: {ref_id} has no parseable JSON triage block", file=sys.stderr)
            record = {
                "prompt_id": ref_id,
                "user_prompt": row["prompt"],
                "base_response": full_response,
                "base_response_prose": prose,
                "base_response_triage_block": triage_block,
                "base_source": f"results/panel_refset_eval/sarvam-105b.json:{ref_id}",
                "violation_expected": bool(ref_entry.get("violation_expected", False)),
                "expected_urgency": ref_entry.get("expected_urgency", "Routine"),
                "selected_rationale": rationale,
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"{ref_id} response_len={len(full_response)} prose_len={len(prose)} triage_len={len(triage_block)}")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
