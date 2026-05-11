"""Data-contract tests over the live evidence artefacts.

These run against the actual ``data/`` + ``results/`` files in the repo —
they're a fast pre-flight check that the schemas the dashboard pages
assume still match what the eval pipeline produced.  Per the shipped workbench design the data-contract test set:

- Every field the loaders ``cast`` to is asserted here.
- The "no hard-coded numbers" rule is enforced by ``test_no_hardcoded_likert_in_streamlit_source``.
- Rubric-pack contract: union of ``constitution_principle_ids`` across the
  4 packs == all 12 IDs from ``data/constitution.yaml``.
- Seed calibration pack contract: ≥ 5 examples, all referenced ref-IDs
  exist in ``data/reference_set.yaml``, every example has a real prompt
  string.
"""
from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

import pytest
import yaml

from streamlit_app.canonical_selector import select_complete_methodology_artifact
from streamlit_app.config import (
    EVALUATOR_TRIAGE_AMBER_THRESHOLD,
    EVALUATOR_TRIAGE_GREEN_THRESHOLD,
    PATH_CALIBRATION_EXAMPLES,
    PATH_CERAI,
    PATH_CONSTITUTION,
    PATH_INSPECT,
    PATH_REFERENCE_SET,
    PATH_TOOL_META,
    PACKAGE_DIR,
    RUBRICS_DIR,
    SAFETY_PRINCIPLE_IDS,
)
from streamlit_app.data_loaders import (
    load_all_rubric_packs,
    load_judge_calibration_examples,
)
from streamlit_app.evidence_validator import EvidenceMissing, validate_evidence
# Methodology artefact (selected via canonical_selector).
def test_methodology_artefact_is_complete_and_well_shaped() -> None:
    selected = select_complete_methodology_artifact()
    assert selected is not None, "no complete methodology artefact found"
    with selected.open() as f:
        data = json.load(f)

    assert data["n_prompts_done"] == data["n_prompts_total"], (
        "selector returned an in-flight artefact"
    )
    assert len(data["rows"]) == data["n_prompts_total"]
    assert isinstance(data.get("jury"), list) and len(data["jury"]) >= 2
    for row in data["rows"]:
        assert "prompt_id" in row
        assert "judge_scores" in row
        # Current final method scores the safety principle subset, so
        # self-judged panel targets can have 2 judges × 5 principles = 10 cells.
        assert len(row["judge_scores"]) >= 10
        for cell in row["judge_scores"]:
            assert {"judge_model_id", "principle_id", "score"} <= set(cell.keys())
            assert 1.0 <= cell["score"] <= 5.0


def test_dashboard_method_defaults_match_final_artefact() -> None:
    """Dashboard controls must default to the shipped final method."""
    selected = select_complete_methodology_artifact()
    assert selected is not None
    with selected.open() as f:
        data = json.load(f)
    calibration = data["calibration"]

    assert list(SAFETY_PRINCIPLE_IDS) == calibration["principle_ids"]
    assert EVALUATOR_TRIAGE_GREEN_THRESHOLD == pytest.approx(
        calibration["green_threshold"]
    )
    assert EVALUATOR_TRIAGE_AMBER_THRESHOLD == pytest.approx(
        calibration["amber_threshold"]
    )
# tool_meta_evaluation.json.
def test_tool_meta_final_method_shape() -> None:
    with PATH_TOOL_META.open() as f:
        meta = json.load(f)
    rows = meta.get("table_final_method")
    assert rows, "tool meta must include final-method rows"
    for row in rows:
        assert "evaluator" in row
        for key in ("sensitivity", "specificity"):
            cell = row[key]
            assert "rate" in cell
            if "k" in cell or "n" in cell:
                assert "k" in cell
                assert "n" in cell

    natives = meta.get("table_panel_models") or meta["table_native"]
    assert len(natives) >= 3
# CeRAI + Inspect evaluator outputs.
@pytest.mark.parametrize("path", [PATH_CERAI, PATH_INSPECT])
def test_evaluator_outputs_have_all_30_refs(path: Path) -> None:
    with path.open() as f:
        data = json.load(f)
    outputs = data["evaluator_outputs"]
    assert isinstance(outputs, dict)
    assert len(outputs) == 30
    for prompt_id, payload in outputs.items():
        assert prompt_id.startswith("ref-")
        assert isinstance(payload, dict)
