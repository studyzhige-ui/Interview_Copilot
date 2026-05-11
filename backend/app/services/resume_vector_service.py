"""Vector embedding and retrieval service for ResumeSection.

Uses the same Milvus infrastructure as MemoryVectorService but in a
separate collection (RESUME_MILVUS_COLLECTION).

Workflow:
  1. upsert_section() — embed a single ResumeSection into Milvus
  2. backfill_pending() — batch-embed all sections with status != "ready"
  3. retrieve() — vector search for resume sections relevant to a query
"""

import logging
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
except ModuleNotFoundError:  # pragma: no cover
    PostgresDocumentStore = None

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.resume_section import ResumeSection
from app.rag.hybrid import RetrievalChunk

logger = logging.getLogger(__name__)

# Use the same embedding dimension as the project's embedding model.
EMBEDDING_DIM = 512
RESUME_COLLECTION = settings.RESUME_MILVUS_COLLECTION


class ResumeVectorService:
    def __init__(self):
        self.collection_name = RESUME_COLLECTION

    # ── Milvus helpers ────────────────────────────────────────────────

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

    # ── Document building ─────────────────────────────────────────────

    @staticmethod
    def build_section_text(section: ResumeSection) -> str:
        return (
            f"Section: {section.section_type}\n"
            f"Title: {section.title}\n"
            f"Content: {section.content}"
        )

    @staticmethod
    def section_metadata(section: ResumeSection) -> dict[str, Any]:
        return {
            "section_id": section.id,
            "user_id": section.user_id,
            "upload_id": section.upload_id,
            "section_type": section.section_type,
            "title": section.title,
        }

    # ── Upsert ────────────────────────────────────────────────────────

    def upsert_section(self, section: ResumeSection, db: Session | None = None) -> bool:
        """Embed a single ResumeSection into the vector store."""
        vector_store = self._vector_store(overwrite=False)
        storage_context = self._storage_context(vector_store)
        document = Document(
            text=self.build_section_text(section),
            metadata=self.section_metadata(section),
        )
        VectorStoreIndex.from_documents(
            [document],
            storage_context=storage_context,
            store_nodes_override=True,
            show_progress=False,
        )
        section.embedding_status = "ready"
        if db is not None:
            db.flush()
        return True

    def backfill_pending(self) -> int:
        """Batch-embed all ResumeSection rows that are not yet vectorized."""
        db = SessionLocal()
        count = 0
        try:
            rows = (
                db.query(ResumeSection)
                .filter(ResumeSection.embedding_status != "ready")
                .all()
            )
            for section in rows:
                try:
                    self.upsert_section(section, db=db)
                    count += 1
                except Exception as exc:  # noqa: BLE001
                    section.embedding_status = "failed"
                    logger.warning(
                        "Resume section embedding failed for %s: %s",
                        section.id,
                        exc,
                    )
            db.commit()
            logger.info("Resume section embedding backfill complete: %s items", count)
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ── Retrieval ─────────────────────────────────────────────────────

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        section_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[RetrievalChunk]:
        """Vector search for resume sections relevant to a query."""
        vector_store = self._vector_store(overwrite=False)
        index = VectorStoreIndex.from_vector_store(vector_store)
        filters = MetadataFilters(
            filters=[
                MetadataFilter(
                    key="user_id", value=user_id, operator=FilterOperator.EQ,
                ),
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
        allowed_types = set(section_types) if section_types else None
        for node in nodes:
            metadata = dict(node.node.metadata or {})
            if metadata.get("user_id") != user_id:
                continue
            if allowed_types and metadata.get("section_type") not in allowed_types:
                continue
            section_id = str(metadata.get("section_id") or "")
            if not section_id:
                continue
            chunks.append(
                RetrievalChunk(
                    id=section_id,
                    text=node.node.get_content(),
                    metadata=metadata,
                    vector_score=float(node.score or 0.0),
                )
            )
        return chunks


resume_vector_service = ResumeVectorService()
