"""TF-IDF retrieval over ``data/judge_calibration_examples.yaml``.

When the v3 judge prompt is built, it
retrieves the top-``k`` calibration examples whose ``prompt`` is
TF-IDF-closest to the panel prompt being judged, filtered to the same
``metric`` as the rubric pack the judge is currently scoring.  The
retrieved IDs are logged in ``judge_trace.jsonl`` so a later audit can
reconstruct exactly which examples anchored each judge call.

Cold-start handling (per the judge-memory cold-start caveat): the seed
pack ships with ~6 examples — TF-IDF cosine distance can legitimately
be 0 for prompts that share no vocabulary with any seed.  Rather than
returning an empty list (which would silently degrade the judge prompt
to "no anchors"), we fall back to the first ``k`` seed examples for the
same metric.  The retriever still logs the cosine score so reviewers
can audit how often the cold-start branch fires.

Implementation choice: scikit-learn's ``TfidfVectorizer`` + cosine
similarity.  Works fine for the n≈6 → n≈100 range we expect over the
submission window; if the calibration pool grows past ~10⁴ examples
we'd want to swap in a faiss / pgvector index, but that's out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import yaml

# Lazy sklearn import: keeps test collection fast in the no-sklearn dev path.
try:  # pragma: no cover — exercised when sklearn is installed.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    _HAS_SKLEARN = True
except ImportError:  # pragma: no cover — degraded fallback below.
    TfidfVectorizer = None  # type: ignore[assignment]
    cosine_similarity = None  # type: ignore[assignment]
    _HAS_SKLEARN = False


_DEFAULT_PACK_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "judge_calibration_examples.yaml"
)


@dataclass(frozen=True)
class RetrievalHit:
    """One retrieval result.

    ``score`` is the cosine similarity in [0, 1]; ``cold_start`` is True
    when this hit came from the seed-fallback branch (no TF-IDF overlap)
    rather than from a real similarity match.  Logging both lets the
    Page 7 trace view distinguish "judge anchored on a relevant
    example" from "judge got the cold-start filler".
    """

    example: dict[str, Any]
    score: float
    cold_start: bool


def _load_pack(path: Path | None = None) -> list[dict[str, Any]]:
    """Read the YAML pack and return the ``examples`` list.

    Returns ``[]`` when the file is missing or has no ``examples`` key —
    the retriever then has nothing to anchor on, which the caller
    surfaces as an empty result rather than as an exception.
    """
    target = path if path is not None else _DEFAULT_PACK_PATH
    if not target.exists():
        return []
    with target.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, Mapping):
        return []
    examples = data.get("examples", [])
    if not isinstance(examples, list):
        return []
    return [dict(ex) for ex in examples if isinstance(ex, Mapping)]


def _filter_by_metric(
    examples: Iterable[Mapping[str, Any]],
    metric: Optional[str],
    rubric_version: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Restrict to one rubric metric (and optionally rubric version).

    Returns dicts for stable downstream serialisation.  Filtering on
    ``metric`` is the primary signal (the judge prompt is built around
    one rubric pack at a time); ``rubric_version`` lets a future v2
    pack avoid mixing with v1 anchors when both exist on disk.
    """
    out: list[dict[str, Any]] = []
    for ex in examples:
        if metric is not None and ex.get("metric") != metric:
            continue
        if rubric_version is not None and ex.get("rubric_version") != rubric_version:
            continue
        out.append(dict(ex))
    return out


