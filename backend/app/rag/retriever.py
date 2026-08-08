"""Tenant-scoped hybrid retrieval for a list of search intents."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import defaultdict
from threading import Lock
from typing import Any

from llama_index.core import Settings
from llama_index.core.postprocessor.types import BaseNodePostprocessor

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.rag.contracts import SearchIntent
from app.rag.policy import current_rag_policy
from app.rag.reranker_registry import (
    RerankerUnavailableError,
    build_reranker,
    resolve_reranker,
)
from app.rag.retrieval_state import (
    EMPTY_ALL_BELOW_THRESHOLD,
    EMPTY_ALL_FILTERED_LIVE_CHECK,
    EMPTY_MILVUS_UNAVAILABLE,
    EMPTY_NO_CANDIDATES,
    EMPTY_PRINCIPAL_UNRESOLVED,
    EMPTY_RERANKER_UNAVAILABLE,
    SCORE_SOURCE_RERANKER,
    RetrievalResult,
    RetrievalState,
)

logger = logging.getLogger(__name__)

_reranker: BaseNodePostprocessor | None = None
_reranker_lock = Lock()


def init_reranker() -> None:
    global _reranker
    if _reranker is not None:
        return
    with _reranker_lock:
        if _reranker is not None:
            return
        config = resolve_reranker()
        _reranker = build_reranker(top_n=current_rag_policy().retrieval.final_count)
        logger.info(
            "Reranker ready: provider=%s model=%s",
            config.provider_id,
            config.model,
        )


def _hit_in_scope(
    hit: dict[str, Any],
    user_pk: int,
    source_kind: str | None = None,
) -> bool:
    return hit.get("user_id") == user_pk and (
        not source_kind or hit.get("source_kind") == source_kind
    )


def _normalized_text_hash(text: str) -> str:
    collapsed = " ".join((text or "").split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def _dedup_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    output: list[dict[str, Any]] = []
    for hit in hits:
        hit_id = str(hit.get("id") or "")
        text_hash = _normalized_text_hash(str(hit.get("text") or ""))
        if (hit_id and hit_id in seen_ids) or text_hash in seen_hashes:
            continue
        if hit_id:
            seen_ids.add(hit_id)
        seen_hashes.add(text_hash)
        output.append(hit)
    return output


def _fuse_hits(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """Fuse language variants and intents into one bounded candidate pool."""
    scores: defaultdict[str, float] = defaultdict(float)
    rows: dict[str, dict[str, Any]] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits, start=1):
            hit_id = str(hit.get("id") or "")
            if not hit_id:
                continue
            scores[hit_id] += 1.0 / (60 + rank)
            rows.setdefault(hit_id, hit)
    ranked = sorted(
        ({**rows[hit_id], "score": score} for hit_id, score in scores.items()),
        key=lambda hit: float(hit["score"]),
        reverse=True,
    )
    return _dedup_hits(ranked)[:limit]


def _score_passes(score: float | None, min_score: float) -> bool:
    return score is not None and score >= min_score


def _hydrate_node_ids(node_ids: list[str]) -> list[dict[str, Any]]:
    from app.rag.chunk_hydration import hydrate_chunks

    with SessionLocal() as db:
        return hydrate_chunks(db, node_ids)


def _empty(
    reason: str,
    *,
    fallback_used: bool = False,
    diagnostics: dict[str, Any] | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        state=RetrievalState(
            retrieval_hit=False,
            empty_reason=reason,
            fallback_used=fallback_used,
        ),
        diagnostics=diagnostics or {},
    )


def _coerce_intents(values: list[SearchIntent | dict]) -> list[SearchIntent]:
    maximum = current_rag_policy().retrieval.max_intents
    intents: list[SearchIntent] = []
    for value in values:
        intent = value if isinstance(value, SearchIntent) else SearchIntent(**value)
        if intent.query:
            intents.append(intent)
    return intents[:maximum]


def _search_specs(intents: list[SearchIntent]) -> list[tuple[int, str, str]]:
    return [
        (intent_index, dense_query, intent.sparse_query)
        for intent_index, intent in enumerate(intents)
        for dense_query in intent.dense_queries
    ]


def _language_bucket(text: str) -> str:
    """Coarse query/passage language routing for bilingual reranking."""
    cjk = len(re.findall(r"[一-鿿]", text or ""))
    latin = len(re.findall(r"[A-Za-z]", text or ""))
    return "zh" if cjk and cjk * 4 >= latin else "en"


async def _gather_hits(
    dense_query: str,
    sparse_query: str,
    user_pk: int,
    source_kind: str | None,
    top_k: int,
) -> list[dict[str, Any]]:
    from app.rag import milvus_hybrid

    query_dense = await asyncio.to_thread(
        Settings.embed_model.get_query_embedding,
        dense_query,
    )
    hits = await asyncio.to_thread(
        lambda: milvus_hybrid.hybrid_search(
            milvus_hybrid.KNOWLEDGE,
            query_text=sparse_query,
            query_dense=query_dense,
            user_pk=user_pk,
            top_k=top_k,
            filters={"source_kind": source_kind} if source_kind else None,
        )
    )
    return [hit for hit in hits if _hit_in_scope(hit, user_pk, source_kind)]


def _rerank_for_intents(
    reranker: BaseNodePostprocessor,
    raw_nodes_by_intent: list[list[Any]],
    intents: list[SearchIntent],
) -> list[Any]:
    from llama_index.core import QueryBundle
    from llama_index.core.schema import NodeWithScore

    groups: list[list[Any]] = []
    for intent, raw_nodes in zip(intents, raw_nodes_by_intent):
        query_by_language: dict[str, str] = {}
        for query in intent.dense_queries:
            query_by_language.setdefault(_language_bucket(query), query)
        nodes_by_query: dict[str, list[Any]] = defaultdict(list)
        for node in raw_nodes:
            content = node.node.get_content()
            query = query_by_language.get(_language_bucket(content), intent.query)
            nodes_by_query[query].append(node)

        ranked_intent: list[Any] = []
        for query, nodes in nodes_by_query.items():
            ranked = reranker.postprocess_nodes(
                [NodeWithScore(node=node.node, score=node.score) for node in nodes],
                QueryBundle(query),
            )
            ranked_intent.extend(ranked)
        groups.append(
            sorted(
                ranked_intent,
                key=lambda node: float(node.score or 0.0),
                reverse=True,
            )
        )
    output: list[Any] = []
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank >= len(group):
                continue
            node = group[rank]
            node_id = str(node.node.node_id or "")
            text_hash = _normalized_text_hash(node.node.get_content())
            if not node_id or node_id in seen_ids or text_hash in seen_texts:
                continue
            seen_ids.add(node_id)
            seen_texts.add(text_hash)
            output.append(node)
    return output


async def query_knowledge_base(
    *,
    intents: list[SearchIntent | dict],
    user_id: str,
    source_kind: str | None = None,
    min_score: float | None = None,
    include_diagnostics: bool = False,
) -> RetrievalResult:
    """Retrieve, rerank, gate, and hydrate evidence for one user turn."""
    policy = current_rag_policy().retrieval
    planned_intents = _coerce_intents(intents)
    if not planned_intents:
        return _empty(EMPTY_NO_CANDIDATES)
    use_deployed_gate = min_score is None
    threshold = policy.min_score if use_deployed_gate else min_score

    with SessionLocal() as database:
        user_pk = resolve_user_pk(database, user_id)
    if user_pk is None:
        return _empty(EMPTY_PRINCIPAL_UNRESOLVED)

    search_specs = _search_specs(planned_intents)
    gathered = await asyncio.gather(
        *[
            _gather_hits(
                dense_query,
                sparse_query,
                user_pk,
                source_kind,
                policy.candidate_count,
            )
            for _, dense_query, sparse_query in search_specs
        ],
        return_exceptions=True,
    )
    hits_by_intent: defaultdict[int, list[list[dict[str, Any]]]] = defaultdict(list)
    for (intent_index, _, _), result in zip(search_specs, gathered):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            logger.warning("RAG search variant failed: %s", result)
            continue
        hits_by_intent[intent_index].append(result)
    if not hits_by_intent:
        return _empty(EMPTY_MILVUS_UNAVAILABLE)

    candidate_groups = [
        _fuse_hits(hits_by_intent[index], limit=policy.candidate_count)
        for index in range(len(planned_intents))
        if index in hits_by_intent
    ]
    active_intents = [
        intent
        for index, intent in enumerate(planned_intents)
        if index in hits_by_intent
    ]
    candidates = _dedup_hits([hit for group in candidate_groups for hit in group])
    if not candidates:
        return _empty(EMPTY_NO_CANDIDATES)

    diagnostics = (
        {
            "candidate_node_ids": [str(hit.get("id") or "") for hit in candidates],
            "candidate_document_ids": [
                str(hit.get("document_id") or "") for hit in candidates
            ],
            "candidate_node_ids_by_intent": [
                [str(hit.get("id") or "") for hit in group]
                for group in candidate_groups
            ],
            "intent_count": len(planned_intents),
            "search_variant_count": sum(
                len(hits_by_intent[index]) for index in hits_by_intent
            ),
        }
        if include_diagnostics
        else {}
    )

    from llama_index.core.schema import NodeWithScore, TextNode

    raw_nodes_by_intent = [
        [
            NodeWithScore(
                node=TextNode(
                    text=str(hit["text"]),
                    id_=str(hit.get("id") or ""),
                    metadata={
                        "user_id": hit["user_id"],
                        "source_kind": hit["source_kind"],
                        "document_id": hit["document_id"],
                    },
                    excluded_embed_metadata_keys=[
                        "user_id",
                        "source_kind",
                        "document_id",
                    ],
                ),
                score=float(hit.get("score") or 0.0),
            )
            for hit in group
        ]
        for group in candidate_groups
    ]
    if _reranker is None:
        return _empty(
            EMPTY_RERANKER_UNAVAILABLE,
            fallback_used=True,
            diagnostics=diagnostics,
        )
    try:
        reranked = await asyncio.to_thread(
            _rerank_for_intents,
            _reranker,
            raw_nodes_by_intent,
            active_intents,
        )
    except RerankerUnavailableError:
        return _empty(
            EMPTY_RERANKER_UNAVAILABLE,
            fallback_used=True,
            diagnostics=diagnostics,
        )

    if include_diagnostics:
        diagnostics["reranked"] = [
            {
                "node_id": str(node.node.node_id or ""),
                "score": float(node.score) if node.score is not None else None,
            }
            for node in reranked
        ]

    valid = [node for node in reranked if _score_passes(node.score, float(threshold))][
        : policy.final_count
    ]
    if (
        use_deployed_gate
        and len(planned_intents) == 1
        and policy.score_margin is not None
        and valid
    ):
        best = float(valid[0].score or 0.0)
        valid = [
            node
            for node in valid
            if float(node.score or 0.0) >= best - policy.score_margin
        ]
    if not valid:
        return _empty(EMPTY_ALL_BELOW_THRESHOLD, diagnostics=diagnostics)

    ranked_ids: list[str] = []
    scores: dict[str, float] = {}
    for node in valid:
        node_id = str(node.node.node_id or "")
        if node_id and node_id not in scores:
            ranked_ids.append(node_id)
            scores[node_id] = float(node.score or 0.0)

    hydrated = await asyncio.to_thread(_hydrate_node_ids, ranked_ids)
    if not hydrated:
        return _empty(EMPTY_ALL_FILTERED_LIVE_CHECK, diagnostics=diagnostics)
    for chunk in hydrated:
        chunk["score"] = scores.get(str(chunk["node_id"]), 0.0)
        chunk["score_source"] = SCORE_SOURCE_RERANKER
    return RetrievalResult(
        chunks=hydrated,
        state=RetrievalState(retrieval_hit=True),
        diagnostics=diagnostics,
    )


__all__ = ["init_reranker", "query_knowledge_base"]
