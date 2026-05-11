"""Integration checks for reference-set size and triage-label coverage."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.integration


def _schemas():
    try:
        return importlib.import_module("data.schemas")
    except ModuleNotFoundError as e:
        pytest.skip(f"data.schemas not importable: {e}")


def _ref_path(repo_root: Path) -> Path:
    p = repo_root / "data" / "reference_set.yaml"
    if not p.exists():
        pytest.skip(f"reference_set.yaml not yet shipped: {p.relative_to(repo_root)}")
    return p


def test_reference_set_size_and_label_coverage(repo_root):
    schemas = _schemas()
    doc = yaml.safe_load(_ref_path(repo_root).read_text(encoding="utf-8"))

    obj = schemas.ReferenceSet(**doc)

    # n=30 — the source-grounded reference-set contract v1.4 LOCKED. ReferenceSet's schema permits the
    # 20-30 range as a viable-shipping band; the smoke check pins the
    # locked target so an accidental drop below 30 surfaces here.
    assert len(obj.items) == 30, (
        f"the source-grounded reference-set contract locks the reference set at n=30; got {len(obj.items)}"
    )

    # Every triage label (RED / AMBER / GREEN) must appear at least
    # once, otherwise per-class sensitivity/specificity is undefined
    # for the missing class.
    labels = {i.expected_triage_label.value for i in obj.items}
    expected = {"RED", "AMBER", "GREEN"}
    assert labels == expected, (
        f"reference_set triage label coverage drift: {labels} (expected {expected})"
    )

    # Each item carries a non-empty factual_checklist — the schema
    # enforces min_length=1, but we re-assert here so the diagnostic
    # is one-line for reviewers reading the gate output.
    bad = [i.id for i in obj.items if not i.factual_checklist]
    assert not bad, f"reference items missing factual_checklist: {bad}"
