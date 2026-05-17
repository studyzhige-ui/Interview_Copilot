"""Memory retrieval service — hybrid (vector + lexical) recall for the QA pipeline."""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.memory import MemoryItem
from app.rag.hybrid import HybridRetriever, RetrievalChunk, lexical_overlap
from app.services.memory.vector_service import memory_vector_service

logger = logging.getLogger(__name__)


class MemoryRetrievalService:
    MAX_RECALL_ITEMS = 3
    PREFILTER_LIMIT = 12
    STALENESS_THRESHOLD_DAYS = 2

    def __init__(
        self,
        hybrid_retriever: HybridRetriever | None = None,
    ):
        self.hybrid_retriever = hybrid_retriever or HybridRetriever()

    def load_user_profile(self, user_id: str) -> list[dict]:
        """Return the user's profile as a list of fact entries.

        Source of truth (post-0019): ``users.user_profile_doc`` — a single
        markdown blob with one fact per line. The legacy multi-row
        ``memory_items WHERE type='user_profile'`` storage was retired
        because rule-based normalized_key dedup couldn't catch semantic
        duplicates (e.g. "User's name: 卷卷" vs "用户名字: 卷卷"). Each
        non-empty line in the doc becomes one dict so existing prompt
        rendering code (which iterates ``profile``) keeps working.
        """
        from app.services.memory.user_profile_doc_service import load_as_lines

        lines = load_as_lines(user_id)
        return [
            {
                "id": f"profile_line_{idx}",
                "type": "user_profile",
                # description + content both hold the same line text with
                # the leading "- " bullet stripped; renderers that only
                # look at one of them still produce sensible output.
                "description": line.lstrip("- ").strip(),
                "content": line.lstrip("- ").strip(),
                "normalized_key": "",
            }
            for idx, line in enumerate(lines)
        ]

    async def recall_relevant(
        self,
        user_id: str,
        query: str,
        max_items: int | None = None,
        memory_types: list[str] | None = None,
    ) -> list[dict]:
        max_items = max_items or self.MAX_RECALL_ITEMS
        memory_types = [
            item
            for item in (memory_types or list(MemoryItem.VALID_TYPES))
            if item in MemoryItem.VALID_TYPES
        ]

        async def vector_fetch() -> list[RetrievalChunk]:
            return await memory_vector_service.retrieve_vector(
                user_id=user_id,
                query=query,
                memory_types=memory_types,
                top_k=max(max_items, 1) * 3,
            )

        async def lexical_fetch() -> list[RetrievalChunk]:
            return self._lexical_candidates(user_id, query, memory_types)

        result = await self.hybrid_retriever.retrieve(
            query=query,
            vector_fetch=vector_fetch,
            lexical_fetch=lexical_fetch,
            final_top_k=max(settings.MEMORY_FINAL_TOP_K, max_items),
        )
        selected_ids = [chunk.id for chunk in result.chunks[:max_items]]
        if selected_ids:
            return self._load_and_mark_selected(user_id, selected_ids, max_items)
        return []

    def _lexical_candidates(
        self,
        user_id: str,
        query: str,
        memory_types: list[str],
    ) -> list[RetrievalChunk]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(MemoryItem)
                .filter(
                    MemoryItem.user_id == user_id,
                    MemoryItem.type.in_(memory_types),
                )
                .order_by(
                    MemoryItem.importance.desc(),
                    MemoryItem.recall_count.desc(),
                    MemoryItem.updated_at.desc(),
                )
                .limit(max(self.PREFILTER_LIMIT, settings.MEMORY_LEXICAL_TOP_K))
                .all()
            )
        finally:
            db.close()

        chunks: list[RetrievalChunk] = []
        for row in rows:
            text = f"{row.description}\n{row.content}"
            score = lexical_overlap(query, text)
            if score <= 0 and row.recall_count <= 0:
                continue
            chunks.append(
                RetrievalChunk(
                    id=row.id,
                    text=text,
                    lexical_score=score,
                    metadata={
                        "type": row.type,
                        "scope": row.scope or "user",
                        "normalized_key": row.normalized_key,
                        "importance": float(row.importance or 0.0),
                        "updated_at": row.updated_at,
                        "created_at": row.created_at,
                    },
                )
            )
        return chunks[: settings.MEMORY_LEXICAL_TOP_K]

    def _load_and_mark_selected(
        self,
        user_id: str,
        selected_ids: list[str],
        max_items: int,
    ) -> list[dict]:
        db = SessionLocal()
        try:
            rows = (
                db.query(MemoryItem)
                .filter(
                    MemoryItem.user_id == user_id,
                    MemoryItem.id.in_(selected_ids),
                )
                .all()
            )
            by_id = {memory.id: memory for memory in rows}
            selected = [by_id[item_id] for item_id in selected_ids if item_id in by_id]
            now = datetime.utcnow()
            for memory in selected:
                memory.recall_count = (memory.recall_count or 0) + 1
                memory.last_accessed_at = now
            db.commit()
            return self._inject_memories(selected[:max_items])
        finally:
            db.close()

    def _inject_memories(self, memories: list[MemoryItem]) -> list[dict]:
        now = datetime.utcnow()
        injected: list[dict] = []
        for memory in memories[: self.MAX_RECALL_ITEMS]:
            content = memory.content.strip()
            if len(content) > 500:
                content = content[:500].rstrip() + "..."
            age = now - (memory.updated_at or memory.created_at)
            staleness_note = ""
            if age > timedelta(days=self.STALENESS_THRESHOLD_DAYS):
                staleness_note = f"{age.days} days old"
            injected.append(
                {
                    "id": memory.id,
                    "type": memory.type,
                    "description": memory.description,
                    "content": content,
                    "staleness_note": staleness_note,
                    "normalized_key": memory.normalized_key,
                    "recall_count": memory.recall_count or 0,
                }
            )
        return injected

    async def get_memory_index(self, user_id: str) -> list[dict]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(MemoryItem)
                .filter(MemoryItem.user_id == user_id)
                .order_by(MemoryItem.updated_at.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "type": row.type,
                    "scope": row.scope or "user",
                    "description": row.description,
                    "normalized_key": row.normalized_key,
                    "confidence": row.confidence or 0.0,
                    "importance": row.importance or 0.0,
                    "recall_count": row.recall_count or 0,
                    "last_evidence_seq": row.last_evidence_seq,
                    "embedding_status": row.embedding_status,
                    "embedded_at": row.embedded_at.isoformat() if row.embedded_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]
        finally:
            db.close()

    def delete_memory(self, memory_id: str, user_id: str) -> bool:
        db: Session = SessionLocal()
        try:
            row = (
                db.query(MemoryItem)
                .filter(MemoryItem.id == memory_id, MemoryItem.user_id == user_id)
                .first()
            )
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True
        finally:
            db.close()


memory_retrieval_service = MemoryRetrievalService()


__all__ = ["MemoryRetrievalService", "memory_retrieval_service"]
