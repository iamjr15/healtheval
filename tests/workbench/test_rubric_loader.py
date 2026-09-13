"""Tests for streamlit_app.rubric_loader.

Validates the rubric-pack contract Rubric Packs contract against the four shipped YAMLs
and exercises the failure paths so a future rubric drift surfaces in CI
rather than mid-render on Page 7.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from streamlit_app.config import (
    CANONICAL_FAILURE_CATEGORIES,
    RUBRIC_PACKS_V1,
    RUBRICS_DIR,
)
from streamlit_app.rubric_loader import (
    REQUIRED_FIELDS,
    RubricValidationError,
    list_available_pack_keys,
    load_validated_rubric_pack,
    load_validated_rubric_packs,
    validate_rubric_pack,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_all_canonical_packs_validate() -> None:
    packs = load_validated_rubric_packs()
    for canonical_key in RUBRIC_PACKS_V1:
        assert canonical_key in packs, (
            f"canonical pack `{canonical_key}` missing from data/rubrics/; "
            "scaffolder didn't ship Phase 0 BLOCKER?"
        )
    # Every shipped pack passes validation.
    for key, pack in packs.items():
        for field in REQUIRED_FIELDS:
            assert field in pack, f"{key}: missing {field}"


def test_failure_categories_superset_of_canonical() -> None:
    packs = load_validated_rubric_packs()
    for key, pack in packs.items():
        cats = set(pack["failure_categories"])
        missing = [c for c in CANONICAL_FAILURE_CATEGORIES if c not in cats]
        assert not missing, (
            f"{key}: missing canonical failure categories {missing}"
        )


def test_list_available_pack_keys_returns_all_four() -> None:
    keys = list_available_pack_keys()
    assert sorted(keys) == sorted(RUBRIC_PACKS_V1)


def test_validate_rubric_pack_rejects_missing_required(tmp_path: Path) -> None:
    incomplete = {"metric": "x", "version": "v1"}  # everything else missing
    fake_path = tmp_path / "fake.yaml"
    with pytest.raises(RubricValidationError, match="missing required fields"):
        validate_rubric_pack(incomplete, path=fake_path)


def test_validate_rubric_pack_rejects_non_dict(tmp_path: Path) -> None:
    fake_path = tmp_path / "fake.yaml"
    with pytest.raises(RubricValidationError, match="top-level YAML"):
        validate_rubric_pack(["not", "a", "dict"], path=fake_path)  # type: ignore[arg-type]


def test_validate_rubric_pack_rejects_non_numeric_threshold(tmp_path: Path) -> None:
    real_path = next(RUBRICS_DIR.glob("*_v1.yaml"))
    with real_path.open() as f:
        data = yaml.safe_load(f)
    data["pass_fail_threshold"] = "four"  # type: ignore[assignment]
    with pytest.raises(RubricValidationError, match="pass_fail_threshold"):
        validate_rubric_pack(data, path=real_path)


def test_validate_rubric_pack_rejects_score_examples_missing_keys(tmp_path: Path) -> None:
    real_path = next(RUBRICS_DIR.glob("*_v1.yaml"))
    with real_path.open() as f:
        data = yaml.safe_load(f)
    data["score_examples"] = [{"score": 5}]  # missing example_response + why
    with pytest.raises(RubricValidationError, match="score_examples"):
        validate_rubric_pack(data, path=real_path)


def test_validate_rubric_pack_rejects_failure_categories_missing_canonical(
    tmp_path: Path,
) -> None:
    real_path = next(RUBRICS_DIR.glob("*_v1.yaml"))
    with real_path.open() as f:
        data = yaml.safe_load(f)
    data["failure_categories"] = ["only_one_thing"]
    with pytest.raises(RubricValidationError, match="canonical"):
        validate_rubric_pack(data, path=real_path)


def test_load_validated_rubric_pack_missing_file(tmp_path: Path) -> None:
    with pytest.raises(RubricValidationError, match="not found"):
        load_validated_rubric_pack(tmp_path / "no_such.yaml")


@pytest.mark.parametrize("metric", list(RUBRIC_PACKS_V1))
def test_each_pack_has_at_least_one_score_example(metric: str) -> None:
    pack = load_validated_rubric_pack(RUBRICS_DIR / f"{metric}.yaml")
    assert pack["score_examples"], f"{metric}: score_examples empty"
