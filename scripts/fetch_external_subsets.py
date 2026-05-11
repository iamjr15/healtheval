"""Fetch + verify the external source CSVs that ground the hand-translated
Hindi subsets in `data/equity_subset_hindi.yaml` + `data/safety_subset_hindi.yaml`.

Run from repo root:

    python scripts/fetch_external_subsets.py

Per the reproducibility gate (clone-and-run reviewer requirement) + the translated-subset provenance check + Codex R6.
This script is the canonical reproducibility hook: pinned SHA-256 hashes
detect upstream drift, and the subset YAMLs are then validated against the
Pydantic schemas in `data/schemas.py`.

The script does NOT regenerate the YAMLs themselves — those carry the
candidate's hand-curated 60 + 30 selections + Claude LLM-draft Hindi
translations and are versioned in git. Re-fetching only the source CSVs
lets reviewers verify provenance.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from collections import Counter
from pathlib import Path
# Pinned source URLs + SHA-256 hashes (verified 2026-05-10)
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / ".cache"

# Make `data` package importable when this script is run from anywhere.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCES: list[tuple[str, str, str]] = [
    # (url, dest filename, sha256)
    (
        "https://huggingface.co/datasets/katielink/EquityMedQA/resolve/main/equitymedqa_trinds.csv",
        "equitymedqa_trinds.csv",
        "124ec1bc3e81c026ea545693c53597c3229a69ece16321a7fdfd223bcaebcfc3",
    ),
    (
        "https://raw.githubusercontent.com/AI4LIFE-GROUP/med-safety-bench/main/datasets/test/gpt4/med_safety_demonstrations_category_1.csv",
        "msb_cat1.csv",
        "026f2fe4d38a8b04f91f23eb84bce4224fa1781120ca93636b93d445ca4392af",
    ),
    (
        "https://raw.githubusercontent.com/AI4LIFE-GROUP/med-safety-bench/main/datasets/test/gpt4/med_safety_demonstrations_category_4.csv",
        "msb_cat4.csv",
        "7d1ff42903d1636dae66e6af647c4405bcd3ff5c7d149ad33d23408d20b964ce",
    ),
    (
        "https://raw.githubusercontent.com/AI4LIFE-GROUP/med-safety-bench/main/datasets/test/gpt4/med_safety_demonstrations_category_8.csv",
        "msb_cat8.csv",
        "67a199a57ecd7845e722ac9c512c99ae2270f9b4418341f0efb1b5b0f98cb702",
    ),
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_one(url: str, dest: Path, expected_sha: str) -> tuple[bool, str]:
    """Download `url` to `dest`, verify SHA-256. Returns (ok, message)."""
    if dest.exists() and _sha256(dest) == expected_sha:
        return True, f"  ✓ {dest.name} (cached, sha256 verified)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:  # noqa: BLE001 — we want any fetch failure surfaced
        return False, f"  ✗ {dest.name} fetch failed: {e}"
    actual = _sha256(dest)
    if actual != expected_sha:
        return False, (
            f"  ✗ {dest.name} SHA-256 mismatch: "
            f"expected {expected_sha[:12]}…, got {actual[:12]}… "
            "(upstream may have changed; source pin in the README needs updating)"
        )
    return True, f"  ✓ {dest.name} fetched + sha256 verified"


def validate_yaml_subsets() -> tuple[bool, list[str]]:
    """Validate the two subset YAMLs against their Pydantic schemas."""
    msgs: list[str] = []
    try:
        import yaml  # type: ignore

        from data.schemas import EquitySubset, SafetySubset
    except ImportError as e:
        return False, [f"  ✗ import failure: {e}"]

    ok = True
    for path, cls in [
        (ROOT / "data" / "equity_subset_hindi.yaml", EquitySubset),
        (ROOT / "data" / "safety_subset_hindi.yaml", SafetySubset),
    ]:
        if not path.exists():
            ok = False
            msgs.append(f"  ✗ {path.name} missing")
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            obj = cls.model_validate(doc)
            msgs.append(f"  ✓ {path.name} validates ({len(obj.items)} items)")
        except Exception as e:  # noqa: BLE001
            ok = False
            msgs.append(f"  ✗ {path.name} validation failed: {e}")
    return ok, msgs


def manifest() -> list[str]:
    """Print a small distribution manifest for the two subset YAMLs."""
    try:
        import yaml  # type: ignore

        from data.schemas import EquitySubset, SafetySubset
    except ImportError:
        return ["  (manifest skipped — missing pyyaml or data.schemas)"]
    out: list[str] = []
    eq = EquitySubset.model_validate(
        yaml.safe_load((ROOT / "data" / "equity_subset_hindi.yaml").read_text("utf-8"))
    )
    sf = SafetySubset.model_validate(
        yaml.safe_load((ROOT / "data" / "safety_subset_hindi.yaml").read_text("utf-8"))
    )
    out.append(f"  EquitySubset: {len(eq.items)} items")
    out.append(f"    by category:        {dict(Counter(i.category.value for i in eq.items))}")
    out.append(f"    by equity_axis_tag: {dict(Counter(i.equity_axis_tag for i in eq.items))}")
    out.append(f"  SafetySubset: {len(sf.items)} items")
    out.append(f"    by category:        {dict(Counter(i.category.value for i in sf.items))}")
    out.append(f"    expected_refusal:   {sum(1 for i in sf.items if i.expected_refusal)} of {len(sf.items)}")
    return out


def main() -> int:
    print("Fetching external source CSVs…")
    print(f"  cache dir: {CACHE_DIR.relative_to(ROOT)}")
    print()

    fetch_ok = True
    for url, name, sha in SOURCES:
        ok, msg = fetch_one(url, CACHE_DIR / name, sha)
        print(msg)
        fetch_ok = fetch_ok and ok

    print()
    print("Validating subset YAMLs against Pydantic schemas…")
    val_ok, val_msgs = validate_yaml_subsets()
    for m in val_msgs:
        print(m)

    print()
    print("Manifest:")
    for line in manifest():
        print(line)

    if fetch_ok and val_ok:
        print()
        print("All checks passed.")
        return 0
    print()
    print("FAILED — see messages above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
