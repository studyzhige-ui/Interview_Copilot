import json
import logging
import re
import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.memory import MemoryItem
from app.rag.embeddings import agent_fast_llm
from app.rag.hybrid import HybridRetriever, RetrievalChunk, lexical_overlap
from app.services.context_service import count_tokens
from app.services.memory_vector_service import memory_vector_service
from app.services.state_utils import (
    dump_session_state,
    parse_session_state,
)
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)


def _extract_json_payload(raw_text: str) -> Any:
    raw_text = str(raw_text or "").strip()
    if not raw_text:
        raise json.JSONDecodeError("empty", raw_text, 0)

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", raw_text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(1))


def _normalize_key(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return normalized[:100] or "memory"


# ── Session State Compaction ─────────────────────────────────────────────

class CompactionService:
    """Compresses old conversation turns into a session_state summary.

    Unlike the old design, this does NOT maintain a structured working_state
    with rigid keys. Instead it produces a free-form conversation summary
    that the LLM can reference for context continuity.

    Triggers every COMPACT_EVERY_N_TURNS turns (default 20).
    """

    COMPACT_EVERY_N_TURNS = 20
    SESSION_STATE_MAX_TOKENS = 1500

    COMPACTION_PROMPT = """你是一个对话摘要助手。请将下面的对话历史压缩成一段简洁的摘要。

规则：
- 保留对话中讨论过的核心主题和关键结论
- 不要复制原文，用自己的话概括
- 摘要控制在 300 字以内
- 如果已有旧摘要，将新对话内容合并进去
- 输出纯 JSON 格式：{{"summary": "..."}}

旧摘要：
{old_summary}

新对话：
{new_conversation}
"""

    async def compact_if_needed(self, session_id: str) -> bool:
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            return False

        turn_count = meta["turn_count"]
        if turn_count < self.COMPACT_EVERY_N_TURNS:
            return False
        if turn_count % self.COMPACT_EVERY_N_TURNS != 0:
            return False

        recent = transcript_service.get_recent_turns(
            session_id=session_id,
            max_turns=100,
            after_seq=meta["compaction_cursor"],
        )
        if not recent:
            return False

        session_state = parse_session_state(
            meta["session_state"],
            meta.get("session_type", "general"),
        )
        old_summary = session_state.get("summary", "")

        prompt = self.COMPACTION_PROMPT.format(
            old_summary=old_summary or "(无)",
            new_conversation="\n".join(
                f"{item['role']}: {item['content']}" for item in recent
            ),
        )
        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            payload = _extract_json_payload(str(response.text))
            new_summary = str(payload.get("summary", "")).strip()

            if count_tokens(new_summary) > self.SESSION_STATE_MAX_TOKENS:
                new_summary = new_summary[:600]

            session_state["summary"] = new_summary
            transcript_service.update_session_fields(
                session_id,
                session_state=dump_session_state(session_state),
                compaction_cursor=recent[-1]["seq"],
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Compaction failed for session %s: %s", session_id, exc)
            return False


# ── Memory Extraction ─────────────────────────────────────────────────────

class MemoryExtractionService:
    """Extracts two types of memories from conversation turns.

    - user_profile:    durable personal facts (name, tech stack, career goals)
    - interview_fact:  specific interview discussion points and learnings,
                       enriched during debrief conversations as the user
                       reviews and corrects their understanding.
    """

    MIN_CONFIDENCE = 0.65
    EXTRACTION_PROMPT = """Review the conversation and extract durable memories.

Allowed memory types:

1. user_profile — personal facts about the user
   Examples: name, target role, tech stack, years of experience, career goals.
   normalized_key format: snake_case identifier (e.g. "target_role", "tech_stack")

2. interview_fact — specific interview discussion points and learnings
   These capture WHAT was discussed in an interview and WHAT the user learned.
   Content format: "[date if known] [interview title]: [topic], [what happened / was learned], [score if available]"
   normalized_key format: "ivf_[topic_snake_case]" (e.g. "ivf_redis_persistence", "ivf_tcp_handshake")
   Rules for interview_fact:
   - Extract when the conversation discusses a specific interview question or technical topic from an interview
   - Include both what was discussed AND the conclusion or learning
   - If the user corrected a misunderstanding during review, note the updated understanding
   - If a score or evaluation is mentioned, include it

Never extract:
- Generic technical knowledge unrelated to a specific interview
- Temporary session state or UI preferences

Return a JSON array. Each item:
- type: "user_profile" or "interview_fact"
- description: short label (max 50 chars)
- normalized_key: snake_case identifier for dedup
- content: the fact (1-2 sentences)
- confidence: 0.0-1.0

If nothing qualifies, return [].

Conversation:
{conversation}
"""

    async def extract_and_merge(
        self,
        session_id: str,
        user_id: str,
        new_messages: list[dict],
    ) -> list[dict] | None:
        if not new_messages:
            return []

        conversation = "\n".join(
            f"{item['role']}: {item['content']}" for item in new_messages
        )
        try:
            response = await agent_fast_llm.acomplete(
                self.EXTRACTION_PROMPT.format(conversation=conversation),
            )
            raw_payload = _extract_json_payload(str(response.text))
            if isinstance(raw_payload, dict):
                candidates = raw_payload.get("items", raw_payload.get("memories", []))
            else:
                candidates = raw_payload
            if not isinstance(candidates, list):
                candidates = []
        except Exception as exc:  # noqa: BLE001
            logger.error("Memory extraction failed for session %s: %s", session_id, exc)
            return None

        max_seq = max((item.get("seq", 0) for item in new_messages), default=0)
        persisted: list[dict] = []
        db: Session = SessionLocal()
        try:
            for candidate in candidates:
                mem_type = str(candidate.get("type") or "").strip()
                if mem_type not in MemoryItem.VALID_TYPES:
                    continue

                confidence = float(candidate.get("confidence") or 0.0)
                if confidence < self.MIN_CONFIDENCE:
                    continue

                description = str(candidate.get("description") or "").strip()[:200]
                content = str(candidate.get("content") or "").strip()
                normalized_key = _normalize_key(
                    str(candidate.get("normalized_key") or description)
                )
                if not description or not content:
                    continue
                if len(content.encode("utf-8")) > MemoryItem.MAX_CONTENT_BYTES:
                    content = content[: MemoryItem.MAX_CONTENT_BYTES // 3]

                existing = (
                    db.query(MemoryItem)
                    .filter(
                        MemoryItem.user_id == user_id,
                        MemoryItem.type == mem_type,
                        MemoryItem.normalized_key == normalized_key,
                    )
                    .first()
                )
                if existing is None:
                    existing = MemoryItem(
                        user_id=user_id,
                        type=mem_type,
                        scope="user",
                        description=description,
                        normalized_key=normalized_key,
                        content=content,
                        confidence=confidence,
                        importance=confidence,
                        embedding_status="pending",
                        source_session_id=session_id,
                        last_evidence_seq=max_seq,
                    )
                    db.add(existing)
                else:
                    existing.description = description
                    existing.content = content
                    existing.confidence = confidence
                    existing.importance = max(existing.importance or 0.5, confidence)
                    existing.embedding_status = "pending"
                    existing.source_session_id = session_id
                    existing.last_evidence_seq = max_seq
                    existing.updated_at = datetime.utcnow()

                db.flush()
                try:
                    memory_vector_service.upsert_memory(existing, db=db)
                except Exception as exc:  # noqa: BLE001
                    existing.embedding_status = "failed"
                    logger.warning("Memory vector upsert failed for %s: %s", existing.id, exc)

                persisted.append(
                    {
                        "type": mem_type,
                        "description": description,
                        "normalized_key": normalized_key,
                        "confidence": confidence,
                    }
                )

            db.commit()
            return persisted
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Memory merge failed for session %s: %s", session_id, exc)
            return None
        finally:
            db.close()


# ── Memory Retrieval ─────────────────────────────────────────────────────

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
        """Load all user_profile memories directly from DB (no vector search).

        user_profile items are always injected into the system prompt,
        similar to hermes USER.md — small, always present.
        """
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(MemoryItem)
                .filter(
                    MemoryItem.user_id == user_id,
                    MemoryItem.type == "user_profile",
                )
                .order_by(MemoryItem.updated_at.desc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "type": row.type,
                    "description": row.description,
                    "content": row.content.strip()[:500],
                    "normalized_key": row.normalized_key,
                }
                for row in rows
            ]
        finally:
            db.close()

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


# ── Post-Turn Maintenance ────────────────────────────────────────────────

class PostTurnMaintenanceService:
    """Runs after each conversation turn as a background task.

    Responsibilities (in order):
    1. Compact session_state if turn threshold is reached
    2. Extract user_profile memories from new messages
    """

    def __init__(
        self,
        compaction: CompactionService,
        memory_extraction: MemoryExtractionService,
    ):
        self.compaction = compaction
        self.memory_extraction = memory_extraction
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_maxsize = 128

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            if len(self._locks) >= self._locks_maxsize:
                oldest_key = next(iter(self._locks))
                del self._locks[oldest_key]
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def run(
        self,
        session_id: str,
        user_id: str,
        *,
        allow_memory_write: bool = True,
    ) -> None:
        async with self._lock_for(session_id):
            await self._run_locked(
                session_id=session_id,
                user_id=user_id,
                allow_memory_write=allow_memory_write,
            )

    async def _run_locked(
        self,
        *,
        session_id: str,
        user_id: str,
        allow_memory_write: bool,
    ) -> None:
        await self.compaction.compact_if_needed(session_id)

        if not allow_memory_write:
            return

        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            return

        # Use compaction_cursor as the memory extraction watermark too
        pending_messages = transcript_service.get_recent_turns(
            session_id=session_id,
            max_turns=20,
            after_seq=meta["compaction_cursor"],
        )
        if not pending_messages:
            return

        await self.memory_extraction.extract_and_merge(
            session_id=session_id,
            user_id=user_id,
            new_messages=pending_messages,
        )


compaction_service = CompactionService()
memory_extraction_service = MemoryExtractionService()
memory_retrieval_service = MemoryRetrievalService()
post_turn_maintenance_service = PostTurnMaintenanceService(
    compaction=compaction_service,
    memory_extraction=memory_extraction_service,
)
