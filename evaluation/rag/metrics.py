"""Pure metric functions for the RAG eval subsystem (plan §3.3).

Everything here is a deterministic pure function over plain inputs (ids, texts,
score lists) — no I/O, no app imports — so it's unit-testable in isolation and
reused across runners. The eval module owns its own tokenizer notion
(``content_coverage``) and deliberately does NOT bind to the production
splitter/embedding tokenizer (plan §3.3.1).
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

# ── content coverage (plan §3.3.1) ───────────────────────────────────────────
# The plan specifies LCS token overlap but explicitly allows normalized character
# 3-gram recall as a cheaper fallback, keeping the name ``content_coverage``.

_NGRAM_N = 3


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split())


def _char_ngrams(text: str, n: int = _NGRAM_N) -> set[str]:
    norm = _normalize(text)
    if not norm:
        return set()
    if len(norm) <= n:
        return {norm}
    return {norm[i:i + n] for i in range(len(norm) - n + 1)}


def content_coverage(expected_content: str, chunk_text: str) -> float:
    """Fraction of ``expected_content``'s character 3-grams present in
    ``chunk_text`` (normalized). 1.0 = fully covered, 0.0 = none / empty
    expectation. Symmetric to the §3.3.1 ``content_coverage`` contract."""
    expected = _char_ngrams(expected_content)
    if not expected:
        return 0.0
    actual = _char_ngrams(chunk_text)
    return len(expected & actual) / len(expected)


# ── retrieval relevance + ranking metrics (plan §3.3.1) ───────────────────────


def relevance_scores(
    ranked_chunks: Sequence[dict],
    expected_chunk_ids: Sequence[str],
    expected_content: str,
    min_content_coverage: float = 0.75,
) -> list[tuple[bool, float]]:
    """Per ranked chunk → (is_strong_hit, relevance_score). A strong hit
    (chunk_id in expected) scores 1.0; otherwise a content-coverage hit scores
    its coverage when it clears ``min_content_coverage``, else 0.0 (plan §3.3.1
    relevance + ndcg scoring). ``ranked_chunks`` are dicts with chunk_id/text."""
    expected = set(expected_chunk_ids)
    out: list[tuple[bool, float]] = []
    for chunk in ranked_chunks:
        if chunk.get("chunk_id") in expected:
            out.append((True, 1.0))
            continue
        cov = content_coverage(expected_content, chunk.get("text", ""))
        out.append((False, cov if cov >= min_content_coverage else 0.0))
    return out


def hit_at_k(scores: Sequence[tuple[bool, float]], k: int) -> bool:
    """Whether top-k holds at least one relevant chunk (score > 0)."""
    return any(s > 0 for _, s in scores[:k])


def recall_at_k(scores: Sequence[tuple[bool, float]], k: int, gold_count: int) -> float:
    """top-k relevant count / gold relevant count. 0.0 when gold_count is 0."""
    if gold_count <= 0:
        return 0.0
    return min(sum(1 for _, s in scores[:k] if s > 0), gold_count) / gold_count


def precision_at_k(scores: Sequence[tuple[bool, float]], k: int) -> float:
    """top-k relevant count / k. 0.0 for k <= 0."""
    if k <= 0:
        return 0.0
    return sum(1 for _, s in scores[:k] if s > 0) / k


def mrr_at_k(scores: Sequence[tuple[bool, float]], k: int) -> float:
    """Reciprocal rank of the first relevant chunk within top-k, else 0."""
    for idx, (_, s) in enumerate(scores[:k]):
        if s > 0:
            return 1.0 / (idx + 1)
    return 0.0


def ndcg_at_k(scores: Sequence[tuple[bool, float]], k: int) -> float:
    """Normalized DCG over the graded relevance scores (strong=1.0, coverage=its
    coverage). 0.0 when there's no ideal gain."""
    rels = [s for _, s in scores[:k]]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(rels))
    ideal = sorted((s for _, s in scores), reverse=True)[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0


def gold_chunk_best_rank(scores: Sequence[tuple[bool, float]]) -> Optional[int]:
    """1-based rank of the first STRONG (chunk_id) hit, or None if none — only
    strong hits count (a content-coverage hit isn't a known gold chunk)."""
    for idx, (strong, _) in enumerate(scores):
        if strong:
            return idx + 1
    return None


def rerank_survival_rate(
    rerank_input: Sequence[tuple[bool, float]],
    rerank_output: Sequence[tuple[bool, float]],
) -> Optional[float]:
    """Relevant chunks surviving rerank: output-relevant / input-relevant.
    None when no relevant chunk entered rerank (plan §3.3.1)."""
    in_rel = sum(1 for _, s in rerank_input if s > 0)
    if in_rel == 0:
        return None
    out_rel = sum(1 for _, s in rerank_output if s > 0)
    return out_rel / in_rel


# ── planner metrics (plan §3.3.2) ─────────────────────────────────────────────


def contains_all_terms(haystack: str, terms: Sequence[str]) -> bool:
    """Whether EVERY term appears (normalized substring) in the haystack. Empty
    terms → True (nothing required). Used for dense/sparse required-term checks;
    the caller builds the haystack from the top-level query + any sub-queries."""
    norm = _normalize(haystack)
    return all(_normalize(t) in norm for t in terms if _normalize(t))


# ── generation metrics (plan §3.3.3) ──────────────────────────────────────────


def answer_completeness(
    answer: str, reference_points: Sequence[str], min_point_coverage: float = 0.6,
) -> float:
    """Fraction of reference_answer_points the answer covers — a point counts
    when it's a normalized substring of the answer OR its content_coverage clears
    ``min_point_coverage`` (robust to minor wording). 0.0 when no points / empty
    answer; the per-sample value feeds reference_point_coverage_rate (its mean)."""
    points = [p for p in reference_points if _normalize(p)]
    if not points:
        return 0.0
    norm_answer = _normalize(answer)
    if not norm_answer:
        return 0.0
    covered = 0
    for point in points:
        if _normalize(point) in norm_answer or content_coverage(point, answer) >= min_point_coverage:
            covered += 1
    return covered / len(points)


# ── aggregation helpers ───────────────────────────────────────────────────────


def mean(values: Sequence[float]) -> Optional[float]:
    """Arithmetic mean, or None for an empty sequence (so 'no samples' is
    distinguishable from 0.0 in a report)."""
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def rate(flags: Sequence[bool]) -> Optional[float]:
    """Fraction of True flags, or None when empty."""
    flags = list(flags)
    return sum(1 for f in flags if f) / len(flags) if flags else None


def percentile(values: Sequence[float], p: float) -> Optional[float]:
    """The p-th percentile (0..100) via linear interpolation, or None when
    empty. Used for latency p50/p95 and chunk-token p50/p95 (plan §3.3.5/§3.3.6)."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    rank = (p / 100.0) * (len(vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(vals[lo])
    frac = rank - lo
    return float(vals[lo] * (1 - frac) + vals[hi] * frac)


__all__ = [
    "content_coverage", "relevance_scores",
    "hit_at_k", "recall_at_k", "precision_at_k", "mrr_at_k", "ndcg_at_k",
    "gold_chunk_best_rank", "rerank_survival_rate",
    "contains_all_terms", "answer_completeness",
    "mean", "rate", "percentile",
]
