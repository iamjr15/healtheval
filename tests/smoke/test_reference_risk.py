"""Reference-risk tier mapping smoke tests."""

from __future__ import annotations

import yaml

from eval.reference_risk import (
    REFERENCE_RISK_ORDER,
    reference_risk_tier,
    risk_tier_from_expected_action,
)


def test_expected_action_maps_to_reference_risk_tier() -> None:
    assert risk_tier_from_expected_action("continue") == "green"
    assert risk_tier_from_expected_action("refer") == "yellow"
    assert risk_tier_from_expected_action("urgent") == "red"


def test_reference_set_covers_all_reference_risk_tiers(repo_root) -> None:
    data = yaml.safe_load((repo_root / "data" / "reference_set.yaml").read_text())
    tiers = {reference_risk_tier(item) for item in data["items"]}
    assert tiers == set(REFERENCE_RISK_ORDER)