def retrieve_examples(
    prompt: str,
    metric: str,
    *,
    k: int = 3,
    rubric_version: Optional[str] = None,
    pack_path: Path | None = None,
    examples: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[RetrievalHit]:
    """Top-``k`` TF-IDF-similar calibration examples for ``(prompt, metric)``.

    Parameters
    ----------
    prompt:
        The panel prompt being judged.  Used as the query string.
    metric:
        Rubric pack metric name (``mnh_safety``, ``factuality``,
        ``limitation_awareness``, ``triage_schema``).  Required —
        passing the wrong metric here would surface anchors with the
        wrong rubric, defeating the purpose of retrieval.
    k:
        Maximum number of hits to return.  ``min(k, n_pool)`` is
        always returned.
    rubric_version:
        Optional rubric-version filter (e.g. ``"v1"``).  Default
        ``None`` accepts any version — useful while only v1 rubric
        packs exist.
    pack_path:
        Override the default ``data/judge_calibration_examples.yaml``
        location (used by tests).
    examples:
        Override the loaded pack entirely (used by tests).  When
        provided, ``pack_path`` is ignored.

    Returns
    -------
    list[RetrievalHit]
        Sorted descending by ``score``.  ``cold_start=True`` flags
        entries that came from the seed-fallback path.

    Cold-start contract:
    Returns at least ``min(k, n_metric_pool)`` hits whenever the metric
    pool is non-empty, even if the TF-IDF cosine score is 0.  Callers
    can trust that a non-empty pool always yields something to render
    in the judge prompt — they need not branch on "no anchors found".
    """
    pool = (
        _filter_by_metric(examples, metric, rubric_version)
        if examples is not None
        else _filter_by_metric(_load_pack(pack_path), metric, rubric_version)
    )
    if not pool:
        return []

    if k <= 0:
        return []

    # Build the TF-IDF doc set: each example's prompt + actual_answer
    # (concatenated) is the document; the query is the panel prompt.
    docs = [
        f"{ex.get('prompt', '')}\n{ex.get('actual_answer', '')}"
        for ex in pool
    ]

    if not _HAS_SKLEARN:
        # Degraded path — return the first k seed entries with cold_start=True.
        return [
            RetrievalHit(example=dict(ex), score=0.0, cold_start=True)
            for ex in pool[:k]
        ]

    vectorizer = TfidfVectorizer(
        analyzer="word",
        token_pattern=r"\S+",  # whitespace tokens — Devanagari / Hinglish friendly
        lowercase=True,
        norm="l2",
    )
    try:
        matrix = vectorizer.fit_transform(docs + [prompt])
    except ValueError:
        # Empty vocabulary — every doc was empty after tokenisation.
        # Cold-start fallback path.
        return [
            RetrievalHit(example=dict(ex), score=0.0, cold_start=True)
            for ex in pool[:k]
        ]
    pool_vecs = matrix[:-1]
    query_vec = matrix[-1]

    sims = cosine_similarity(query_vec, pool_vecs).flatten()
    # Argsort descending; numpy not strictly required (we have it via sklearn).
    ranked = sorted(
        zip(pool, sims), key=lambda pair: float(pair[1]), reverse=True
    )

    hits: list[RetrievalHit] = []
    for ex, score in ranked[:k]:
        score_f = float(score)
        hits.append(
            RetrievalHit(
                example=dict(ex),
                score=score_f,
                cold_start=score_f == 0.0,
            )
        )
    # Cold-start backfill: if the first k hits all have score 0, mark them
    # cold_start; we still return them so the judge prompt has anchors.
    return hits


def render_examples_block(hits: Sequence[RetrievalHit]) -> str:
    """Render retrieved hits as a string suitable for the judge prompt.

    Used by :func:`eval.judges._build_judge_prompt` when v3 retrieval is
    enabled.  Empty hit list renders the empty string — the caller
    decides whether to include the "Retrieved calibration anchors"
    header at all.
    """
    if not hits:
        return ""
    chunks: list[str] = []
    for i, hit in enumerate(hits, 1):
        ex = hit.example
        marker = " (cold-start fallback)" if hit.cold_start else ""
        chunks.append(
            f"## Anchor {i} — id={ex.get('id', '?')} score≈{hit.score:.3f}{marker}\n"
            f"Prompt: {ex.get('prompt', '').strip()}\n"
            f"Actual answer: {ex.get('actual_answer', '').strip()}\n"
            f"Human score: {ex.get('human_score', '?')}\n"
            f"Reason: {(ex.get('human_reason') or '').strip()}"
        )
    return "\n\n".join(chunks)


__all__ = ["RetrievalHit", "retrieve_examples", "render_examples_block"]
