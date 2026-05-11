import logging
import re
import time
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

from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
try:
    from llama_index.storage.docstore.postgres import PostgresDocumentStore
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    PostgresDocumentStore = None

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot

logger = logging.getLogger(__name__)

MILVUS_URI = settings.MILVUS_URI
MILVUS_COLLECTION = settings.MILVUS_COLLECTION


# ---------------------------------------------------------------------------
# Module-level singletons with thread-safe lazy initialization
# ---------------------------------------------------------------------------

_reranker: Optional[SentenceTransformerRerank] = None
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
    """Initialize the reranker model. Safe to call multiple times (idempotent)."""
    global _reranker
    if _reranker is not None:
        return
    with _reranker_lock:
        if _reranker is not None:
            return
        try:
            prepare_hf_runtime()
            reranker_model = resolve_local_snapshot(settings.RERANKER_MODEL_ID)
            if reranker_model is None:
                raise RuntimeError(
                    f"Reranker model '{settings.RERANKER_MODEL_ID}' is missing. "
                    "Run the model init script before starting the backend."
                )
            _reranker = SentenceTransformerRerank(
                model=reranker_model,
                top_n=settings.RERANK_TOP_N,
            )
            logger.info("BGE-Reranker 交叉注意力模型加载完成。")
        except Exception as e:
            logger.error(f"BGE-Reranker 启动失败: {e}")
            raise


# ---------------------------------------------------------------------------
# Per-user BM25 Index Cache
# ---------------------------------------------------------------------------

_BM25_CACHE_TTL = 300  # seconds — rebuild index if older than 5 minutes

class _BM25CacheEntry:
    __slots__ = ("retriever", "node_count", "created_at")

    def __init__(self, retriever: BM25Retriever, node_count: int):
        self.retriever = retriever
        self.node_count = node_count
        self.created_at = time.monotonic()

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > _BM25_CACHE_TTL


_bm25_cache: dict[str, _BM25CacheEntry] = {}
_bm25_cache_lock = Lock()


def _bm25_cache_key(user_id: str, source_type: Optional[str]) -> str:
    return f"{user_id}|{source_type or '*'}"


def invalidate_bm25_cache(user_id: str) -> None:
    """Invalidate all cached BM25 indexes for a given user.

    Call this after document ingestion to ensure fresh retrieval.
    """
    with _bm25_cache_lock:
        keys_to_remove = [k for k in _bm25_cache if k.startswith(f"{user_id}|")]
        for key in keys_to_remove:
            del _bm25_cache[key]
        if keys_to_remove:
            logger.info("BM25 cache invalidated for user_id=%s (%d entries)", user_id, len(keys_to_remove))


def _get_cached_bm25(
    user_id: str,
    source_type: Optional[str],
    allowed_user_ids: list[str],
) -> Optional[BM25Retriever]:
    """Return a cached BM25 retriever if available and not expired."""
    cache_key = _bm25_cache_key(user_id, source_type)
    with _bm25_cache_lock:
        entry = _bm25_cache.get(cache_key)
        if entry is not None and not entry.expired:
            logger.info("BM25 cache hit: key=%s nodes=%d", cache_key, entry.node_count)
            return entry.retriever
    return None


def _build_and_cache_bm25(
    user_id: str,
    source_type: Optional[str],
    allowed_user_ids: list[str],
) -> Optional[BM25Retriever]:
    """Build a BM25 retriever from the docstore, cache it, and return it."""
    if PostgresDocumentStore is None:
        return None
    try:
        docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
        all_nodes = list(docstore.docs.values())
        logger.info("Postgres Docstore 节点总数: %s", len(all_nodes))

        if not all_nodes:
            return None

        filtered_nodes = [
            n for n in all_nodes
            if _metadata_matches_scope(n.metadata, allowed_user_ids, source_type)
        ]
        if not filtered_nodes:
            logger.warning(
                "BM25: 目标隔离区域下节点为空。allowed_user_ids=%s source_type=%s",
                allowed_user_ids, source_type,
            )
            return None

        retriever = BM25Retriever.from_defaults(
            nodes=filtered_nodes,
            similarity_top_k=settings.BM25_TOP_K,
        )

        cache_key = _bm25_cache_key(user_id, source_type)
        with _bm25_cache_lock:
            _bm25_cache[cache_key] = _BM25CacheEntry(retriever, len(filtered_nodes))
        logger.info("BM25 index built and cached: key=%s nodes=%d", cache_key, len(filtered_nodes))
        return retriever

    except Exception as e:
        logger.warning("BM25 构建失败: %s", e)
        return None


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _allowed_user_ids(user_id: str, source_type: Optional[str]) -> list[str]:
    return [user_id] if user_id else []


