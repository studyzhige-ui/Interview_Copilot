"""Core RAG retrieval: Milvus hybrid search → dedup → rerank → hydrate.

One retrieval pass (:func:`query_knowledge_base`):

  1. Resolve the request principal to the stable ``users.id`` pk — the ONLY
     Milvus pre-filter (P0 tenant boundary, server-side ``user_id == pk``).
  2. Milvus 2.6 native hybrid search: dense ANN on the ``dense_query``
     embedding + server-side BM25 on ``sparse_query``, fused by RRF. The two
     queries are real separate inputs — the planner writes a natural-language
     dense query and a keyword sparse query (retrieval plan §2.1/§2.3).
  3. Deterministic dedup (Milvus row id, then normalised-text hash). One
     hybrid search cannot repeat a primary key, so this mainly guards the
     multi-sub-query merge path; it is cheap either way.
  4. Cross-encoder rerank with the top-level dense query. A remote reranker
     transport failure takes the EXPLICIT fallback path: unranked RRF top-N,
     ``score_source=retriever_fallback``, and NO reranker-score threshold —
     RRF scores live on a ~1/60 scale, so ``RAG_MIN_SCORE=0.5`` would
     silently filter every one of them (retrieval plan §2.5).
  5. Postgres hydrate + live check for the final top-N via
     :func:`app.rag.chunk_hydration.hydrate_chunks` —
     Postgres text is the fact source; chunks of deleted/deleting documents
     drop out here.

Returns :class:`~app.rag.retrieval_state.RetrievalResult`: hydrated chunks in
rank order plus a structured :class:`RetrievalState`. The old
``[SYSTEM_EMPTY_WARNING]`` sentinel-string protocol is gone. The ``[K#]``
numbering and the final sources array are context assembly's job — NOT
produced here (retrieval plan §2.7).
"""

import asyncio
import hashlib
import logging
from threading import Lock
from typing import Any, Optional

from llama_index.core import Settings
from llama_index.core.postprocessor.types import BaseNodePostprocessor

from app.core.config import settings
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
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
    SCORE_SOURCE_RERANKER,
    SCORE_SOURCE_RETRIEVER_FALLBACK,
    RetrievalResult,
    RetrievalState,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level singletons with thread-safe lazy initialization
# ---------------------------------------------------------------------------

_reranker: Optional[BaseNodePostprocessor] = None
_reranker_lock = Lock()


def init_reranker():
    """Initialize the reranker. Safe to call multiple times (idempotent).

    Provider + model are picked from ``RERANKER_PROVIDER`` + ``RERANKER_MODEL``
    env vars. The lightweight default uses SiliconFlow; the optional local
    installation can run BGE-Reranker v2 M3 from the HuggingFace cache.
    """
    global _reranker
    if _reranker is not None:
        return
    with _reranker_lock:
        if _reranker is not None:
            return
        try:
            cfg = resolve_reranker()
            _reranker = build_reranker(top_n=settings.RERANK_TOP_N)
            logger.info(
                "Reranker ready: provider=%s model=%s",
                cfg.provider_id,
                cfg.model,
            )
        except Exception as e:
            # Reranker is part of the configured stack — if it can't load,
            # fail loud at startup so the operator notices and fixes the
            # config / downloads the model. Silently degrading to vector-only
            # makes RAG quality regressions easy to miss.
            logger.error("Reranker init failed: %s", e)
            raise


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _hit_in_scope(
    hit: dict[str, Any],
    user_pk: int,
    source_kind: Optional[str] = None,
) -> bool:
    """Defence-in-depth tenant check on a Milvus hit.

    The server-side expr already filters ``user_id == pk``; a row from
    another tenant must never survive even if that expr were wrong. With
    ``source_kind=None`` (the default) only the tenant check applies.
    Fails closed on a missing ``user_id``.
    """
    if hit.get("user_id") != user_pk:
        return False
    if source_kind and hit.get("source_kind") != source_kind:
        return False
    return True


