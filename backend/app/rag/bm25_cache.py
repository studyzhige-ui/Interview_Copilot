"""Per-user BM25 retriever cache.

Extracted from ``app.rag.retriever`` so that retriever orchestration and
keyword-index bookkeeping live in dedicated modules.

Cache lifecycle:
  - Entries expire after :data:`_BM25_CACHE_TTL` seconds.
  - :func:`invalidate_bm25_cache` drops all entries for a user after
    document ingestion so subsequent queries see fresh content.
  - :func:`_get_cached_bm25` returns an unexpired entry if present.
  - :func:`_build_and_cache_bm25` re-builds from the Postgres docstore.
"""

import logging
import time
from threading import Lock
from typing import Optional

from llama_index.retrievers.bm25 import BM25Retriever

try:
    from llama_index.storage.docstore.postgres import PostgresDocumentStore
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    PostgresDocumentStore = None

from app.core.config import settings

logger = logging.getLogger(__name__)


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
            logger.info(
                "BM25 cache invalidated for user_id=%s (%d entries)",
                user_id,
                len(keys_to_remove),
            )


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
            logger.info(
                "BM25 cache hit: key=%s nodes=%d", cache_key, entry.node_count,
            )
            return entry.retriever
    return None


def _build_and_cache_bm25(
    user_id: str,
    source_type: Optional[str],
    allowed_user_ids: list[str],
    *,
    metadata_matches_scope,
) -> Optional[BM25Retriever]:
    """Build a BM25 retriever from the Postgres docstore, cache it, and return it.

    ``metadata_matches_scope`` is injected from the caller so that this
    module does not depend on the higher-level retriever's metadata-scope
    helper (avoids a circular import).
    """
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
            if metadata_matches_scope(n.metadata, allowed_user_ids, source_type)
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
