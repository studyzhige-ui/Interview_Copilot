"""Memory extraction service — distills durable facts from new conversation turns."""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.memory import MemoryItem
from app.rag.embeddings import agent_fast_llm
from app.services.memory._json_payload import _extract_json_payload, _normalize_key
from app.services.memory.vector_service import memory_vector_service

logger = logging.getLogger(__name__)


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


memory_extraction_service = MemoryExtractionService()


__all__ = ["MemoryExtractionService", "memory_extraction_service"]
