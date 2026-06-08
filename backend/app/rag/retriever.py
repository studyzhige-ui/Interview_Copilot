import asyncio
import logging
import re
from threading import Lock
from typing import Optional, Dict, Any

from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter, FilterOperator
from llama_index.core.retrievers import VectorIndexRetriever

# 解决跨版本 LlamaIndex-Core 与 BM25 强绑定函数被移除的 Import Bug
import llama_index.core.vector_stores.utils
if not hasattr(llama_index.core.vector_stores.utils, "build_metadata_filter_fn"):
    def _mock_build_metadata_filter_fn(*args, **kwargs):
        return lambda x: True
    llama_index.core.vector_stores.utils.build_metadata_filter_fn = _mock_build_metadata_filter_fn

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.retrievers import QueryFusionRetriever

from app.core.config import settings
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.rag.reranker_registry import build_reranker, resolve_reranker
from app.rag.bm25_cache import (
    _build_and_cache_bm25 as _build_and_cache_bm25_impl,
    _get_cached_bm25,
)

# Re-exported so other modules and tests can import these via
# ``app.rag.retriever`` — ingestion.py imports ``invalidate_bm25_cache``
# from here, and test_bm25_cache.py asserts the re-export identity.
# They're unused *in this module*, so ``ruff --fix`` strips them as F401;
# the per-line noqa pins them on purpose. Do NOT delete.
from app.rag.bm25_cache import (
    _BM25_CACHE_TTL,  # noqa: F401
    _BM25CacheEntry,  # noqa: F401
    _bm25_cache,  # noqa: F401
    _bm25_cache_key,  # noqa: F401
    _bm25_cache_lock,  # noqa: F401
    invalidate_bm25_cache,  # noqa: F401
)

logger = logging.getLogger(__name__)

MILVUS_URI = settings.MILVUS_URI
MILVUS_COLLECTION = settings.MILVUS_COLLECTION


# ---------------------------------------------------------------------------
# Module-level singletons with thread-safe lazy initialization
# ---------------------------------------------------------------------------

_reranker: Optional[BaseNodePostprocessor] = None
_reranker_lock = Lock()

_milvus_store: Optional[MilvusVectorStore] = None
_milvus_index: Optional[VectorStoreIndex] = None
_milvus_lock = Lock()


def _milvus_dense_index_config() -> dict:
    return {
        "index_type": settings.MILVUS_DENSE_INDEX_TYPE,
        "metric_type": settings.MILVUS_SIMILARITY_METRIC,
        "M": settings.MILVUS_HNSW_M,
        "efConstruction": settings.MILVUS_HNSW_EF_CONSTRUCTION,
    }


def _milvus_search_config() -> dict:
    return {
        "metric_type": settings.MILVUS_SIMILARITY_METRIC,
        "params": {
            "ef": settings.MILVUS_HNSW_EF_SEARCH,
        },
    }


def _get_milvus_index() -> VectorStoreIndex:
    """Return a shared Milvus VectorStoreIndex, creating it once on first use."""
    global _milvus_store, _milvus_index
    if _milvus_index is not None:
        return _milvus_index
    with _milvus_lock:
        if _milvus_index is not None:
            return _milvus_index
        _milvus_store = MilvusVectorStore(
            uri=MILVUS_URI,
            collection_name=MILVUS_COLLECTION,
            dim=settings.EMBEDDING_DIM,
            overwrite=False,
            similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
            index_config=_milvus_dense_index_config(),
            search_config=_milvus_search_config(),
        )
        _milvus_index = VectorStoreIndex.from_vector_store(_milvus_store)
        logger.info(
            "Milvus VectorStoreIndex singleton created: collection=%s dim=%s metric=%s",
            MILVUS_COLLECTION,
            settings.EMBEDDING_DIM,
            settings.MILVUS_SIMILARITY_METRIC,
        )
        return _milvus_index


