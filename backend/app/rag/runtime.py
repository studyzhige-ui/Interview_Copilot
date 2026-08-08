"""Process-local initialization for the RAG models actually in use."""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_embedding_ready = False
_reranker_ready = False


def ensure_rag_runtime(*, embedding: bool = False, reranker: bool = False) -> None:
    """Load each heavyweight RAG component at most once in this process.

    Normal chat and Agent retrieval runs in the turns worker. The API process
    only needs these models for its explicit diagnostic RAG endpoint, so that
    endpoint calls this helper lazily instead of delaying API readiness.
    """
    global _embedding_ready, _reranker_ready
    with _lock:
        if embedding and not _embedding_ready:
            from app.rag.embeddings import init_rag_settings

            init_rag_settings()
            _embedding_ready = True
        if reranker and not _reranker_ready:
            from app.rag.retriever import init_reranker

            init_reranker()
            _reranker_ready = True


__all__ = ["ensure_rag_runtime"]
