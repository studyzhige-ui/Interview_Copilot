"""Milvus ability-state hybrid collection (MEMORY-V3).

A dedicated Milvus collection holding one vector per ability state — the
``search_text`` (topic + summary) embedded — so the agent can retrieve a user's
TOPIC-RELEVANT ability states instead of carrying all of them in every prompt.
Separate collection + params from the knowledge RAG collection.

Postgres (``memory_ability_states``) stays the fact source; this is an index
copy maintained asynchronously via outbox jobs (``upsert_memory_ability_index``
/ ``delete_memory_ability_index``), so a Milvus outage never blocks a memory
write — it only delays the index update. Write helpers raise on failure (the
outbox retries); the read helper degrades to an empty list (never breaks a
turn).
"""
from __future__ import annotations

import logging
from threading import Lock
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_store = None   # MilvusVectorStore singleton for the ability collection
_index = None   # VectorStoreIndex built on top of it
_lock = Lock()


def _init() -> Any:
    """Lazily build the shared ability-collection store + index."""
    global _store, _index
    if _index is not None:
        return _index
    with _lock:
        if _index is not None:
            return _index
        from llama_index.core import VectorStoreIndex
        from llama_index.vector_stores.milvus import MilvusVectorStore

        # Reuse the knowledge collection's HNSW index/search config (same engine,
        # same params) — only the collection name + the one-node-per-state model
        # differ. ``knowledge_service`` already imports these across the same
        # app.services → app.rag boundary.
        from app.rag.retriever import _milvus_dense_index_config, _milvus_search_config

        _store = MilvusVectorStore(
            uri=settings.MILVUS_URI,
            collection_name=settings.MEMORY_ABILITY_MILVUS_COLLECTION,
            dim=settings.EMBEDDING_DIM,
            overwrite=False,
            similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
            index_config=_milvus_dense_index_config(),
            search_config=_milvus_search_config(),
        )
        _index = VectorStoreIndex.from_vector_store(_store)
        logger.info(
            "Milvus ability collection ready: %s (dim=%s)",
            settings.MEMORY_ABILITY_MILVUS_COLLECTION, settings.EMBEDDING_DIM,
        )
        return _index


def upsert_ability(
    state_id: str,
    *,
    user_id: int,
    search_text: str,
    topic: str,
    skill_type: str,
    mastery_level: str,
    summary: str | None = None,
) -> None:
    """Index (or re-index) one ability state. Raises on failure so the outbox
    job retries."""
    from llama_index.core import Settings
    from llama_index.core.schema import TextNode

    _init()
    text = (search_text or topic or "").strip()
    if not text:
        return
    # Upsert = delete-then-add by the state id (the node's primary key).
    try:
        _store.delete_nodes([state_id])
    except Exception:  # noqa: BLE001 — first write has nothing to delete
        pass
    node = TextNode(
        id_=state_id,
        text=text,
        metadata={
            "user_id": user_id,
            "topic": topic,
            "skill_type": skill_type,
            "mastery_level": mastery_level,
            "summary": summary or "",
        },
    )
    node.embedding = Settings.embed_model.get_text_embedding(text)
    _store.add([node])


def delete_ability(state_id: str) -> None:
    """Drop one ability state's index copy. Raises on failure (outbox retries)."""
    _init()
    _store.delete_nodes([state_id])


def search_abilities(user_id: str, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
    """Return the user's most topic-relevant ability states for ``query``.

    ``user_id`` is the username principal; it's resolved to the stable users.id
    pk (the ability collection's scope key, CLEANUP #2) before filtering. Read
    path — degrades to ``[]`` on any Milvus error so a turn never breaks.
    """
    if not (query or "").strip():
        return []
    top_k = top_k or settings.MEMORY_ABILITY_TOP_K
    try:
        from app.core.user_identity import resolve_user_pk
        from app.db.database import SessionLocal
        from llama_index.core.retrievers import VectorIndexRetriever
        from llama_index.core.vector_stores import (
            FilterOperator,
            MetadataFilter,
            MetadataFilters,
        )

        # Resolve the username principal -> the pk the ability collection keys on.
        # Inside the try so a resolve/db hiccup degrades to [] like any other.
        with SessionLocal() as _db:
            user_pk = resolve_user_pk(_db, user_id)
        if user_pk is None:
            return []
        index = _init()
        retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=top_k,
            filters=MetadataFilters(
                filters=[MetadataFilter(key="user_id", value=user_pk, operator=FilterOperator.EQ)]
            ),
        )
        nodes = retriever.retrieve(query)
        out: list[dict[str, Any]] = []
        for n in nodes:
            m = n.node.metadata or {}
            if m.get("user_id") != user_pk:  # defence-in-depth on the tenant filter
                continue
            out.append({
                "topic": m.get("topic", ""),
                "skill_type": m.get("skill_type", ""),
                "mastery_level": m.get("mastery_level", ""),
                "summary": m.get("summary", ""),
                "score": float(n.score) if n.score is not None else 0.0,
            })
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("ability_index.search failed user=%s: %s", user_id, exc)
        return []


__all__ = ["upsert_ability", "delete_ability", "search_abilities"]
