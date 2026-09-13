"""Devanagari × Roman × Hinglish-mixed consistency battery (the script-variance check).

Source: Khullar et al. 2025 (arXiv:2512.10780) — Hindi-Roman vs
Hindi-Devanagari script gap up to 24 pts in health triage; 83% of real
Indian users use Romanized Hindi rather than Devanagari.

This module's contract:

    generate_script_variants(prompt: dict) -> dict
        returns {"devanagari": str, "roman": str, "hinglish_mixed": str}

In production each non-Devanagari variant is generated via an
LLM-assisted script-conversion call (Sarvam M-style transliteration or
Claude Sonnet 4.6); for build-time the LLM call is behind a mockable
interface so smoke tests run offline. The resulting prompts are run through
the full 4-model panel under the shared system prompt, and per-model
script variance is reported separately with effect sizes.

Manual review checkpoint
------------------------

LLM-converted variants are draft-only; the lead's bilingual review against the
WHO/MoHFW source paragraph is the quality gate before the variants
are accepted into ``data/prompts.yaml``. ``mark_review_required`` flags
each variant with a coarse confidence proxy so the reviewer can
prioritise.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Literal

logger = logging.getLogger(__name__)

ScriptName = Literal["devanagari", "roman", "hinglish_mixed"]
# Cross-language sentinel IDs (eval-core round-2 contract).
# Reference-set IDs ref-026..ref-030 are the de-facto sentinel band per
# eval-core's data/reference_set.yaml header. The cross-language battery
# should run these through Devanagari × Roman × Hinglish-mixed first so
# the cross-language results subsection has authoritative ground truth
# for every script before lower-priority prompts are evaluated. The
# ReferenceItem schema does not yet carry an explicit
# `script_variant_required` field (eval-core followed up with
# data-spec); until it does, this constant is the canonical contract.
CROSS_LANGUAGE_SENTINEL_IDS: tuple[str, ...] = (
    "ref-026", "ref-027", "ref-028", "ref-029", "ref-030",
)


def is_cross_language_sentinel(prompt: dict[str, Any]) -> bool:
    """``True`` if this prompt is in the script-variance check sentinel band.

    Recognises both ``id`` (canonical ``ReferenceItem`` field) and
    ``prompt_id`` (legacy alias).
    """
    pid = str(prompt.get("id") or prompt.get("prompt_id") or "")
    return pid in CROSS_LANGUAGE_SENTINEL_IDS


def partition_sentinels(
    prompts: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ``prompts`` into ``(sentinels, rest)`` preserving order.

    The panel runner in :mod:`scripts.run_panel_refset_eval` produces the
    saved panel responses; this module can be used for a separate sentinel
    bucket through :func:`expand_prompts_with_variants` first per
    eval-core's contract — ensures cross-language variance
    subsection has clean signal even if the rest of the run is
    interrupted.
    """
    sentinels = [p for p in prompts if is_cross_language_sentinel(p)]
    rest = [p for p in prompts if not is_cross_language_sentinel(p)]
    return sentinels, rest
# Mockable LLM hook — production wires this to Sarvam/Claude; tests stub it.
def _default_llm_transliterate(text: str, target_script: ScriptName) -> str:
    """Deterministic offline fallback used in smoke tests.

    Production replaces this via :func:`set_transliterator` with a real
    Sarvam M / Claude Sonnet 4.6 call. The fallback is good enough to
    exercise the dataclass + manual-review wiring without API access.
    """
    if target_script == "devanagari":
        return text
    if target_script == "roman":
        return _devanagari_to_roman_naive(text)
    if target_script == "hinglish_mixed":
        return _devanagari_to_hinglish_mixed_naive(text)
    raise ValueError(f"unknown target_script: {target_script}")


_TRANSLITERATOR: Callable[[str, ScriptName], str] = _default_llm_transliterate


def set_transliterator(fn: Callable[[str, ScriptName], str]) -> None:
    """Inject a real LLM-backed transliterator (Sarvam M / Claude).

    Call this once at process start in production; tests leave the
    default offline fallback in place.
    """
    global _TRANSLITERATOR
    _TRANSLITERATOR = fn


# Naive offline transliteration (a placeholder — NOT linguistic-grade).
# Per the script-variance check the real production path goes through Sarvam M; this exists
# so build-time smoke tests run without network.
_DEVANAGARI_TO_ITRANS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "T", "ठ": "Th", "ड": "D", "ढ": "Dh", "ण": "N",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "Sh", "स": "s", "ह": "h",
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ं": "n", "ः": "h",
    "्": "", "ँ": "n", "।": ".", "॥": ".",
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}


