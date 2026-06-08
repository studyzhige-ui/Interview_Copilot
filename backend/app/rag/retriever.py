import asyncio
import logging
import re
from threading import Lock
from typing import Optional, Dict, Any

from llama_index.core import Settings

# Cross-version LlamaIndex-Core shim: some versions dropped
# ``build_metadata_filter_fn``. The resume/ability LlamaIndex Milvus retrieval
# paths still rely on it, so keep this defensive patch.
import llama_index.core.vector_stores.utils
if not hasattr(llama_index.core.vector_stores.utils, "build_metadata_filter_fn"):
    def _mock_build_metadata_filter_fn(*args, **kwargs):
        return lambda x: True
    llama_index.core.vector_stores.utils.build_metadata_filter_fn = _mock_build_metadata_filter_fn

from llama_index.core.postprocessor.types import BaseNodePostprocessor

from app.core.config import settings
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.rag.reranker_registry import build_reranker, resolve_reranker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons with thread-safe lazy initialization
# ---------------------------------------------------------------------------

_reranker: Optional[BaseNodePostprocessor] = None
_reranker_lock = Lock()


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
# Helper utilities
# ---------------------------------------------------------------------------

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
    混合检索中枢（Milvus 原生 dense + BM25 hybrid + Reranker + 防幻觉拦截）。

    P0 安全：通过 Milvus hybrid_search 的 expr (user_id == pk) 隔离租户。
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

        # ===== [1] Scope — the Milvus hybrid_search ``expr`` filters by the
        # stable users.id pk server-side; allowed_user_ids drives the
        # defence-in-depth post-filter below. =====
        allowed_user_ids = _allowed_user_ids(user_pk, source_kind)
        logger.info(
            "RAG hybrid scope: requested_user_id=%s, user_pk=%s, source_kind=%s",
            user_id, user_pk, source_kind,
        )

        # ===== [2] Milvus 2.6 native hybrid: dense ANN + server-side BM25,
        # fused by RRF in one query. Replaces the old dense-only Milvus +
        # Postgres-sourced BM25 fusion. =====
        logger.info(f"开始 Milvus hybrid 检索: {query_str}")
        try:
            from llama_index.core import QueryBundle
            from llama_index.core.schema import NodeWithScore, TextNode

            from app.rag import milvus_hybrid

            query_bundle = QueryBundle(query_str)
            # Embedding + Milvus search are sync/blocking — off the event loop so
            # the SSE turn doesn't stall other in-flight requests.
            query_dense = await asyncio.to_thread(
                Settings.embed_model.get_query_embedding, query_str,
            )
            hits = await asyncio.to_thread(
                lambda: milvus_hybrid.hybrid_search(
                    query_text=query_str,
                    query_dense=query_dense,
                    user_pk=user_pk,
                    source_kind=source_kind,
                    top_k=settings.FUSION_TOP_K,
                )
            )
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
                if _metadata_matches_scope(
                    {"user_id": h["user_id"], "source_kind": h["source_kind"]},
                    allowed_user_ids, source_kind,
                )
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
