"""Smoke (e): Devanagari render-safety regression guard for the
health-translated Hindi subsets.

Adapted from frontend-report's review pass (frontend review pass,
2026-05-10; see `data/equity_subset_hindi_review_notes.md` §1 + §5).
The four automated checks are cheap (~milliseconds for 90 prompts) and
protect the corpus from regression as the candidate's binding bilingual
review pass lands edits.

If any check fails, the corresponding entry has drifted — re-run the
review notes pass before merging.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest
import yaml  # type: ignore

pytestmark = pytest.mark.smoke

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SUBSET_PATHS = [
    REPO_ROOT / "data" / "equity_challenges_hindi.yaml",
    REPO_ROOT / "data" / "safety_challenges_hindi.yaml",
]

DEVANAGARI_DIGITS = set("०१२३४५६७८९")
# Whitespace immediately followed by a Devanagari vowel sign ("matra") —
# detached-matra footgun (U+093E .. U+094D + a few combining marks).
_DETACHED_MATRA_RE = re.compile(r"\s[ा-्ॎ॑-ॗॢ-ॣ]")


def _iter_items() -> list[tuple[str, str]]:
    """Yield (id, hindi_text) for every entry across both subsets."""
    out: list[tuple[str, str]] = []
    for path in SUBSET_PATHS:
        if not path.exists():
            pytest.fail(f"missing subset YAML: {path.relative_to(REPO_ROOT)}")
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in doc["items"]:
            out.append((item["id"], item["hindi_text"]))
            # devanagari_text == hindi_text invariant — check it too
            if "devanagari_text" in item:
                out.append((item["id"] + ".devanagari_text", item["devanagari_text"]))
    return out


def test_corpus_present() -> None:
    items = _iter_items()
    # 180 paired equity + 30 safety, with Hindi and Devanagari fields.
    assert len(items) == 420, f"expected 420 rows across both subsets, got {len(items)}"


def test_unicode_nfc_normalized() -> None:
    """Every Hindi text must be NFC-normalized (rendering correctness)."""
    failures = [
        item_id
        for item_id, text in _iter_items()
        if unicodedata.normalize("NFC", text) != text
    ]
    assert not failures, f"NFC normalization failed for: {failures}"


def test_no_devanagari_digits() -> None:
    """Indian medical writing convention: prefer Latin digits (0-9), not
    Devanagari digits (०-९) for doses, gestational ages, BMI, etc."""
    failures = [
        item_id
        for item_id, text in _iter_items()
        if any(c in DEVANAGARI_DIGITS for c in text)
    ]
    assert not failures, f"Devanagari digits found in: {failures}"


def test_no_detached_matras() -> None:
    """Whitespace-before-vowel-sign indicates a missing or detached
    consonant — the matra would not render correctly."""
    failures = [
        item_id
        for item_id, text in _iter_items()
        if _DETACHED_MATRA_RE.search(text)
    ]
    assert not failures, f"detached matras found in: {failures}"


def test_devanagari_text_contains_devanagari() -> None:
    """Roman/Hinglish inputs carry a separate Devanagari equivalent."""
    for path in SUBSET_PATHS:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in doc['items']:
            assert any('\u0900' <= c <= '\u097f' for c in item['devanagari_text'])
