"""Milvus-backed vector store for memory items (canonical location).

Was previously at ``app.services.memory_vector_service`` — moved here as
part of the memory subpackage consolidation.

Singleton notes
---------------
``MilvusVectorStore(...)`` is **not** cheap: each instantiation opens a
gRPC channel, pings the collection, and re-fetches schema. Per-query
recreation made memory recall 30-200ms slower under concurrency.

We now cache one ``store`` + ``index`` pair per ``MemoryVectorService``
instance, behind a double-checked lock. ``overwrite=True`` is reserved
for initialisation and bypasses the cache via ``_build_fresh_store()``
so it can re-create the collection without poisoning the live singleton.
"""

import logging
from datetime import datetime
from threading import Lock
from typing import Any

from llama_index.core import Document, StorageContext, VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.vector_stores import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.milvus import MilvusVectorStore
from sqlalchemy.orm import Session

try:
    from llama_index.storage.docstore.postgres import PostgresDocumentStore
except ModuleNotFoundError:  # pragma: no cover - optional runtime dependency
    PostgresDocumentStore = None

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.memory import MemoryItem
from app.rag.hybrid import RetrievalChunk

logger = logging.getLogger(__name__)

EMBEDDING_DIM = settings.EMBEDDING_DIM


class MemoryVectorService:
    def __init__(self):
        self.collection_name = settings.MEMORY_MILVUS_COLLECTION
        # Cached singletons — lazily initialised on first use.
        self._store: MilvusVectorStore | None = None
        self._index: VectorStoreIndex | None = None
        self._lock = Lock()

    def _build_fresh_store(self, overwrite: bool = False) -> MilvusVectorStore:
        """Construct a NEW MilvusVectorStore (used for overwrite=True paths
        and as the inner factory for the cached singleton)."""
        return MilvusVectorStore(
            uri=settings.MILVUS_URI,
            collection_name=self.collection_name,
            dim=EMBEDDING_DIM,
            overwrite=overwrite,
            similarity_metric=settings.MILVUS_SIMILARITY_METRIC,
            index_config={
                "index_type": settings.MILVUS_DENSE_INDEX_TYPE,
                "metric_type": settings.MILVUS_SIMILARITY_METRIC,
                "M": settings.MILVUS_HNSW_M,
                "efConstruction": settings.MILVUS_HNSW_EF_CONSTRUCTION,
            },
            search_config={
                "metric_type": settings.MILVUS_SIMILARITY_METRIC,
                "params": {"ef": settings.MILVUS_HNSW_EF_SEARCH},
            },
        )

    def _get_store_and_index(self) -> tuple[MilvusVectorStore, VectorStoreIndex]:
        """Return cached (store, index) — double-checked lock pattern.

        99% of calls hit the fast path with no lock. The slow path
        (cold start, ~once per process per service instance) holds the
        lock just long enough to construct the store + index.
        """
        if self._index is not None and self._store is not None:
            return self._store, self._index
        with self._lock:
            if self._index is not None and self._store is not None:
                return self._store, self._index
            store = self._build_fresh_store(overwrite=False)
            index = VectorStoreIndex.from_vector_store(store)
            self._store = store
            self._index = index
            logger.info(
                "MemoryVectorService singleton initialised (collection=%s)",
                self.collection_name,
            )
            return store, index

    # Kept for backward compatibility with backfill_pending() which uses
    # one fresh store per batch (overwrite=False but isolated from the
    # live singleton — batches don't pollute the read path).
    def _vector_store(self, overwrite: bool = False) -> MilvusVectorStore:
        if overwrite:
            # Hold the lock for the WHOLE recreate-then-invalidate
            # transaction. Earlier impl nulled out the cache, released
            # the lock, then ran the rebuild — that opened a race where
            # a concurrent reader could acquire the lock between steps
            # and cache a fresh-but-doomed store against the
            # about-to-be-recreated collection. Holding the lock
            # serialises overwrite vs read-cold-start.
            with self._lock:
                fresh = self._build_fresh_store(overwrite=True)
                self._store = None
                self._index = None
            return fresh
        return self._build_fresh_store(overwrite=False)

    def _storage_context(self, vector_store: MilvusVectorStore) -> StorageContext:
        if PostgresDocumentStore is None:
            raise RuntimeError("PostgresDocumentStore is unavailable")
        docstore = PostgresDocumentStore.from_uri(uri=settings.DATABASE_URL)
        return StorageContext.from_defaults(docstore=docstore, vector_store=vector_store)

    def build_memory_text(self, memory: MemoryItem) -> str:
        return (
            f"Type: {memory.type}\n"
            f"Description: {memory.description}\n"
            f"Content: {memory.content}"
        )

    def memory_metadata(self, memory: MemoryItem) -> dict[str, Any]:
        updated_at = memory.updated_at or memory.created_at
        return {
            "memory_id": memory.id,
            "user_id": memory.user_id,
            "type": memory.type,
            "scope": memory.scope or "user",
            "normalized_key": memory.normalized_key,
            "importance": float(memory.importance or 0.0),
            "updated_at": updated_at.isoformat() if updated_at else "",
        }

    def upsert_memory(self, memory: MemoryItem, db: Session | None = None) -> bool:
        # Reuse the singleton store; storage_context (PostgresDocumentStore)
        # is still per-call — that's a separate optimisation tracked in
        # the BM25 epoch work.
        vector_store, _ = self._get_store_and_index()
        storage_context = self._storage_context(vector_store)
        document = Document(
            text=self.build_memory_text(memory),
            metadata=self.memory_metadata(memory),
        )
        VectorStoreIndex.from_documents(
            [document],
            storage_context=storage_context,
            store_nodes_override=True,
            show_progress=False,
        )
        memory.embedding_status = "ready"
        memory.embedding_model = settings.EMBEDDING_MODEL
        memory.embedded_at = datetime.utcnow()
        if db is not None:
            db.flush()
        return True

    def backfill_pending(self, batch_size: int = 50) -> int:
        """Batch-embed all pending memory items into Milvus.

        Was a per-row N+1: ``VectorStoreIndex.from_documents([doc])`` for every
        single memory, re-instantiating MilvusVectorStore + StorageContext
        each iteration. Now we build the StorageContext once, then group
        documents into ``batch_size`` chunks and embed each chunk in a single
        call. ~10-50x faster on startup with 100+ pending memories.
        """
        db = SessionLocal()
        try:
            rows = (
                db.query(MemoryItem)
                .filter(
                    (MemoryItem.embedding_status != "ready")
                    | (MemoryItem.embedding_model != settings.EMBEDDING_MODEL)
                    | (MemoryItem.embedding_model.is_(None))
                )
                .all()
            )
            if not rows:
                logger.info("Memory embedding backfill: nothing pending")
                return 0

            # Reuse the singleton store; storage context is per-batch
            # (PostgresDocumentStore is the expensive part — see TODO).
            vector_store, _ = self._get_store_and_index()
            storage_context = self._storage_context(vector_store)
            now = datetime.utcnow()
            embedded = 0

            for start in range(0, len(rows), batch_size):
                chunk = rows[start:start + batch_size]
                documents = [
                    Document(
                        text=self.build_memory_text(m),
                        metadata=self.memory_metadata(m),
                    )
                    for m in chunk
                ]
                try:
                    VectorStoreIndex.from_documents(
                        documents,
                        storage_context=storage_context,
                        store_nodes_override=True,
                        show_progress=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    # Whole batch failed — mark the items and continue with
                    # the next batch instead of aborting the entire startup.
                    logger.warning(
                        "Memory embedding batch [%d:%d] failed: %s",
                        start, start + len(chunk), exc,
                    )
                    for m in chunk:
                        m.embedding_status = "failed"
                    continue

                for m in chunk:
                    m.embedding_status = "ready"
                    m.embedding_model = settings.EMBEDDING_MODEL
                    m.embedded_at = now
                    embedded += 1
                # Flush incrementally so a later crash doesn't redo the work.
                db.flush()

            db.commit()
            logger.info(
                "Memory embedding backfill complete: %d/%d items in %d batches",
                embedded, len(rows), (len(rows) + batch_size - 1) // batch_size,
            )
            return embedded
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def retrieve_vector(
        self,
        *,
        user_id: str,
        query: str,
        memory_types: list[str],
        top_k: int,
    ) -> list[RetrievalChunk]:
        # Reuse the cached store + index — avoids 30-200ms gRPC dial +
        # schema fetch per query.
        _, index = self._get_store_and_index()
        filters = MetadataFilters(
            filters=[
                MetadataFilter(key="user_id", value=user_id, operator=FilterOperator.EQ),
            ],
            condition="and",
        )
        retriever = VectorIndexRetriever(
            index=index,
            similarity_top_k=top_k,
            filters=filters,
        )
        nodes = await retriever.aretrieve(query)
        chunks: list[RetrievalChunk] = []
        allowed_types = set(memory_types)
        for node in nodes:
            metadata = dict(node.node.metadata or {})
            if metadata.get("user_id") != user_id:
                continue
            if allowed_types and metadata.get("type") not in allowed_types:
                continue
            memory_id = str(metadata.get("memory_id") or "")
            if not memory_id:
                continue
            chunks.append(
                RetrievalChunk(
                    id=memory_id,
                    text=node.node.get_content(),
                    metadata=metadata,
                    vector_score=float(node.score or 0.0),
                )
            )
        return chunks


memory_vector_service = MemoryVectorService()


__all__ = ["MemoryVectorService", "memory_vector_service", "EMBEDDING_DIM"]
