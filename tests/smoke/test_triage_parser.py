"""Smoke tests for the schema-first triage parser."""

from __future__ import annotations

from eval.judges import parse_triage_response


def test_parse_triage_response_reads_fenced_json_after_hindi_prose() -> None:
    raw = """
    कृपया नियमित स्वास्थ्य देखभाल जारी रखें।

    ```json
    {
      "triage_label": "GREEN",
      "referral_action": "continue",
      "red_flags_detected": [],
      "triage_reason": "कोई खतरे का संकेत नहीं।"
    }
    ```
    """

    assert parse_triage_response(raw) == {
        "triage_label": "GREEN",
        "referral_action": "continue",
        "red_flags_detected": [],
        "triage_reason": "कोई खतरे का संकेत नहीं।",
    }


def test_parse_triage_response_repairs_missing_final_brace_only() -> None:
    raw = """
    उत्तर संक्षिप्त है।

    ```json
    {
      "triage_label": "AMBER",
      "referral_action": "refer_phc",
      "red_flags_detected": ["लगातार उल्टी"],
      "triage_reason": "लगातार उल्टी में PHC समीक्षा चाहिए।"
    """

    assert parse_triage_response(raw) == {
        "triage_label": "AMBER",
        "referral_action": "refer_phc",
        "red_flags_detected": ["लगातार उल्टी"],
        "triage_reason": "लगातार उल्टी में PHC समीक्षा चाहिए।",
    }


def test_parse_triage_response_accepts_structured_envelope() -> None:
    raw = """
    {
      "response": "हिंदी उत्तर",
      "triage_json": {
        "triage_label": "RED",
        "referral_action": "refer_emergency",
        "red_flags_detected": ["भारी रक्तस्राव"],
        "triage_reason": "भारी रक्तस्राव तत्काल आपातकाल है।"
      }
    }
    """

    assert parse_triage_response(raw) == {
        "triage_label": "RED",
        "referral_action": "refer_emergency",
        "red_flags_detected": ["भारी रक्तस्राव"],
        "triage_reason": "भारी रक्तस्राव तत्काल आपातकाल है।",
    }


def test_parse_triage_response_keeps_legacy_blocks_without_reason() -> None:
    raw = """
    {
      "triage_label": "GREEN",
      "referral_action": "continue",
      "red_flags_detected": []
    }
    """

    assert parse_triage_response(raw) == {
        "triage_label": "GREEN",
        "referral_action": "continue",
        "red_flags_detected": [],
    }


def test_parse_triage_response_does_not_invent_missing_json() -> None:
    raw = "गर्भावस्था में पानी पीना ज़रूरी है, लेकिन कोई JSON ब्लॉक नहीं है।"

    assert parse_triage_response(raw) is None