def _metadata_matches_scope(
    metadata: dict[str, Any],
    allowed_user_ids: list[str],
    source_type: Optional[str],
) -> bool:
    if allowed_user_ids and metadata.get("user_id") not in allowed_user_ids:
        return False
    if source_type and metadata.get("source_type") != source_type:
        return False
    return True


def _build_metadata_filters(
    allowed_user_ids: list[str],
    source_type: Optional[str],
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
    if source_type:
        filter_list.append(
            MetadataFilter(
                key="source_type",
                value=source_type,
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


def _score_passes(score: Optional[float], min_score: float, used_reranker: bool) -> bool:
    if score is None:
        return False
    if used_reranker:
        return score >= min_score
    return score >= min(min_score, settings.RAG_FALLBACK_MIN_SCORE)


def _log_top_nodes(label: str, nodes: list[Any], limit: int = 5) -> None:
    if not nodes:
        logger.info("%s: no candidates", label)
        return
    for idx, node in enumerate(nodes[:limit], start=1):
        metadata = node.node.metadata if getattr(node, "node", None) else {}
        snippet = node.node.get_content().replace("\n", " ")[:100]
        logger.info(
            "%s #%s score=%s user_id=%s source_type=%s file=%s text=%s",
            label,
            idx,
            f"{float(node.score):.4f}" if node.score is not None else "None",
            metadata.get("user_id"),
            metadata.get("source_type"),
            metadata.get("file_name"),
            snippet,
        )


# ---------------------------------------------------------------------------
# Core retrieval function
# ---------------------------------------------------------------------------

async def query_knowledge_base(
    query_str: str,
    user_id: str,
    source_type: Optional[str] = None,
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

        # ===== [1] 连接 Milvus 向量引擎（复用单例） =====
        index = _get_milvus_index()

        # ===== [2] 构建多租户隔离过滤器 (Milvus MetadataFilter) =====
        allowed_user_ids = _allowed_user_ids(user_id, source_type)
        logger.info(
            "元数据过滤器已激活: requested_user_id=%s, allowed_user_ids=%s, source_type=%s",
            user_id,
            allowed_user_ids,
            source_type,
        )

        # 向量检索器。每个 user_id 单独建 EQ filter，避免部分向量库不支持 IN。
        vector_retrievers = []
        filter_scopes = [[uid] for uid in allowed_user_ids] or [[]]
        for scope_user_ids in filter_scopes:
            vector_retrievers.append(
                VectorIndexRetriever(
                    index=index,
                    similarity_top_k=settings.VECTOR_TOP_K,
                    filters=_build_metadata_filters(scope_user_ids, source_type),
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

        bm25_retriever = _get_cached_bm25(user_id, source_type, allowed_user_ids)
        if bm25_retriever is None:
            bm25_retriever = _build_and_cache_bm25(user_id, source_type, allowed_user_ids)

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
                if _metadata_matches_scope(node.node.metadata, allowed_user_ids, source_type)
            ]
            _log_top_nodes("RAG raw candidates", raw_nodes)
        except Exception as ret_e:
            logger.error(f"节点召回失败: {ret_e}")
            raw_nodes = []

        # Reranker 交叉注意力重排序
        used_reranker = bool(_reranker and raw_nodes)
        if used_reranker:
            processed_nodes = _reranker.postprocess_nodes(raw_nodes, query_bundle)
        else:
            processed_nodes = raw_nodes
        _log_top_nodes("RAG processed candidates", processed_nodes)

        # 绝对分数阈值拦截。RRF/向量分数和 reranker 分数尺度不同，不能共用 0.5。
        valid_nodes = [
            node for node in processed_nodes
            if _score_passes(node.score, min_score, used_reranker)
        ]
        valid_nodes = valid_nodes[:settings.RERANK_TOP_N]

        if not valid_nodes and processed_nodes:
            lexical_nodes = [
                node
                for node in processed_nodes
                if _lexical_overlap(query_str, node.node.get_content())
                >= settings.RAG_LEXICAL_FALLBACK_MIN_OVERLAP
            ]
            if lexical_nodes:
                logger.warning(
                    "RAG 阈值未命中，但词面覆盖通过 fallback: query=%s overlap_threshold=%.2f",
                    query_str,
                    settings.RAG_LEXICAL_FALLBACK_MIN_OVERLAP,
                )
                valid_nodes = lexical_nodes[:settings.RERANK_TOP_N]

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
                "source_type": n.node.metadata.get("source_type"),
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
