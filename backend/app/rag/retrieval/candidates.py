"""Tenant-scoped candidate retrieval with one lexical search per intent."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from llama_index.core import Settings

from app.rag.domain.models import SearchIntent
from app.rag.index.identity import current_index_identity
from app.rag.index.vector_validation import validate_vector
from app.rag.policy import current_rag_policy
from app.rag.retrieval.fusion import reciprocal_rank_fusion


class CandidateSearchUnavailable(RuntimeError):
    pass


@dataclass
class IntentCandidates:
    intent: SearchIntent
    hits: list[dict[str, Any]] = field(default_factory=list)
    channel_errors: list[str] = field(default_factory=list)


def _in_scope(
    hit: dict[str, Any],
    *,
    user_pk: int,
    source_kind: str | None,
    document_ids: set[str],
) -> bool:
    return (
        hit.get("user_id") == user_pk
        and (not source_kind or hit.get("source_kind") == source_kind)
        and (not document_ids or str(hit.get("document_id") or "") in document_ids)
        # Conversation attachments are available only through explicit
        # document IDs; they must never leak into global knowledge retrieval.
        and (bool(document_ids) or hit.get("source_kind") != "chat_attachment")
    )


async def _query_embedding(query: str) -> list[float]:
    vector = await asyncio.to_thread(Settings.embed_model.get_query_embedding, query)
    return validate_vector(
        vector,
        expected_dim=current_index_identity().embedding_dim,
        label="查询",
    )


async def search_intent_candidates(
    intent: SearchIntent,
    *,
    user_pk: int,
    source_kind: str | None,
    candidate_count: int,
) -> IntentCandidates:
    """Run one BM25 request and one dense request per query-language variant."""

    from app.rag import milvus_hybrid

    policy = current_rag_policy().retrieval
    document_ids = set(intent.document_ids)
    filters: dict[str, Any] = {}
    if source_kind:
        filters["source_kind"] = source_kind
    if document_ids:
        filters["document_id"] = sorted(document_ids)

    async def sparse() -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            lambda: milvus_hybrid.sparse_search(
                milvus_hybrid.KNOWLEDGE,
                query_text=intent.sparse_query,
                user_pk=user_pk,
                top_k=candidate_count,
                filters=filters or None,
            )
        )

    async def dense(query: str) -> list[dict[str, Any]]:
        vector = await _query_embedding(query)
        return await asyncio.to_thread(
            lambda: milvus_hybrid.dense_search(
                milvus_hybrid.KNOWLEDGE,
                query_dense=vector,
                user_pk=user_pk,
                top_k=candidate_count,
                filters=filters or None,
            )
        )

    channels = [sparse(), *[dense(query) for query in intent.dense_queries]]
    raw = await asyncio.gather(
        *[
            asyncio.wait_for(channel, timeout=policy.search_timeout_seconds)
            for channel in channels
        ],
        return_exceptions=True,
    )
    ranked_lists: list[list[dict[str, Any]]] = []
    weights: list[float] = []
    errors: list[str] = []
    dense_variant_weight = policy.dense_weight / max(1, len(intent.dense_queries))
    for index, result in enumerate(raw):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            errors.append(f"{type(result).__name__}: {result}")
            continue
        scoped = [
            hit
            for hit in result
            if str(hit.get("id") or "")
            and str(hit.get("text") or "").strip()
            and _in_scope(
                hit,
                user_pk=user_pk,
                source_kind=source_kind,
                document_ids=document_ids,
            )
        ]
        ranked_lists.append(scoped)
        weights.append(policy.sparse_weight if index == 0 else dense_variant_weight)
    if not ranked_lists:
        raise CandidateSearchUnavailable("; ".join(errors) or "all channels failed")
    hits = reciprocal_rank_fusion(
        ranked_lists,
        weights=weights,
        rrf_k=policy.rrf_k,
        limit=candidate_count,
    )
    for hit in hits:
        hit["intent_ids"] = [intent.intent_id]
    return IntentCandidates(intent=intent, hits=hits, channel_errors=errors)


__all__ = [
    "CandidateSearchUnavailable",
    "IntentCandidates",
    "search_intent_candidates",
]
