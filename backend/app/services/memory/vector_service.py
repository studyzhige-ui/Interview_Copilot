"""Milvus-backed vector store for memory items (canonical location).

Was previously at ``app.services.memory_vector_service`` — moved here as
part of the memory subpackage consolidation.
"""

import logging
from datetime import datetime
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

    def _vector_store(self, overwrite: bool = False) -> MilvusVectorStore:
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
        vector_store = self._vector_store(overwrite=False)
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

            # One vector store + storage context for the whole batch.
            vector_store = self._vector_store(overwrite=False)
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
        vector_store = self._vector_store(overwrite=False)
        index = VectorStoreIndex.from_vector_store(vector_store)
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
