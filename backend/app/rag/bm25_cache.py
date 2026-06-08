"""Per-user BM25 retriever cache.

Extracted from ``app.rag.retriever`` so that retriever orchestration and
keyword-index bookkeeping live in dedicated modules.

Cache lifecycle:
  - Entries expire after :data:`_BM25_CACHE_TTL` seconds.
  - :func:`invalidate_bm25_cache` drops all entries for a user after
    document ingestion so subsequent queries see fresh content.
  - :func:`_get_cached_bm25` returns an unexpired entry if present.
  - :func:`_build_and_cache_bm25` re-builds from the Postgres ``document_chunks``
    fact table.
"""

import logging
import time
from collections import OrderedDict
from threading import Lock
from typing import Optional

from llama_index.retrievers.bm25 import BM25Retriever

from app.core.config import settings

logger = logging.getLogger(__name__)


# 1 hour. Active invalidation is the primary freshness mechanism — every
# write path that puts new content into ``document_chunks``
# (``ingest_document``, ``ingest_text``, and ``delete_knowledge_document``)
# calls ``invalidate_bm25_cache(user_id)`` explicitly, so this TTL is a
# safety net for edge cases (e.g. a worker writes nodes without going
# through ingestion.py) rather than the primary "is this fresh" check.
_BM25_CACHE_TTL = 3600  # seconds

# LRU cap. Each entry holds a fully-built BM25Retriever (token frequency
# tables + the cached nodes themselves). A power user's corpus can be
# tens of MB; without a cap, a multi-tenant deploy with many active
# users would grow this dict without bound. 32 keeps memory predictable
# while comfortably exceeding the realistic concurrent-active-user
# count for a single API worker.
_BM25_CACHE_MAX = 32


class _BM25CacheEntry:
    __slots__ = ("retriever", "node_count", "created_at")

    def __init__(self, retriever: BM25Retriever, node_count: int):
        self.retriever = retriever
        self.node_count = node_count
        self.created_at = time.monotonic()

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > _BM25_CACHE_TTL


# Ordered for LRU semantics — most-recently-used at the tail, evict from
# the head when over ``_BM25_CACHE_MAX``. JS Maps' insertion-order trick
# isn't free in Python dicts (3.7+ guarantees insertion order on the
# normal dict but doesn't expose ``move_to_end``), hence OrderedDict.
_bm25_cache: "OrderedDict[str, _BM25CacheEntry]" = OrderedDict()
_bm25_cache_lock = Lock()


def _bm25_cache_key(user_id: str, source_kind: Optional[str]) -> str:
    return f"{user_id}|{source_kind or '*'}"


def invalidate_bm25_cache(user_id: str) -> None:
    """Invalidate all cached BM25 indexes for a given user.

    Call this after document ingestion to ensure fresh retrieval.
    """
    with _bm25_cache_lock:
        keys_to_remove = [k for k in _bm25_cache if k.startswith(f"{user_id}|")]
        for key in keys_to_remove:
            del _bm25_cache[key]
        if keys_to_remove:
            logger.info(
                "BM25 cache invalidated for user_id=%s (%d entries)",
                user_id,
                len(keys_to_remove),
            )


def _get_cached_bm25(
    user_id: str,
    source_kind: Optional[str],
    allowed_user_ids: list[str],
) -> Optional[BM25Retriever]:
    """Return a cached BM25 retriever if available and not expired."""
    cache_key = _bm25_cache_key(user_id, source_kind)
    with _bm25_cache_lock:
        entry = _bm25_cache.get(cache_key)
        if entry is not None and not entry.expired:
            # Move to tail (MRU) so the LRU eviction in
            # ``_build_and_cache_bm25`` doesn't drop a still-active user.
            _bm25_cache.move_to_end(cache_key)
            logger.info(
                "BM25 cache hit: key=%s nodes=%d", cache_key, entry.node_count,
            )
            return entry.retriever
    return None


def _build_and_cache_bm25(
    user_id: str,
    source_kind: Optional[str],
    allowed_user_ids: list[str],
    *,
    metadata_matches_scope,
) -> Optional[BM25Retriever]:
    """Build a BM25 retriever from the Postgres ``document_chunks`` fact table.

    Scoping is done by the SQL filter (user_id IN allowed + source_kind), so
    ``metadata_matches_scope`` is no longer needed here; it's kept in the
    signature for the caller's compatibility.
    """
    from llama_index.core.schema import TextNode

    from app.db.database import SessionLocal
    from app.models.document_chunk import DocumentChunk

    try:
        scope_users = allowed_user_ids or [user_id]
        with SessionLocal() as db:
            query = db.query(DocumentChunk).filter(DocumentChunk.user_id.in_(scope_users))
            if source_kind:
                query = query.filter(DocumentChunk.source_kind == source_kind)
            rows = query.order_by(DocumentChunk.created_at.asc()).all()

        filtered_nodes = [
            TextNode(
                text=r.text,
                id_=r.node_id or r.id,
                metadata={"user_id": r.user_id, "source_kind": r.source_kind},
            )
            for r in rows if r.text
        ]
        if not filtered_nodes:
            logger.warning(
                "BM25: 目标隔离区域下 chunk 为空。allowed_user_ids=%s source_kind=%s",
                allowed_user_ids, source_kind,
            )
            return None

        retriever = BM25Retriever.from_defaults(
            nodes=filtered_nodes,
            similarity_top_k=settings.BM25_TOP_K,
        )

        cache_key = _bm25_cache_key(user_id, source_kind)
        with _bm25_cache_lock:
            _bm25_cache[cache_key] = _BM25CacheEntry(retriever, len(filtered_nodes))
            _bm25_cache.move_to_end(cache_key)  # MRU on (re)insert
            # Evict oldest until under cap. Each entry can be MB-scale
            # so the cap protects multi-tenant memory budget.
            while len(_bm25_cache) > _BM25_CACHE_MAX:
                evicted_key, _ = _bm25_cache.popitem(last=False)
                logger.info("BM25 cache evict (LRU): key=%s", evicted_key)
        logger.info(
            "BM25 index built and cached: key=%s nodes=%d",
            cache_key,
            len(filtered_nodes),
        )
        return retriever

    except Exception as e:
        logger.warning("BM25 构建失败: %s", e)
        return None


__all__ = [
    "_BM25_CACHE_TTL",
    "_BM25CacheEntry",
    "_bm25_cache",
    "_bm25_cache_lock",
    "_bm25_cache_key",
    "invalidate_bm25_cache",
    "_get_cached_bm25",
    "_build_and_cache_bm25",
]
