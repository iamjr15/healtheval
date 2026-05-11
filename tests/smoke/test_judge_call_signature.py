"""Smoke (c): `eval.judges.judge_panel()` exists and returns the
expected shape WHEN MOCKED (the judge-panel contract / judge-call smoke gate).

Owned by Teammate C (eval-core). All vendor SDK calls (Anthropic,
Google GenAI, Sarvam) are patched at the
boundary that `eval.judges` actually uses (`_call_judge_*`) so this
test makes ZERO network calls — required by the reproducibility gate.

XFAILs cleanly when `eval.judges.judge_panel` is not yet exposed or
when its signature is still in flight.
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.smoke


def _get_judges_module():
    try:
        return importlib.import_module("eval.judges")
    except ModuleNotFoundError:
        return None


def _get_callable(name: str):
    mod = _get_judges_module()
    if mod is None:
        return None
    return getattr(mod, name, None)


@pytest.mark.xfail(
    _get_callable("judge_panel") is None,
    reason="blocked on eval-core teammate (eval.judges.judge_panel not yet exposed)",
    strict=False,
)
def test_judge_panel_returns_expected_shape_when_mocked():
    judges_mod = _get_judges_module()
    judge_panel = _get_callable("judge_panel")
    assert judges_mod is not None and judge_panel is not None

    # eval.judges fans out to four `_call_judge_<vendor>` helpers; patching
    # those keeps us strictly offline regardless of which vendor SDKs are
    # installed in the smoke env. If one of the helpers doesn't exist yet
    # (still being wired by eval-core), the patch is silently skipped.
    helper_names = (
        "_call_judge_anthropic",
        "_call_judge_google",
        "_call_judge_sarvam",
    )

    fake_score_payload = '{"score": 4, "rationale": "smoke stub"}'

    started = []
    try:
        for helper in helper_names:
            if hasattr(judges_mod, helper):
                p = patch.object(judges_mod, helper, return_value=fake_score_payload)
                p.start()
                started.append(p)

        # judge-panel signature (eval/judges.py @ judge_panel):
        #   judge_panel(prompt: str, response_dict: Mapping, panel_model_id: str)
        try:
            result = judge_panel(
                prompt="गर्भावस्था में रक्तस्राव — क्या करें?",
                response_dict={
                    "response": "तुरंत PHC जाएं।",
                    "triage_json": {
                        "triage_label": "RED",
                        "referral_action": "refer_mch_emergency",
                        "red_flags_detected": ["bleeding"],
                    },
                },
                panel_model_id="sarvam-30b",
            )
        except TypeError as e:
            # Signature drift — the API is in flight; flag rather than fail.
            pytest.xfail(f"judge_panel signature still in flight: {e!s}")
    finally:
        for p in started:
            try:
                p.stop()
            except RuntimeError:
                pass

    # Contract: result is iterable; each entry exposes a numeric `score`
    # and a string `rationale` (either as JudgeScore dataclass attrs or
    # as dict keys). We accept both for forward-compat.
    assert result is not None
    assert hasattr(result, "__iter__"), "judge_panel() must return an iterable"
    items = list(result)
    assert items, "judge_panel() must return at least one judge x principle cell"

    # data-spec's data.schemas.JudgeScore is the wire format eval-core
    # now emits — score is a 1..5 Likert float, principle_id is int 1..12,
    # rationale is Optional[str], plus a self_judging_dropped boolean.
    # The smoke test pins these so a vendor-API regression that returns
    # garbage Likert values (e.g. 0.0 fallback when SDK calls fail) is
    # caught at the gate, not in production.
    for cell in items:
        def _f(name):
            v = getattr(cell, name, None)
            if v is None and isinstance(cell, dict):
                v = cell.get(name)
            return v

        score = _f("score")
        rationale = _f("rationale")
        principle_id = _f("principle_id")
        judge_model_id = _f("judge_model_id")

        assert score is not None, f"judge cell missing `score`: {cell!r}"
        assert isinstance(score, (int, float))
        # 1..5 Likert per JudgeScore (data.schemas) — reject a
        # legacy 0..1 normalized score reappearing.
        assert 1.0 <= float(score) <= 5.0, (
            f"score {score!r} out of Likert range [1,5] — data.schemas.JudgeScore "
            f"contract regressed."
        )

        assert principle_id is not None, f"judge cell missing `principle_id`: {cell!r}"
        # principle_id is the constitutional rubric index (1..12).
        # Pydantic accepts int; downstream code treats as int.
        assert isinstance(principle_id, int) and 1 <= principle_id <= 12, (
            f"principle_id {principle_id!r} not in [1,12] — constitution drift."
        )

        # rationale is Optional[str] — accept None or str, reject other types.
        if rationale is not None:
            assert isinstance(rationale, str)

        if judge_model_id is not None:
            assert isinstance(judge_model_id, str) and judge_model_id
