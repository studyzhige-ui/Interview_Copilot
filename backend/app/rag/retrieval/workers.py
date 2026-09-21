"""Process-owned pools for RAG resources; no Session crosses a thread boundary."""

from __future__ import annotations

import os
from threading import Lock
from typing import Literal

from app.core.bounded_work import BoundedWorkPool, WorkCapacityExceeded

Resource = Literal["storage", "search", "embedding", "reranking"]
_pools: dict[Resource, BoundedWorkPool] = {}
_lock = Lock()
_closed = False


def _after_fork() -> None:
    # Threads and their locks do not survive Celery prefork. Children lazily
    # create their own pools and never submit into the parent's dead executor.
    global _pools, _lock, _closed
    _pools, _lock, _closed = {}, Lock(), False


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork)


def pool(resource: Resource) -> BoundedWorkPool:
    from app.core.config import settings

    limits = {
        "storage": (settings.RAG_STORAGE_WORKERS, settings.RAG_STORAGE_QUEUE),
        "search": (settings.RAG_SEARCH_WORKERS, settings.RAG_SEARCH_QUEUE),
        "embedding": (settings.RAG_EMBEDDING_WORKERS, settings.RAG_EMBEDDING_QUEUE),
        "reranking": (settings.RAG_RERANK_WORKERS, settings.RAG_RERANK_QUEUE),
    }
    with _lock:
        if _closed:
            raise WorkCapacityExceeded("retrieval: shutting down")
        if resource not in _pools:
            workers, queue_size = limits[resource]
            _pools[resource] = BoundedWorkPool(
                f"rag-{resource}", workers=workers, queue_size=queue_size
            )
        return _pools[resource]


def close_pools() -> None:
    global _closed
    with _lock:
        _closed = True
        old = list(_pools.values())
    for instance in old:
        instance.shutdown()


def open_pools() -> None:
    """API lifespan restart is safe only after the previous work has drained."""
    global _closed
    with _lock:
        if not _closed:
            return
        if any(item.snapshot()["inflight"] for item in _pools.values()):
            raise RuntimeError("previous retrieval workers have not drained")
        _pools.clear()
        _closed = False
