"""Pure-function retrieval quality metrics.

All functions are stateless and operate on plain Python types.  They can be
unit-tested without touching any external service.
"""

from __future__ import annotations

import math
import re


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Collapse whitespace and lowercase."""
    return " ".join(text.replace("\n", " ").split()).strip().lower()


def tokenize(text: str) -> list[str]:
    """Extract meaningful tokens (English words and Chinese bigrams+)."""
    return re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalize(text))


# ---------------------------------------------------------------------------
# Overlap / relevance helpers
# ---------------------------------------------------------------------------

def overlap_score(query: str, text: str) -> float:
    """Token-level overlap between *query* and *text*.

    Returns the fraction of query tokens found in text.
    """
    q_tokens = set(tokenize(query))
    if not q_tokens:
        return 0.0
    t_lower = text.lower()
    return sum(1 for t in q_tokens if t in t_lower) / len(q_tokens)


def chunk_relevance(
    reference_text: str,
    retrieved_text: str,
    threshold: float = 0.15,
) -> bool:
    """Return whether *retrieved_text* is relevant to *reference_text*."""
    return overlap_score(reference_text, retrieved_text) >= threshold


# ---------------------------------------------------------------------------
# Ranking metrics
# ---------------------------------------------------------------------------

def hit_at_k(
    relevant_flags: list[bool],
    k: int | None = None,
) -> int:
    """Binary hit: 1 if any item in top-k is relevant, else 0."""
    flags = relevant_flags[:k] if k else relevant_flags
    return 1 if any(flags) else 0


def precision_at_k(
    relevant_flags: list[bool],
    k: int | None = None,
) -> float:
    """Precision@K — fraction of top-k that are relevant."""
    flags = relevant_flags[:k] if k else relevant_flags
    if not flags:
        return 0.0
    return sum(flags) / len(flags)


def recall_at_k(
    relevant_flags: list[bool],
    total_relevant: int = 1,
    k: int | None = None,
) -> float:
    """Recall@K — fraction of total relevant items found in top-k."""
    flags = relevant_flags[:k] if k else relevant_flags
    if total_relevant <= 0:
        return 0.0
    return min(sum(flags) / total_relevant, 1.0)


def reciprocal_rank(relevant_flags: list[bool]) -> float:
    """Mean Reciprocal Rank for a single query."""
    for rank, flag in enumerate(relevant_flags, start=1):
        if flag:
            return 1.0 / rank
    return 0.0


def dcg(scores: list[float]) -> float:
    """Discounted Cumulative Gain."""
    value = 0.0
    for rank, score in enumerate(scores, start=1):
        gain = max(score, 0.0)
        if gain == 0.0:
            continue
        value += gain / math.log2(rank + 1)
    return value


def ndcg_at_k(
    scores: list[float],
    k: int | None = None,
) -> float:
    """Normalised DCG@K."""
    truncated = scores[:k] if k else scores
    if not truncated:
        return 0.0
    ideal = sorted(truncated, reverse=True)
    ideal_dcg = dcg(ideal)
    if ideal_dcg == 0.0:
        return 0.0
    return dcg(truncated) / ideal_dcg


# ---------------------------------------------------------------------------
# Latency helpers
# ---------------------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    """Linear interpolation percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * p
    lower = int(idx)
    upper = min(lower + 1, len(ordered) - 1)
    weight = idx - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


# ---------------------------------------------------------------------------
# Aggregate helpers
# ---------------------------------------------------------------------------

def aggregate_scores(values: list[float]) -> dict[str, float]:
    """Return mean, min, max, p50, p95 for a list of scores."""
    if not values:
        return {"mean": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p95": 0.0}
    import statistics

    return {
        "mean": round(statistics.mean(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "p50": round(percentile(values, 0.5), 4),
        "p95": round(percentile(values, 0.95), 4),
    }