def init_reranker():
    """Initialize the reranker. Safe to call multiple times (idempotent).

    Provider + model are picked from ``RERANKER_PROVIDER`` + ``RERANKER_MODEL``
    env vars. Default keeps the previous behaviour (local BGE-Reranker
    v2 M3 from HF cache); switching ``RERANKER_PROVIDER=siliconflow`` etc
    skips the local download entirely.
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
                cfg.provider_id, cfg.model,
            )
        except Exception as e:
            # Reranker is part of the configured stack — if it can't load,
            # fail loud at startup so the operator notices and fixes the
            # config / downloads the model. Silently degrading to vector-only
            # makes RAG quality regressions easy to miss.
            logger.error("Reranker init failed: %s", e)
            raise


# ---------------------------------------------------------------------------
# BM25 cache adapter — see ``app.rag.bm25_cache`` for the implementation.
# ---------------------------------------------------------------------------


def _build_and_cache_bm25(
    user_id: int,
    source_kind: Optional[str],
    allowed_user_ids: list[int],
):
    """Compatibility wrapper — injects ``_metadata_matches_scope`` from this module."""
    return _build_and_cache_bm25_impl(
        user_id=user_id,
        source_kind=source_kind,
        allowed_user_ids=allowed_user_ids,
        metadata_matches_scope=_metadata_matches_scope,
    )


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _allowed_user_ids(user_id: int, source_kind: Optional[str]) -> list[int]:
    # ``is not None`` (not truthiness): the scope key is now a numeric users.id,
    # and a hypothetical pk of 0 must still scope to that user, never collapse to
    # an empty (and thus unscoped-fallback) list.
    return [user_id] if user_id is not None else []


def _metadata_matches_scope(
    metadata: dict[str, Any],
    allowed_user_ids: list[int],
    source_kind: Optional[str],
) -> bool:
    if allowed_user_ids and metadata.get("user_id") not in allowed_user_ids:
        return False
    if source_kind and metadata.get("source_kind") != source_kind:
        return False
    return True


def _build_metadata_filters(
    allowed_user_ids: list[int],
    source_kind: Optional[str],
) -> MetadataFilters:
    filter_list = []
    if len(allowed_user_ids) == 1:
        filter_list.append(
            MetadataFilter(
                key="user_id",
                value=allowed_user_ids[0],
                operator=FilterOperator.EQ,
            )
        )
    elif len(allowed_user_ids) > 1:
        filter_list.append(
            MetadataFilter(
                key="user_id",
                value=allowed_user_ids,
                operator=FilterOperator.IN,
            )
        )
    if source_kind:
        filter_list.append(
            MetadataFilter(
                key="source_kind",
                value=source_kind,
                operator=FilterOperator.EQ,
            )
        )
    return MetadataFilters(filters=filter_list, condition="and")


def _query_terms(text: str) -> list[str]:
    normalized = text.lower()
    terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized)
    return list(dict.fromkeys(terms))


def _lexical_overlap(query: str, content: str) -> float:
    terms = _query_terms(query)
    if not terms:
        return 0.0
    normalized = content.lower()
    hits = sum(1 for term in terms if term in normalized)
    return hits / len(terms)


def _score_passes(score: Optional[float], min_score: float) -> bool:
    """A node clears the bar iff its score meets ``min_score``.

    One threshold, no relaxation: the same ``RAG_MIN_SCORE`` applies whether or
    not a reranker ran. RAG holds the line — if nothing clears the bar the
    caller returns an empty result rather than admitting low-relevance chunks
    (宁缺毋滥). There is deliberately no second-pass score/lexical fallback.
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
            "%s #%s score=%s user_id=%s source_kind=%s file=%s text=%s",
            label,
            idx,
            f"{float(node.score):.4f}" if node.score is not None else "None",
            metadata.get("user_id"),
            metadata.get("source_kind"),
            metadata.get("file_name"),
            snippet,
        )


# ---------------------------------------------------------------------------
# Core retrieval function
# ---------------------------------------------------------------------------

