import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class RetrievalChunk:
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector_score: float | None = None
    lexical_score: float | None = None
    final_score: float = 0.0


@dataclass
class HybridRetrievalResult:
    chunks: list[RetrievalChunk]
    used_vector: bool = False
    used_lexical: bool = False
    degraded: bool = False
    error: str = ""


def query_terms(text: str) -> list[str]:
    normalized = text.lower()
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized)
    return list(dict.fromkeys(terms))


def lexical_overlap(query: str, content: str) -> float:
    terms = query_terms(query)
    if not terms:
        return 0.0
    normalized = content.lower()
    hits = sum(1 for term in terms if term in normalized)
    return hits / len(terms)


def recency_score(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return 0.0
    if not isinstance(value, datetime):
        return 0.0
    age_days = max((datetime.utcnow() - value).total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + age_days)


class HybridRetriever:
    """Small shared fusion layer for domain retrievers.

    Domain retrievers own storage-specific fetching. This layer keeps scoring and
    deduplication consistent between knowledge and memory retrieval.
    """

    async def retrieve(
        self,
        *,
        query: str,
        vector_fetch: Callable[[], Any] | None = None,
        lexical_fetch: Callable[[], Any] | None = None,
        final_top_k: int = 5,
    ) -> HybridRetrievalResult:
        vector_chunks: list[RetrievalChunk] = []
        lexical_chunks: list[RetrievalChunk] = []
        degraded = False
        errors: list[str] = []

        if vector_fetch is not None:
            try:
                vector_chunks = list(await vector_fetch())
            except Exception as exc:  # noqa: BLE001
                degraded = True
                errors.append(f"vector: {exc}")
                logger.warning("Vector retrieval degraded: %s", exc)

        if lexical_fetch is not None:
            try:
                lexical_chunks = list(await lexical_fetch())
            except Exception as exc:  # noqa: BLE001
                degraded = True
                errors.append(f"lexical: {exc}")
                logger.warning("Lexical retrieval degraded: %s", exc)

        merged: dict[str, RetrievalChunk] = {}
        for chunk in vector_chunks:
            chunk.vector_score = chunk.vector_score if chunk.vector_score is not None else 0.0
            chunk.final_score += 0.6 * chunk.vector_score
            merged[chunk.id] = chunk

        for chunk in lexical_chunks:
            existing = merged.get(chunk.id)
            lexical_score = chunk.lexical_score
            if lexical_score is None:
                lexical_score = lexical_overlap(query, chunk.text)
            if existing is None:
                chunk.lexical_score = lexical_score
                chunk.final_score += 0.35 * lexical_score
                merged[chunk.id] = chunk
            else:
                existing.lexical_score = max(existing.lexical_score or 0.0, lexical_score)
                existing.final_score += 0.35 * lexical_score
                existing.metadata.update(chunk.metadata)

        for chunk in merged.values():
            importance = float(chunk.metadata.get("importance") or 0.0)
            chunk.final_score += 0.15 * importance
            chunk.final_score += 0.05 * recency_score(
                chunk.metadata.get("updated_at") or chunk.metadata.get("created_at")
            )

        ranked = sorted(merged.values(), key=lambda item: item.final_score, reverse=True)
        return HybridRetrievalResult(
            chunks=ranked[:final_top_k],
            used_vector=bool(vector_chunks),
            used_lexical=bool(lexical_chunks),
            degraded=degraded,
            error="; ".join(errors),
        )