def _normalized_text_hash(text: str) -> str:
    """Exact hash over whitespace-collapsed text — dedup rule 3 (deterministic;
    deliberately NO semantic similarity)."""
    collapsed = " ".join((text or "").split())
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def _dedup_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic pre-rerank dedup, keeping the FIRST copy: same Milvus row
    id → drop; same normalised full text → drop. Callers pass score-descending
    hits, so "first" is the higher-scored copy (the §2.6 retention rule)."""
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    out: list[dict[str, Any]] = []
    for hit in hits:
        hit_id = hit.get("id")
        if hit_id and hit_id in seen_ids:
            continue
        text_hash = _normalized_text_hash(hit.get("text", ""))
        if text_hash in seen_hashes:
            continue
        if hit_id:
            seen_ids.add(hit_id)
        seen_hashes.add(text_hash)
        out.append(hit)
    return out


def _score_passes(score: Optional[float], min_score: float) -> bool:
    """Reranker-score gate — applies ONLY to the reranker branch.

    The retriever-fallback branch (remote reranker unavailable) returns
    RRF-ordered top-N WITHOUT this threshold: RRF scores are ~1/60-scale
    and would never clear a cross-encoder threshold like 0.5.
    """
    if score is None:
        return False
    return score >= min_score


def _log_top_nodes(label: str, nodes: list[Any], limit: int = 5) -> None:
    if not nodes:
        logger.info("%s: no candidates", label)
        return
    for idx, node in enumerate(nodes[:limit], start=1):
        metadata = node.node.metadata if getattr(node, "node", None) else {}
        snippet = node.node.get_content().replace("\n", " ")[:100]
        logger.info(
            "%s #%s score=%s user_id=%s source_kind=%s document_id=%s text=%s",
            label,
            idx,
            f"{float(node.score):.4f}" if node.score is not None else "None",
            metadata.get("user_id"),
            metadata.get("source_kind"),
            metadata.get("document_id"),
            snippet,
        )


def _hydrate_node_ids(node_ids: list[str]) -> list[dict[str, Any]]:
    """Sync hydrate + live check (runs in a worker thread)."""
    from app.rag.chunk_hydration import hydrate_chunks

    with SessionLocal() as db:
        return hydrate_chunks(db, node_ids)


def _empty(reason: str, *, fallback_used: bool = False) -> RetrievalResult:
    return RetrievalResult(
        state=RetrievalState(
            retrieval_hit=False,
            empty_reason=reason,
            fallback_used=fallback_used,
        )
    )


async def _gather_hits(
    dense_q: str,
    sparse_q: str,
    user_pk: int,
    source_kind: Optional[str],
    top_k: int,
) -> list[dict[str, Any]]:
    """One Milvus hybrid pass (dense ANN on the dense query's embedding +
    server-side BM25 on the sparse query), tenant-scoped. Embedding + search
    are sync/blocking — dispatched off the event loop. Raises on a Milvus
    failure so the caller can map it to ``milvus_unavailable``."""
    from app.rag import milvus_hybrid

    query_dense = await asyncio.to_thread(
        Settings.embed_model.get_query_embedding,
        dense_q,
    )
    hits = await asyncio.to_thread(
        lambda: milvus_hybrid.hybrid_search(
            milvus_hybrid.KNOWLEDGE,
            query_text=sparse_q,
            query_dense=query_dense,
            user_pk=user_pk,
            top_k=top_k,
            filters={"source_kind": source_kind} if source_kind else None,
        )
    )
    return [h for h in hits if _hit_in_scope(h, user_pk, source_kind)]


def _retrieval_specs(
    dense_q: str,
    sparse_q: str,
    sub_queries: Optional[list[dict]],
) -> list[tuple[str, str]]:
    """Build the (dense, sparse) query specs to fan out over.

    Multi-sub-query turns retrieve each sub-query separately (map-reduce);
    a single-intent turn uses one top-level spec. Sub-queries are capped at
    ``MAX_SUB_QUERIES`` (defensive — the planner already limits them) and a
    blank side falls back to the other. Malformed/empty sub-queries collapse
    to the single top-level spec."""
    specs: list[tuple[str, str]] = []
    for sq in (sub_queries or [])[: settings.MAX_SUB_QUERIES]:
        sd = (sq.get("dense_query") or sq.get("sparse_query") or "").strip()
        ss = (sq.get("sparse_query") or sq.get("dense_query") or "").strip()
        if sd:
            specs.append((sd, ss))
    return specs or [(dense_q, sparse_q)]


# ---------------------------------------------------------------------------
# Core retrieval function
# ---------------------------------------------------------------------------


async def query_knowledge_base(
    *,
    dense_query: str,
    sparse_query: str,
    user_id: str,
    source_kind: Optional[str] = None,
    sub_queries: Optional[list[dict]] = None,
) -> RetrievalResult:
    """混合检索中枢（Milvus 原生 dense + BM25 hybrid + Reranker + hydrate）。

    P0 安全：通过 Milvus hybrid_search 的 expr (user_id == pk) 隔离租户。
    防幻觉：reranker 绝对置信分数截断低质量节点（fallback 分支除外，见
    ``_score_passes``）。返回的 chunk 文本以 Postgres facts 为准。

    ``sub_queries`` (planner-detected multi-intent turns): each
    ``{dense_query, sparse_query}`` is retrieved separately with a smaller
    candidate budget (``SUB_QUERY_FUSION_TOP_K``); the merged, deduped pool
    goes through ONE unified rerank keyed on the top-level ``dense_query``
    (retrieval plan §2.3/§2.5). A single-intent turn uses one top-level pass
    with ``FUSION_TOP_K``.
    """
    min_score = settings.RAG_MIN_SCORE

    # Either query may be blank (planner fallback / single-query L2 caller
    # passing one string) — each side falls back to the other.
    dense_q = (dense_query or sparse_query or "").strip()
    sparse_q = (sparse_query or dense_query or "").strip()
    if not dense_q:
        # Deliberate reuse of no_candidates (the frozen enum has no
        # "no query" value; live callers never send a fully blank pair).
        return _empty(EMPTY_NO_CANDIDATES)

    # Resolve the request principal (username) -> stable users.id once. An
    # unresolved principal means no accessible corpus -> return empty (never
    # fall through to an unscoped query, which would leak across tenants).
    with SessionLocal() as _db:
        user_pk = resolve_user_pk(_db, user_id)
    if user_pk is None:
        logger.warning(
            "query_knowledge_base: principal %r did not resolve to a users.id; "
            "returning empty (no unscoped retrieval).",
            user_id,
        )
        return _empty(EMPTY_PRINCIPAL_UNRESOLVED)

    # ===== [1] Milvus 2.6 native hybrid: dense ANN on the dense query's
    # embedding + server-side BM25 on the sparse query, fused by RRF. For a
    # multi-intent turn each sub-query is one pass (smaller budget), run
    # concurrently and merged into a single candidate pool. =====
    specs = _retrieval_specs(dense_q, sparse_q, sub_queries)
    per_query_top_k = (
        settings.SUB_QUERY_FUSION_TOP_K if len(specs) > 1 else settings.FUSION_TOP_K
    )
    logger.info(
        "RAG hybrid retrieval: user_pk=%s specs=%d top_k=%d source_kind=%s",
        user_pk,
        len(specs),
        per_query_top_k,
        source_kind,
    )
    # Concurrent fan-out: each spec's embed + Milvus round-trip overlaps the
    # others (capped at MAX_SUB_QUERIES). One failed sub-query must not discard
    # useful candidates returned by the other independent intents.
    gathered = await asyncio.gather(
        *[_gather_hits(d, s, user_pk, source_kind, per_query_top_k) for d, s in specs],
        return_exceptions=True,
    )
    per_spec_hits: list[list[dict[str, Any]]] = []
    for index, result in enumerate(gathered):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            logger.warning(
                "RAG sub-query %d/%d failed: %s",
                index + 1,
                len(specs),
                result,
            )
            continue
        per_spec_hits.append(result)
    if not per_spec_hits:
        logger.error(
            "RAG hybrid search unavailable for all %d query spec(s)",
            len(specs),
        )
        return _empty(EMPTY_MILVUS_UNAVAILABLE)

    hits = [h for spec_hits in per_spec_hits for h in spec_hits]
    if not hits:
        return _empty(EMPTY_NO_CANDIDATES)

    # ===== [2] Deterministic dedup (id → normalised text hash). Also folds
    # the same chunk hit by multiple sub-queries into one candidate.
    # Stable-sort by score desc FIRST so the higher-scored copy wins the
    # dedup (§2.6 retention rule); spec order is the tiebreak. No-op for a
    # single query (already RRF-descending). Matters only on the reranker-
    # fallback path, where this RRF score is the final score. =====
    hits.sort(key=lambda h: h.get("score") or 0.0, reverse=True)
    hits = _dedup_hits(hits)

    from llama_index.core import QueryBundle
    from llama_index.core.schema import NodeWithScore, TextNode

    raw_nodes = [
        NodeWithScore(
            node=TextNode(
                text=h["text"],
                id_=h["id"] or "",
                metadata={
                    "user_id": h["user_id"],
                    "source_kind": h["source_kind"],
                    "document_id": h["document_id"],
                },
            ),
            score=h["score"],
        )
        for h in hits
    ]
    _log_top_nodes("RAG raw candidates", raw_nodes)

    # ===== [3] Rerank (cross-encoder), query = the top-level dense query.
    #
    # ``postprocess_nodes`` is synchronous regardless of backend (local HF
    # cross-encoder = torch ops; remote = blocking httpx) — dispatch to a
    # worker thread so concurrent turns keep making progress.
    fallback_used = False
    if _reranker is None:
        # init_reranker() is fail-loud at startup; reaching here means it was
        # never called (defensive). Take the explicit fallback path.
        logger.warning("Reranker not initialised; using RRF-order fallback")
        fallback_used = True
        processed_nodes = raw_nodes
    else:
        try:
            processed_nodes = await asyncio.to_thread(
                _reranker.postprocess_nodes,
                raw_nodes,
                QueryBundle(dense_q),
            )
        except RerankerUnavailableError as exc:
            logger.warning(
                "Reranker unavailable; falling back to RRF order: %s",
                exc,
            )
            fallback_used = True
            processed_nodes = raw_nodes
    _log_top_nodes("RAG processed candidates", processed_nodes)

    # ===== [4] Score gate + final top-N. The fallback branch skips the
    # reranker-score threshold (different scale) and is labelled so it can
    # never be mistaken for reranker output. =====
    if fallback_used:
        valid_nodes = processed_nodes[: settings.RERANK_TOP_N]
        score_source = SCORE_SOURCE_RETRIEVER_FALLBACK
    else:
        valid_nodes = [
            node for node in processed_nodes if _score_passes(node.score, min_score)
        ][: settings.RERANK_TOP_N]
        score_source = SCORE_SOURCE_RERANKER
        if not valid_nodes:
            logger.warning("防幻觉拦截触发：所有节点得分低于阈值 (%s)", min_score)
            return _empty(EMPTY_ALL_BELOW_THRESHOLD)

    # Light post-rerank dedup by node id — guards fallback/anomalous paths.
    seen: set[str] = set()
    ranked_node_ids: list[str] = []
    score_by_node: dict[str, float] = {}
    for node in valid_nodes:
        node_id = node.node.node_id
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        ranked_node_ids.append(node_id)
        score_by_node[node_id] = float(node.score) if node.score is not None else 0.0

    # ===== [5] Postgres hydrate + live check (fact text + provenance). =====
    hydrated = await asyncio.to_thread(_hydrate_node_ids, ranked_node_ids)
    if not hydrated:
        logger.warning(
            "RAG live check dropped all %d candidates (stale Milvus rows?)",
            len(ranked_node_ids),
        )
        return _empty(EMPTY_ALL_FILTERED_LIVE_CHECK, fallback_used=fallback_used)

    chunks: list[dict[str, Any]] = []
    for chunk in hydrated:
        chunk["score"] = score_by_node.get(chunk["node_id"], 0.0)
        chunk["score_source"] = score_source
        chunks.append(chunk)

    logger.info(
        "RAG retrieval done: %d chunks (score_source=%s)",
        len(chunks),
        score_source,
    )
    return RetrievalResult(
        chunks=chunks,
        state=RetrievalState(retrieval_hit=True, fallback_used=fallback_used),
    )
