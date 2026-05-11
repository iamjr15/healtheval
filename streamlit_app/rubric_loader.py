"""Validating loader for ``data/rubrics/{metric}_v{N}.yaml`` packs.

The raw read happens in ``data_loaders.load_rubric_pack`` /
``load_all_rubric_packs`` (which only ``yaml.safe_load`` the file under
``@st.cache_data``).  This module sits on top and **validates** the
shape — confirming every required field is present, ``score_examples``
parses into the documented record shape, and ``failure_categories``
contains the canonical superset.

Per the shipped workbench design the rubric-pack contract the required fields are:

    metric, version, scoring_scale, pass_fail_threshold, score_examples,
    common_false_positives, common_false_negatives, domain_specific_rules,
    language_specific_rules, safety_policy, failure_categories

A missing required field raises ``RubricValidationError`` with a clear
message naming the file + the field.  Optional fields recognised but
not required: ``constitution_principle_ids``, ``description``.

Page 7 (Rubric Packs) calls ``load_validated_rubric_packs()`` so any
drift between the YAML and the page renderer surfaces at startup, not
mid-render.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import CANONICAL_FAILURE_CATEGORIES, RUBRIC_PACKS_V1, RUBRICS_DIR
from .schemas import RubricPack

# Required keys (per the shipped workbench design the rubric-pack contract / Page 7 brief).
REQUIRED_FIELDS: tuple[str, ...] = (
    "metric",
    "version",
    "scoring_scale",
    "pass_fail_threshold",
    "score_examples",
    "common_false_positives",
    "common_false_negatives",
    "domain_specific_rules",
    "language_specific_rules",
    "safety_policy",
    "failure_categories",
)

# Recognised but optional — surface as "extras" without failing.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "constitution_principle_ids",
    "description",
)


class RubricValidationError(ValueError):
    """Raised when a rubric YAML doesn't satisfy the rubric-pack contract schema."""


def _require_list_of_strings(
    value: Any, *, path: Path, field: str
) -> list[str]:
    if not isinstance(value, list):
        raise RubricValidationError(
            f"{path}: field `{field}` must be a list, got {type(value).__name__}"
        )
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise RubricValidationError(
                f"{path}: field `{field}[{i}]` must be a string, got "
                f"{type(item).__name__}"
            )
    return value


def _validate_score_examples(
    value: Any, *, path: Path
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RubricValidationError(
            f"{path}: `score_examples` must be a list, got {type(value).__name__}"
        )
    if not value:
        raise RubricValidationError(f"{path}: `score_examples` is empty")
    for i, ex in enumerate(value):
        if not isinstance(ex, dict):
            raise RubricValidationError(
                f"{path}: `score_examples[{i}]` must be a dict"
            )
        for sub in ("score", "example_response", "why"):
            if sub not in ex:
                raise RubricValidationError(
                    f"{path}: `score_examples[{i}]` missing `{sub}`"
                )
        if not isinstance(ex["score"], (int, float)):
            raise RubricValidationError(
                f"{path}: `score_examples[{i}].score` must be numeric"
            )
    return value


def _validate_scoring_scale(value: Any, *, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RubricValidationError(
            f"{path}: `scoring_scale` must be a mapping (dict)"
        )
    return value


def validate_rubric_pack(data: dict[str, Any], *, path: Path) -> RubricPack:
    """Run the rubric-pack contract contract checks against an already-parsed YAML dict."""
    if not isinstance(data, dict):
        raise RubricValidationError(
            f"{path}: top-level YAML must be a mapping, got "
            f"{type(data).__name__}"
        )

    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise RubricValidationError(
            f"{path}: missing required fields {missing}"
        )

    # Per-field shape checks.
    for str_field in ("metric", "version", "safety_policy"):
        if not isinstance(data[str_field], str) or not data[str_field].strip():
            raise RubricValidationError(
                f"{path}: `{str_field}` must be a non-empty string"
            )

    if not isinstance(data["pass_fail_threshold"], (int, float)):
        raise RubricValidationError(
            f"{path}: `pass_fail_threshold` must be numeric"
        )

    _validate_scoring_scale(data["scoring_scale"], path=path)
    _validate_score_examples(data["score_examples"], path=path)
    for f in (
        "common_false_positives",
        "common_false_negatives",
        "domain_specific_rules",
        "language_specific_rules",
        "failure_categories",
    ):
        _require_list_of_strings(data[f], path=path, field=f)

    # Failure categories must include the canonical superset.
    fc = set(data["failure_categories"])
    missing_canonical = [c for c in CANONICAL_FAILURE_CATEGORIES if c not in fc]
    if missing_canonical:
        raise RubricValidationError(
            f"{path}: `failure_categories` missing canonical entries "
            f"{missing_canonical} (CANONICAL_FAILURE_CATEGORIES "
            f"in streamlit_app.config defines the floor)"
        )

    return data  # type: ignore[return-value]


def load_validated_rubric_pack(path: Path | str) -> RubricPack:
    """Read + validate a single rubric YAML.  Raises on any contract miss."""
    path = Path(path)
    if not path.exists():
        raise RubricValidationError(f"{path}: file not found")
    with path.open() as f:
        data = yaml.safe_load(f)
    return validate_rubric_pack(data, path=path)


def load_validated_rubric_packs(
    rubrics_dir: Path | str | None = None,
    *,
    version: str = "v1",
) -> dict[str, RubricPack]:
    """Read + validate every ``*_{version}.yaml`` in ``rubrics_dir``.

    Returns a dict keyed by ``"<metric>_<version>"`` (e.g.,
    ``"mnh_safety_v1"``) so the caller can join against the canonical
    list in ``config.RUBRIC_PACKS_V1``.  Raises on the first invalid pack.
    """
    base = Path(rubrics_dir) if rubrics_dir else RUBRICS_DIR
    out: dict[str, RubricPack] = {}
    for path in sorted(base.glob(f"*_{version}.yaml")):
        pack = load_validated_rubric_pack(path)
        out[path.stem] = pack
    return out


def list_available_pack_keys(
    rubrics_dir: Path | str | None = None,
    *,
    version: str = "v1",
) -> list[str]:
    """Cheap directory listing — no validation.  For the sidebar selector."""
    base = Path(rubrics_dir) if rubrics_dir else RUBRICS_DIR
    return sorted(p.stem for p in base.glob(f"*_{version}.yaml"))


def list_all_pack_keys(rubrics_dir: Path | str | None = None) -> list[str]:
    """Across all versions — used by the "show all versions" toggle."""
    base = Path(rubrics_dir) if rubrics_dir else RUBRICS_DIR
    return sorted(p.stem for p in base.glob("*.yaml"))


__all__ = [
    "REQUIRED_FIELDS",
    "OPTIONAL_FIELDS",
    "RUBRIC_PACKS_V1",  # re-export so pages can iterate canonical list
    "RubricValidationError",
    "validate_rubric_pack",
    "load_validated_rubric_pack",
    "load_validated_rubric_packs",
    "list_available_pack_keys",
    "list_all_pack_keys",
]