# Reference set + constitution.
def test_reference_set_has_30_items_with_required_fields() -> None:
    with PATH_REFERENCE_SET.open() as f:
        ref = yaml.safe_load(f)
    items = ref["items"]
    assert len(items) == 30
    required = {
        "id",
        "hindi_text",
        "expected_safety_action",
        "expected_triage_label",
        "factual_checklist",
        "refusal_expected",
        "citation_expected",
        "red_flag_match_required",
        "source_url",
        "source_paragraph",
    }
    for item in items:
        missing = required - set(item.keys())
        assert not missing, f"{item.get('id')} missing fields: {missing}"


def test_constitution_has_12_principles() -> None:
    with PATH_CONSTITUTION.open() as f:
        const = yaml.safe_load(f)
    principles = const["principles"]
    assert len(principles) == 12
    ids = {p["id"] for p in principles}
    assert ids == set(range(1, 13))
# Rubric packs (Phase 0 BLOCKER).
def test_all_four_rubric_packs_load_and_declare_correct_metric() -> None:
    packs = load_all_rubric_packs(version="v1")
    assert set(packs.keys()) == {
        "mnh_safety",
        "factuality",
        "limitation_awareness",
        "triage_schema",
    }
    for metric, pack in packs.items():
        assert pack["metric"] == metric
        assert pack["version"].startswith("v")
        assert isinstance(pack["scoring_scale"], dict)
        assert isinstance(pack["score_examples"], list)
        assert len(pack["score_examples"]) >= 2
        assert isinstance(pack["failure_categories"], list)
        # The 8 canonical failure categories must all appear in every pack
        # (each pack may add metric-specific extras on top).
        canon = {
            "missed_red_flag",
            "unsafe_reassurance",
            "wrong_referral_level",
            "unsupported_medication_advice",
            "incomplete_answer",
            "hallucinated_policy",
            "schema_parse_failure",
            "over_refusal",
        }
        assert canon <= set(pack["failure_categories"]), (
            f"{metric}_v1.yaml is missing canonical failure_categories"
        )


def test_rubric_packs_cover_all_12_constitution_principles() -> None:
    """Union of constitution_principle_ids across the 4 packs == {1..12}."""
    packs = load_all_rubric_packs(version="v1")
    union: set[int] = set()
    for pack in packs.values():
        ids = pack.get("constitution_principle_ids", [])
        # Also assert intra-pack disjointness against running union.
        assert union.isdisjoint(set(ids)), (
            f"principle ID overlap between rubric packs: {set(ids) & union}"
        )
        union.update(ids)
    assert union == set(range(1, 13)), (
        f"rubric packs cover {sorted(union)}, expected {{1..12}}"
    )
# Seed judge_calibration_examples.yaml.
def test_seed_calibration_pack_loads_with_at_least_five_examples() -> None:
    pack = load_judge_calibration_examples()
    examples = pack["examples"]
    assert len(examples) >= 5

    # Required failure-mode coverage per the shipped workbench design the calibration-example coverage requirement Phase 0.
    failure_categories_seen = {ex.get("failure_category") for ex in examples}
    metrics_seen = {ex["metric"] for ex in examples}

    # Anchors required: missed_red_flag, schema_parse_failure, over_refusal,
    # wrong_referral_level (all negatives) and at least one positive
    # (failure_category=None on a 5-anchor positive).
    required_negatives = {
        "missed_red_flag",
        "schema_parse_failure",
        "over_refusal",
        "wrong_referral_level",
    }
    assert required_negatives <= failure_categories_seen, (
        f"missing required negative anchors: {required_negatives - failure_categories_seen}"
    )
    assert None in failure_categories_seen, (
        "seed pack must contain at least one positive (failure_category=null) anchor"
    )

    # The pack should cover all four rubric metrics (or at least most).
    assert metrics_seen & {
        "mnh_safety",
        "factuality",
        "limitation_awareness",
        "triage_schema",
    }


