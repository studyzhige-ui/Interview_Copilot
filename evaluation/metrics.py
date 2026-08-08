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
    """Extract English terms plus overlapping Chinese bigrams."""
    value = normalize(text)
    tokens = re.findall(r"[a-z0-9]+", value)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", value):
        if len(sequence) == 1:
            tokens.append(sequence)
        else:
            tokens.extend(
                sequence[index : index + 2] for index in range(len(sequence) - 1)
            )
    return tokens


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


def term_coverage(terms: list[str], text: str) -> float:
    """Fraction of curator-provided, language-independent terms in ``text``."""
    if not terms:
        return 0.0
    value = normalize(text)
    compact_value = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", value)
    matched = 0
    for term in terms:
        normalized_term = normalize(term)
        compact_term = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", normalized_term)
        matched += normalized_term in value or (
            bool(compact_term) and compact_term in compact_value
        )
    return matched / len(terms)


def chunk_matches_terms(
    terms: list[str],
    text: str,
    *,
    threshold: float = 0.75,
) -> bool:
    return term_coverage(terms, text) >= threshold


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
    denominator = k if k is not None else len(flags)
    if denominator <= 0:
        return 0.0
    return sum(flags) / denominator


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


def average_precision_at_k(
    relevant_flags: list[bool],
    k: int,
    *,
    total_relevant: int,
) -> float:
    """Standard AP@K, including relevant items missed from the retrieved list."""
    flags = relevant_flags[:k]
    denominator = min(total_relevant, k)
    if denominator <= 0:
        return 0.0
    precision_sum = 0.0
    seen = 0
    for rank, flag in enumerate(flags, start=1):
        if flag:
            seen += 1
            precision_sum += seen / rank
    return precision_sum / denominator


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
    *,
    total_relevant: int | None = None,
) -> float:
    """Normalised DCG@K."""
    truncated = scores[:k] if k else scores
    if not truncated:
        return 0.0
    if total_relevant is None:
        ideal = sorted(truncated, reverse=True)
    else:
        limit = k or len(truncated)
        ideal = [1.0] * min(total_relevant, limit)
        ideal.extend([0.0] * (limit - len(ideal)))
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


# ---------------------------------------------------------------------------
# Grounded-answer helpers
# ---------------------------------------------------------------------------


_CITATION_RE = re.compile(r"\[K(\d+)]", re.IGNORECASE)
_INSUFFICIENT_MARKERS = (
    "资料不足",
    "信息不足",
    "无法确定",
    "无法根据",
    "未包含",
    "cannot be answered",
    "cannot determine",
    "not contain",
    "insufficient information",
    "not provided",
)


def citation_validity(answer: str, context_count: int) -> float | None:
    """Share of emitted ``[K#]`` references that identify a supplied chunk."""
    citations = [int(value) for value in _CITATION_RE.findall(answer)]
    if not citations:
        return None
    return sum(1 <= value <= context_count for value in citations) / len(citations)


def citation_coverage(answer: str) -> float | None:
    """Share of substantive answer sentences carrying at least one citation."""
    sentences = [
        value.strip()
        for value in re.split(r"(?<=[。！？!?])\s*|(?<=\.)\s+|\n+", answer)
        if len(re.sub(r"\s+", "", value)) >= 8
        and not has_insufficient_disclaimer(value)
    ]
    if not sentences:
        return None
    return sum(bool(_CITATION_RE.search(value)) for value in sentences) / len(sentences)


def has_insufficient_disclaimer(answer: str) -> bool:
    """Whether the response explicitly acknowledges missing evidence."""
    value = normalize(answer)
    return any(marker in value for marker in _INSUFFICIENT_MARKERS)


def is_insufficient_answer(answer: str) -> bool:
    """Whether missing evidence is the response's leading answer, not a hedge."""
    first_sentence = re.split(
        r"(?<=[。！？!?])\s*|(?<=\.)\s+|\n+", normalize(answer), maxsplit=1
    )[0]
    return any(marker in first_sentence for marker in _INSUFFICIENT_MARKERS)
