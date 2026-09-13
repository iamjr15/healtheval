"""Integration: eval-core's `tests/fixtures/sample_findings.json` makes
a lossless round trip through `data.schemas.FindingsSchema`.

Per eval-core's round-2 contract lock — the fixture is a fully populated
FindingsSchema (one FindingsItem with the 36-cell self-judging-avoided
jury, bootstrap CIs, Beta-Binomial CIs, krippendorff_alpha=0.84, all 8
EquityAxis strata). If a downstream layer ever silently changes the
wire format, this test catches it before release.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


# Surviving-jury identities when the panel response is from
# Sarvam-105b (HEALTH-PARIKSHA self-judging avoidance dropping the
# Sarvam judge): exactly Claude + Gemini. Pinned per eval-core's name-
# check canary guidance so any future jury reshuffle that lands back
# on count=2 with a different pair surfaces here. When `DEFAULT_JURY`
# in `eval/judges.py` is reshuffled, eval-core DMs foundation-eng
# with the new identities and we update this set in lockstep.
EXPECTED_SURVIVING_JURY_V1_5_4 = {"claude-sonnet-4-6", "gemini-2.5-pro"}


def _schemas():
    try:
        return importlib.import_module("data.schemas")
    except ModuleNotFoundError as e:
        pytest.skip(f"data.schemas not importable: {e}")


def _fixture_path(repo_root: Path) -> Path:
    p = repo_root / "tests" / "fixtures" / "sample_findings.json"
    if not p.exists():
        pytest.skip(f"eval-core fixture not present: {p.relative_to(repo_root)}")
    return p


def test_sample_findings_round_trips(repo_root):
    schemas = _schemas()
    raw = _fixture_path(repo_root).read_text(encoding="utf-8")

    obj = schemas.FindingsSchema.model_validate_json(raw)

    # Round-trip equality: dump → re-validate → dump again must be stable.
    dump_a = obj.model_dump(mode="json")
    obj_b = schemas.FindingsSchema.model_validate(dump_a)
    dump_b = obj_b.model_dump(mode="json")
    assert dump_a == dump_b, "FindingsSchema round-trip lost or mutated fields"

    # Spot-checks on the eval-core contract — sarvam-105b panel response,
    # HEALTH-PARIKSHA avoidance applied (Sarvam-105b judge dropped from
    # the surviving jury rather than emitted as a flagged placeholder),
    # 8 equity axes populated.
    assert obj.items, "fixture has no FindingsItem"
    item = obj.items[0]
    assert item.model_id == "sarvam-105b", f"fixture panel_model_id drift: {item.model_id!r}"

    # Avoidance: surviving frontier-disjoint judges × 12 principles cells.
    # The Sarvam judge MUST NOT appear in the surviving set. The exact
    # surviving-jury cardinality depends on jury composition:
    # Current default -> 2 surviving (Anthropic + Google) -> 24 cells.
    # Cell count is asserted as a multiple of 12 with surviving-jury size
    # in {2, 3} so the test stays valid across the transition without
    # cross-team rework.
    judges_present = {j.judge_model_id for j in item.judges}
    assert "sarvam-105b" not in judges_present, (
        f"HEALTH-PARIKSHA avoidance regressed — sarvam-105b judging a sarvam-105b "
        f"panel response. Jury was: {sorted(judges_present)}"
    )
    n_judges = len(judges_present)
    assert n_judges in (2, 3), (
        f"expected 2 or 3 surviving judges after avoidance; "
        f"got {n_judges}: {judges_present}"
    )
    assert len(item.judges) == n_judges * 12, (
        f"expected {n_judges * 12} cells ({n_judges} judges × 12 principles) "
        f"after avoidance; got {len(item.judges)}"
    )

    # Strong canary — pin the exact surviving-jury identity set
    # when the fixture is at the current cell count. Catches an accidental
    # judge swap that happens to preserve the cardinality (e.g. a future
    # reshuffle landing on a different pair instead of {claude, gemini}).
    if n_judges == 2:
        assert judges_present == EXPECTED_SURVIVING_JURY_V1_5_4, (
            f"jury-identity drift — surviving judges {judges_present} "
            f"!= expected {EXPECTED_SURVIVING_JURY_V1_5_4}. If `DEFAULT_JURY` "
            f"in eval/judges.py was reshuffled, update "
            f"EXPECTED_SURVIVING_JURY_V1_5_4 at top of this file."
        )
    axes = {s.axis for s in item.equity_strata}
    expected_axes = {
        "age_group", "risk_tier", "language_script",
        "frontline_worker_proxy", "crisis_flag_overlap", "geography",
        "caste_community", "education_disability_combined",
    }
    assert expected_axes.issubset(axes), (
        f"equity_strata missing axes: {expected_axes - axes}"
    )
