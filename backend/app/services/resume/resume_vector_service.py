"""Resume-section vector index — Milvus 2.6 native dense + server-side BM25
hybrid via the shared ``app.rag.milvus_hybrid`` abstraction.

Postgres ``resume_sections`` is the fact source (and ``resumes.raw_text_snapshot``
the upstream full-resume snapshot); Milvus holds an index-only copy of each
section, scoped by the stable ``users.id`` pk. No LlamaIndex vector store, no
docstore — the section content is embedded directly and BM25 is computed
server-side by Milvus from the ``text`` field.

Workflow:
  1. ``upsert_section`` — delete-then-insert one section's hybrid row.
  2. ``delete_by_resume`` — keep the index in sync when a section set is
     re-parsed (old resume rows dropped before the fresh ones are re-indexed).
  3. ``backfill_pending`` — (re)index sections whose ``embedding_status != ready``.
  4. ``retrieve`` — dense + BM25 hybrid search, pk-scoped.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from llama_index.core import Settings
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.resume_section import ResumeSection
from app.rag import milvus_hybrid
from app.rag.hybrid import RetrievalChunk

logger = logging.getLogger(__name__)

_COLL = milvus_hybrid.RESUME


class ResumeVectorService:
    """Hybrid index for resume sections (one Milvus row per ResumeSection)."""

    @staticmethod
    def build_section_text(section: ResumeSection) -> str:
        return (
            f"Section: {section.section_type}\n"
            f"Title: {section.title}\n"
            f"Content: {section.content}"
        )

    def _row(self, section: ResumeSection) -> dict[str, Any]:
        text = self.build_section_text(section)
        return {
            "id": section.id,
            "user_id": int(section.user_id),
            "resume_id": section.resume_id or "",
            "section_type": section.section_type or "",
            "title": section.title or "",
            "text": text,
            "dense": Settings.embed_model.get_text_embedding(text),
        }

    # ── Upsert / delete (index sync) ──────────────────────────────────────

    def upsert_section(self, section: ResumeSection, db: Session | None = None) -> bool:
        """Embed + (re)index a single section. Idempotent: delete-then-insert by
        the section id so a re-parse can't leave a stale copy."""
        milvus_hybrid.delete_by_field(_COLL, "id", section.id)
        milvus_hybrid.insert(_COLL, [self._row(section)])
        section.embedding_status = "ready"
        if db is not None:
            db.flush()
        return True

    def delete_by_resume(self, resume_id: str) -> None:
        """Drop every section index row for one resume (re-parse / resume delete)."""
        milvus_hybrid.delete_by_field(_COLL, "resume_id", resume_id)

    def backfill_pending(self) -> int:
        """Batch (re)index all sections not yet marked ``ready``."""
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
                        "Resume section embedding failed for %s: %s", section.id, exc,
                    )
            db.commit()
            logger.info("Resume section hybrid backfill complete: %s items", count)
            return count
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ── Retrieval ─────────────────────────────────────────────────────────

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        section_types: list[str] | None = None,
        top_k: int = 5,
    ) -> list[RetrievalChunk]:
        """Dense + BM25 hybrid search over the user's resume sections.

        ``user_id`` is the username principal; it's resolved to the stable
        users.id pk (the Milvus scope key). Unresolved principal -> []."""
        with SessionLocal() as db:
            user_pk = resolve_user_pk(db, user_id)
        if user_pk is None:
            return []

        def _search() -> list[dict[str, Any]]:
            query_dense = Settings.embed_model.get_query_embedding(query)
            return milvus_hybrid.hybrid_search(
                _COLL, query_text=query, query_dense=query_dense,
                user_pk=user_pk, top_k=top_k,
            )

        hits = await asyncio.to_thread(_search)
        allowed = set(section_types) if section_types else None
        chunks: list[RetrievalChunk] = []
        for h in hits:
            if h.get("user_id") != user_pk:  # defence-in-depth on the server filter
                continue
            if allowed and h.get("section_type") not in allowed:
                continue
            chunks.append(RetrievalChunk(
                id=str(h["id"]),
                text=h["text"],
                metadata={
                    "section_id": h["id"],
                    "user_id": h["user_id"],
                    "resume_id": h.get("resume_id"),
                    "section_type": h.get("section_type"),
                    "title": h.get("title"),
                },
                vector_score=float(h["score"]),
            ))
        return chunks


resume_vector_service = ResumeVectorService()
