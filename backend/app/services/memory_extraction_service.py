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
from app.services.interview_state_service import interview_state_service
from app.services.memory_vector_service import memory_vector_service
from app.services.state_utils import (
    default_interview_state_payload,
    default_working_state_payload,
    dump_state_blob,
    parse_state_blob,
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


class CompactionService:
    COMPACTION_THRESHOLD_TOKENS = 5000
    KEEP_LAST_MESSAGES = 6
    WORKING_STATE_MAX_TOKENS = 1000
    WORKING_STATE_PROMPT = """You maintain structured working state for a multi-turn interview copilot.

Return a JSON object with exactly these keys:
- goal
- current_phase
- covered_topics
- pending_topics
- candidate_claims_to_verify
- observed_gaps
- next_best_question
- constraints
- summary

Rules:
- Keep only current-session working state.
- Do not store generic technical knowledge.
- Do not copy long transcript text verbatim.
- Lists must stay short and concrete.
- summary must be under 120 Chinese characters or 220 ASCII chars.

Previous working state:
{old_working_state}

Conversation to compact:
{new_conversation}
"""

    async def compact_if_needed(self, session_id: str) -> bool:
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            return False

        recent = transcript_service.get_recent_turns(
            session_id=session_id,
            max_turns=100,
            after_seq=meta["compaction_cursor"],
        )
        if not recent:
            return False

        working_state = parse_state_blob(
            meta["working_state"],
            default_working_state_payload,
        )
        total_tokens = (
            count_tokens(dump_state_blob(working_state))
            + sum(count_tokens(item["content"]) for item in recent)
        )
        if total_tokens <= self.COMPACTION_THRESHOLD_TOKENS:
            return False

        compress_messages = recent[:-self.KEEP_LAST_MESSAGES]
        if not compress_messages:
            return False

        prompt = self.WORKING_STATE_PROMPT.format(
            old_working_state=json.dumps(working_state, ensure_ascii=False, indent=2),
            new_conversation="\n".join(
                f"{item['role']}: {item['content']}" for item in compress_messages
            ),
        )
        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            payload = parse_state_blob(
                json.dumps(_extract_json_payload(str(response.text))),
                default_working_state_payload,
            )
            serialized = dump_state_blob(payload)
            if count_tokens(serialized) > self.WORKING_STATE_MAX_TOKENS:
                payload["summary"] = str(payload.get("summary") or "")[:220]
                serialized = dump_state_blob(payload)
            transcript_service.update_session_fields(
                session_id,
                working_state=serialized,
                compaction_cursor=compress_messages[-1]["seq"],
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Compaction failed for session %s: %s", session_id, exc)
            return False


class InterviewStateUpdateService:
    INTERVIEW_STATE_PROMPT = """You maintain structured interview state for one session.

Return a JSON object with exactly these keys:
- goal
- phase
- covered_topics
- pending_topics
- observed_gaps
- evidence
- candidate_claims
- next_question
- constraints

Rules:
- observed_gaps should only contain evidence-backed weaknesses or uncertainty.
- evidence must be a short list of objects with topic, observation, and confidence when possible.
- Keep the state concise and current-session only.

Previous interview state:
{old_state}

New conversation:
{conversation}
"""

    async def update_from_messages(
        self,
        session_id: str,
        user_id: str,
        new_messages: list[dict],
    ) -> dict:
        current_state = interview_state_service.get_state(session_id, user_id)
        if not new_messages:
            return current_state

        prompt = self.INTERVIEW_STATE_PROMPT.format(
            old_state=json.dumps(current_state, ensure_ascii=False, indent=2),
            conversation="\n".join(
                f"{item['role']}: {item['content']}" for item in new_messages
            ),
        )
        try:
            response = await agent_fast_llm.acomplete(
                prompt,
                response_format={"type": "json_object"},
            )
            payload = parse_state_blob(
                json.dumps(_extract_json_payload(str(response.text))),
                default_interview_state_payload,
            )
            interview_state_service.update_state(session_id, user_id, payload)
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Interview state update failed for session %s: %s",
                session_id,
                exc,
            )
            return current_state


class MemoryExtractionService:
    MIN_CONFIDENCE = 0.65
    EXTRACTION_PROMPT = """Review the conversation and extract only cross-session durable memories.

Allowed memory types:
- user_profile
- interaction_preference
- feedback_rule
- project_reference

Never extract:
- temporary session progress
- short-lived weaknesses or scoring
- technical knowledge already derivable from code or docs
- anything you are not confident should survive across sessions

Return a JSON array. Each item must contain:
- type
- description
- normalized_key
- content
- confidence

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


class MemoryRetrievalService:
    MAX_RECALL_ITEMS = 3
    PREFILTER_LIMIT = 12
    STALENESS_THRESHOLD_DAYS = 2
    SELECT_PROMPT = """Choose the memory ids most relevant to the current query.

Return a JSON array of ids. Choose at most {max_items}. If none matter, return [].

Memory catalog:
{memory_catalog}

Query:
{query}
"""

    def __init__(
        self,
        hybrid_retriever: HybridRetriever | None = None,
    ):
        self.hybrid_retriever = hybrid_retriever or HybridRetriever()

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


class PostTurnMaintenanceService:
    def __init__(
        self,
        compaction: CompactionService,
        interview_updates: InterviewStateUpdateService,
        memory_extraction: MemoryExtractionService,
    ):
        self.compaction = compaction
        self.interview_updates = interview_updates
        self.memory_extraction = memory_extraction
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
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

        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            return

        pending_messages = transcript_service.get_recent_turns(
            session_id=session_id,
            max_turns=100,
            after_seq=meta["memory_cursor"],
        )
        if not pending_messages:
            return

        await self.interview_updates.update_from_messages(
            session_id=session_id,
            user_id=user_id,
            new_messages=pending_messages,
        )
        extracted = []
        if allow_memory_write:
            extracted = await self.memory_extraction.extract_and_merge(
                session_id=session_id,
                user_id=user_id,
                new_messages=pending_messages,
            )
        if extracted is not None:
            transcript_service.update_session_fields(
                session_id,
                memory_cursor=max(item["seq"] for item in pending_messages),
            )


compaction_service = CompactionService()
interview_state_update_service = InterviewStateUpdateService()
memory_extraction_service = MemoryExtractionService()
memory_retrieval_service = MemoryRetrievalService()
post_turn_maintenance_service = PostTurnMaintenanceService(
    compaction=compaction_service,
    interview_updates=interview_state_update_service,
    memory_extraction=memory_extraction_service,
)