def test_seed_calibration_examples_reference_real_ref_ids() -> None:
    pack = load_judge_calibration_examples()
    with PATH_REFERENCE_SET.open() as f:
        ref_set = yaml.safe_load(f)
    real_ids = {item["id"] for item in ref_set["items"]}

    for ex in pack["examples"]:
        ref_id = ex.get("ref_id")
        assert ref_id in real_ids, f"calibration example {ex['id']} cites unknown ref-id {ref_id!r}"
        assert isinstance(ex.get("prompt"), str) and ex["prompt"].strip(), (
            f"{ex['id']} missing prompt text"
        )
        assert isinstance(ex.get("actual_answer"), str) and ex["actual_answer"].strip(), (
            f"{ex['id']} missing actual_answer text"
        )
        assert isinstance(ex.get("human_score"), (int, float))
        assert 1.0 <= float(ex["human_score"]) <= 5.0


def test_seed_calibration_prompts_match_reference_set_text() -> None:
    """For ref-IDs that the seed cites, the prompt should match the n=30 ref-set."""
    pack = load_judge_calibration_examples()
    with PATH_REFERENCE_SET.open() as f:
        ref_set = yaml.safe_load(f)
    by_id = {item["id"]: item for item in ref_set["items"]}

    for ex in pack["examples"]:
        ref_id = ex.get("ref_id")
        if ref_id not in by_id:
            continue
        # The seed prompt should literally match the ref-set's hindi_text
        # (modulo trailing whitespace).  This is the contract that proves
        # the seed is grounded in real evidence and not fabricated.
        ref_prompt = by_id[ref_id]["hindi_text"].strip()
        assert ref_prompt == ex["prompt"].strip(), (
            f"{ex['id']} prompt does not match {ref_id} hindi_text in reference_set"
        )
# Evidence validator end-to-end.
def test_evidence_validator_passes_against_current_evidence() -> None:
    selected = validate_evidence()
    assert selected is not None
    assert selected.exists()


def test_evidence_validator_raises_clean_message_when_calibration_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If we point validate_evidence's calibration path at a missing file it must raise EvidenceMissing."""
    bogus = tmp_path / "missing.yaml"
    monkeypatch.setattr(
        "streamlit_app.evidence_validator.PATH_CALIBRATION_EXAMPLES", bogus
    )
    with pytest.raises(EvidenceMissing) as excinfo:
        validate_evidence()
    assert "missing.yaml" in str(excinfo.value) or "missing" in str(excinfo.value).lower()
# Hard-coded numbers / Likert-range literals scan over streamlit_app/.
# Files that are ALLOWED to contain decimal-range literals.  The scan only
# looks at NUMBER tokens (not strings or comments), but a few modules
# legitimately need real numeric defaults: config.py declares rate limits /
# budgets, schemas.py is type-only, and the package __init__.py is import-only.
_HARDCODED_LITERAL_ALLOWLIST = {
    "config.py",
    "schemas.py",
}
_LIKERT_NUMBER_RE = re.compile(r"^[1-5]\.[0-9]+$")


def _python_files_under_streamlit_app() -> list[Path]:
    files: list[Path] = []
    for path in PACKAGE_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if path.name in _HARDCODED_LITERAL_ALLOWLIST:
            continue
        files.append(path)
    return files


def test_no_hardcoded_likert_in_streamlit_source() -> None:
    """Pages must not embed 1.0..5.0 numeric literals.

    The scan tokenises each ``streamlit_app/**.py`` file and only inspects
    NUMBER tokens — comments, string literals, and docstrings cannot trip
    this test.  Catches lines like ``if score >= 4.0:`` that should
    instead read ``rubric_pack["pass_fail_threshold"]`` from the loaded
    rubric YAML.  ``config.py`` + ``schemas.py`` are allow-listed because
    they're the legitimate places for numeric defaults to live.
    """
    offenders: list[tuple[Path, int, str]] = []
    for path in _python_files_under_streamlit_app():
        try:
            source = path.read_text()
        except OSError:
            continue
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except tokenize.TokenizeError:
            continue
        for tok in tokens:
            if tok.type != tokenize.NUMBER:
                continue
            if not _LIKERT_NUMBER_RE.match(tok.string):
                continue
            offenders.append(
                (
                    path.relative_to(PACKAGE_DIR.parent),
                    tok.start[0],
                    tok.line.rstrip(),
                )
            )
    assert not offenders, (
        "Hard-coded Likert-range literals (1.0..5.x) found in streamlit_app/ source — "
        "read these from rubric / methodology artefacts instead:\n"
        + "\n".join(f"  {p}:{ln}  {ctx}" for p, ln, ctx in offenders)
    )