async def query_knowledge_base(
    query_str: str,
    user_id: str,
    source_kind: Optional[str] = None,
    min_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    混合检索中枢（向量 + BM25 + Reranker + 防幻觉拦截）。

    P0 安全：严格通过 MetadataFilter 隔离 user_id。
    防幻觉：使用 Reranker 绝对置信分数截断低质量节点。
    """
    try:
        if min_score is None:
            min_score = settings.RAG_MIN_SCORE

        # Resolve the request principal (username) -> stable users.id once. The
        # RAG scope key (Milvus node metadata + document_chunks.user_id) is the
        # pk; everything below filters by it. An unresolved principal means no
        # accessible corpus -> return empty (never fall through to an unscoped
        # query, which would leak across tenants).
        with SessionLocal() as _db:
            user_pk = resolve_user_pk(_db, user_id)
        if user_pk is None:
            logger.warning(
                "query_knowledge_base: principal %r did not resolve to a users.id; "
                "returning empty (no unscoped retrieval).", user_id,
            )
            return {
                "answer": "[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。",
                "context_text": "[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。",
                "chunks": [],
                "sources": [],
            }

        # ===== [1] 连接 Milvus 向量引擎（复用单例） =====
        index = _get_milvus_index()

        # ===== [2] 构建多租户隔离过滤器 (Milvus MetadataFilter) =====
        allowed_user_ids = _allowed_user_ids(user_pk, source_kind)
        logger.info(
            "元数据过滤器已激活: requested_user_id=%s, user_pk=%s, allowed_user_ids=%s, source_kind=%s",
            user_id,
            user_pk,
            allowed_user_ids,
            source_kind,
        )

        # 向量检索器。每个 user_id 单独建 EQ filter，避免部分向量库不支持 IN。
        vector_retrievers = []
        filter_scopes = [[uid] for uid in allowed_user_ids] or [[]]
        for scope_user_ids in filter_scopes:
            vector_retrievers.append(
                VectorIndexRetriever(
                    index=index,
                    similarity_top_k=settings.VECTOR_TOP_K,
                    filters=_build_metadata_filters(scope_user_ids, source_kind),
                )
            )

        # ===== [3] BM25 检索器（per-user 缓存） =====
        if len(vector_retrievers) == 1:
            final_retriever = vector_retrievers[0]
        else:
            final_retriever = QueryFusionRetriever(
                retrievers=vector_retrievers,
                similarity_top_k=settings.FUSION_TOP_K,
                num_queries=1,
                mode="reciprocal_rerank",
            )

        bm25_retriever = _get_cached_bm25(user_pk, source_kind, allowed_user_ids)
        if bm25_retriever is None:
            bm25_retriever = _build_and_cache_bm25(user_pk, source_kind, allowed_user_ids)

        if bm25_retriever is not None:
            final_retriever = QueryFusionRetriever(
                retrievers=[*vector_retrievers, bm25_retriever],
                similarity_top_k=settings.FUSION_TOP_K,
                num_queries=1,
                mode="reciprocal_rerank",
            )
            logger.info("BM25 + 向量混合检索启动")
        else:
            logger.warning("BM25 不可用，仅使用向量检索。")

        # ===== [4] 检索 + Rerank + 防幻觉拦截 =====
        logger.info(f"开始检索: {query_str}")

        try:
            from llama_index.core import QueryBundle
            query_bundle = QueryBundle(query_str)
            raw_nodes = await final_retriever.aretrieve(query_str)
            raw_nodes = [
                node
                for node in raw_nodes
                if _metadata_matches_scope(node.node.metadata, allowed_user_ids, source_kind)
            ]
            _log_top_nodes("RAG raw candidates", raw_nodes)
        except Exception as ret_e:
            logger.error(f"节点召回失败: {ret_e}")
            raw_nodes = []

        # Reranker 交叉注意力重排序.
        #
        # ``postprocess_nodes`` is synchronous regardless of which
        # reranker backend is active: the local HF cross-encoder runs
        # CPU/GPU-bound torch ops; the remote API rerank
        # (``RemoteAPIRerank._postprocess_nodes``) uses ``httpx.Client``
        # with a 15s timeout. Either way, calling it inline from an
        # async retriever blocks the WHOLE event loop until the call
        # returns. ``asyncio.to_thread`` dispatches to a worker thread
        # so every other in-flight request can keep making progress
        # while reranking runs — typically saves 100-2000ms of
        # head-of-line blocking per concurrent turn.
        used_reranker = bool(_reranker and raw_nodes)
        if used_reranker:
            processed_nodes = await asyncio.to_thread(
                _reranker.postprocess_nodes, raw_nodes, query_bundle,
            )
        else:
            processed_nodes = raw_nodes
        _log_top_nodes("RAG processed candidates", processed_nodes)

        # 绝对分数阈值拦截：统一使用 RAG_MIN_SCORE，不因缺少 reranker 而放宽。
        # 过滤后无命中即返回空结果（宁缺毋滥），不再做词面覆盖 / 低分二次放行。
        valid_nodes = [
            node for node in processed_nodes
            if _score_passes(node.score, min_score)
        ]
        valid_nodes = valid_nodes[:settings.RERANK_TOP_N]

        if not valid_nodes:
            logger.warning(f"防幻觉拦截触发：所有节点得分低于阈值 ({min_score})")
            return {
                "answer": "[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。",
                "context_text": "[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。",
                "chunks": [],
                "sources": []
            }

        logger.info(f"通过阈值过滤: {len(valid_nodes)} 个节点 (阈值={min_score})")

        # ===== [5] 封装结果 =====
        sources = []
        texts = []
        chunks = []
        for n in valid_nodes:
            score = float(n.score) if n.score is not None else 0.0
            content = n.node.get_content().strip()
            overlap = _lexical_overlap(query_str, content)
            texts.append(f"[RAG Score: {score:.3f} | Lexical Overlap: {overlap:.2f}] {content}")
            chunks.append({
                "id": n.node.node_id,
                "text": content,
                "score": score,
                "lexical_overlap": overlap,
                "source_kind": n.node.metadata.get("source_kind"),
                "metadata": n.node.metadata,
            })
            sources.append({
                "score": score,
                "lexical_overlap": overlap,
                "score_source": "reranker" if used_reranker else "retriever",
                "text": content,
                "metadata": n.node.metadata
            })

        return {
            "answer": "\n\n".join(texts),
            "context_text": "\n\n".join(texts),
            "chunks": chunks,
            "sources": sources
        }

    except Exception as e:
        logger.error(f"检索引擎异常: {e}")
        raise