def _devanagari_to_roman_naive(text: str) -> str:
    """Quick char-by-char romanisation; production swaps in Sarvam M."""
    out: list[str] = []
    for ch in text:
        out.append(_DEVANAGARI_TO_ITRANS.get(ch, ch))
    # Collapse whitespace + lowercase ITRANS-ish capitals.
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _devanagari_to_hinglish_mixed_naive(text: str) -> str:
    """Mix-script approximation: keep clinical-y English keywords, romanise
    the rest. Production swaps in an LLM call that preserves the
    code-mixed register typical of urban Indian users (per Khullar 2025).
    """
    roman = _devanagari_to_roman_naive(text)
    # Insert a few canonical English clinical anchors so the variant
    # actually reads as code-mixed rather than fully romanised.
    substitutions = [
        (r"\bsvaasthya\b", "health"),
        (r"\bdard\b", "pain"),
        (r"\bbukhaar\b", "fever"),
        (r"\bkhoon\b", "blood"),
        (r"\bbachcha\b", "baby"),
        (r"\bdavaa\b", "medicine"),
    ]
    for pat, repl in substitutions:
        roman = re.sub(pat, repl, roman, flags=re.IGNORECASE)
    return roman
def generate_script_variants(prompt: dict[str, Any]) -> dict[str, str]:
    """Return ``{"devanagari", "roman", "hinglish_mixed"}`` for one prompt.

    Parameters
    ----------
    prompt
        Either ``{"text": str, ...}`` or ``{"prompt": str, ...}`` from
        ``data/prompts.yaml``. Devanagari is treated as canonical.

    Returns
    -------
    dict[str, str]
        Three script variants; the Devanagari variant is the input
        text verbatim (canonical); the other two are produced by the
        active transliterator (production: Sarvam M / Claude; offline:
        :func:`_default_llm_transliterate`).
    """
    # Accept any of the canonical text fields used across the schemas:
    #   data.schemas.Prompt        → hindi_text / devanagari_text
    #   data.schemas.ReferenceItem → hindi_text / devanagari_text
    #   legacy Promptfoo / CeRAI   → text / prompt
    canonical = str(
        prompt.get("hindi_text")
        or prompt.get("devanagari_text")
        or prompt.get("text")
        or prompt.get("prompt")
        or ""
    ).strip()
    if not canonical:
        raise ValueError("generate_script_variants: prompt has no text")
    return {
        "devanagari": canonical,
        "roman": _TRANSLITERATOR(canonical, "roman"),
        "hinglish_mixed": _TRANSLITERATOR(canonical, "hinglish_mixed"),
    }


def expand_prompts_with_variants(
    prompts: list[dict[str, Any]],
    *,
    sentinels_first: bool = True,
) -> list[dict[str, Any]]:
    """Fan each prompt out into 3 rows (one per script variant).

    Each output row carries ``script_variant`` metadata so downstream
    per-model variance reporting (the cross-language results section) can group cleanly. Non-text
    fields are preserved across all 3 variants.

    Output shape note (per data-spec contract): the rows returned here
    are PLAIN DICTS, NOT :class:`data.schemas.Prompt` instances. The
    Prompt schema's ``devanagari_text == hindi_text`` model_validator
    forbids text mutation; the runtime variants live as a separate
    in-memory artefact consumed by Promptfoo / Inspect scorer checks directly.
    Callers that need to validate a row should round-trip only the
    devanagari variant through :class:`data.schemas.Prompt`.
    """
    if sentinels_first:
        sentinels, rest = partition_sentinels(prompts)
        ordered = sentinels + rest
    else:
        ordered = list(prompts)

    out: list[dict[str, Any]] = []
    for p in ordered:
        variants = generate_script_variants(p)
        canonical = variants["devanagari"]
        for script, text in variants.items():
            row = dict(p)
            # Mirror text into both common field names so Promptfoo's
            # YAML-driven test rows pick it up regardless of whether
            # the consumer reads `hindi_text` (data-spec canonical),
            # `devanagari_text`, `text`, or `prompt`.
            row["text"] = text
            row["prompt"] = text
            row["hindi_text"] = text
            row["devanagari_text"] = text  # variant-local; NOT validated through Prompt
            row["script_variant"] = script
            row["canonical_devanagari"] = canonical
            row["is_cross_language_sentinel"] = is_cross_language_sentinel(p)
            out.append(row)
    return out


def mark_review_required(variant_text: str, original_devanagari: str) -> bool:
    """Coarse heuristic for "needs human review before being trusted".

    Real production uses back-translation BLEU > 50 (per the script-variance check quality
    gate) — that's a Phase-2 artefact. This stand-in flags any variant
    with mismatched length ratio (LLM truncation) or empty output.
    """
    if not variant_text.strip():
        return True
    ratio = len(variant_text) / max(1, len(original_devanagari))
    return not (0.4 <= ratio <= 2.5)
