"""Vector embedding and retrieval service for ResumeSection.

Uses the same Milvus infrastructure as MemoryVectorService but in a
separate collection (RESUME_MILVUS_COLLECTION).

Workflow:
  1. upsert_section() — embed a single ResumeSection into Milvus
  2. backfill_pending() — batch-embed all sections with status != "ready"
  3. retrieve() — vector search for resume sections relevant to a query

Singleton — see ``app.services.memory.vector_service`` for the rationale;
same double-checked-lock pattern applies here.
"""

import logging
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

from app.core.config import settings
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.resume_section import ResumeSection
from app.rag.hybrid import RetrievalChunk

logger = logging.getLogger(__name__)

# Use the same embedding dimension as the project's embedding model.
EMBEDDING_DIM = settings.EMBEDDING_DIM
RESUME_COLLECTION = settings.RESUME_MILVUS_COLLECTION


class ResumeVectorService:
    def __init__(self):
        self.collection_name = RESUME_COLLECTION
        # Cached singletons — lazily initialised on first use.
        self._store: MilvusVectorStore | None = None
        self._index: VectorStoreIndex | None = None
        self._lock = Lock()

    # ── Milvus helpers ────────────────────────────────────────────────

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
        """Return cached (store, index) — double-checked lock pattern."""
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
                "ResumeVectorService singleton initialised (collection=%s)",
                self.collection_name,
            )
            return store, index

    # Back-compat shim — kept because tests may patch it. New code should
    # use _get_store_and_index() for reads / _build_fresh_store(True) for
    # collection recreation.
    def _vector_store(self, overwrite: bool = False) -> MilvusVectorStore:
        if overwrite:
            # Hold the lock through the full rebuild → invalidate
            # transaction. See vector_service.py for the race window
            # this closes.
            with self._lock:
                fresh = self._build_fresh_store(overwrite=True)
                self._store = None
                self._index = None
            return fresh
        return self._build_fresh_store(overwrite=False)

    def _storage_context(self, vector_store: MilvusVectorStore) -> StorageContext:
        # Milvus-only: the resume-section text fact source is Postgres
        # ``resume_sections``; Milvus holds the retrieval index. The old
        # LlamaIndex PostgresDocumentStore cache path is removed (CLEANUP).
        return StorageContext.from_defaults(vector_store=vector_store)

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
        vector_store, _ = self._get_store_and_index()
        storage_context = self._storage_context(vector_store)
        document = Document(
            text=self.build_section_text(section),
            metadata=self.section_metadata(section),
        )
        VectorStoreIndex.from_documents(
            [document],
            storage_context=storage_context,
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
        # The resume Milvus scope key is the stable users.id pk; resolve the
        # request principal once. Unresolved principal -> no accessible sections.
        with SessionLocal() as _db:
            user_pk = resolve_user_pk(_db, user_id)
        if user_pk is None:
            return []
        _, index = self._get_store_and_index()
        filters = MetadataFilters(
            filters=[
                MetadataFilter(
                    key="user_id", value=user_pk, operator=FilterOperator.EQ,
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
            if metadata.get("user_id") != user_pk:
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
