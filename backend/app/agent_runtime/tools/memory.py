"""Memory tools: recall_memory and save_memory.

recall_memory — Semantic search over user's long-term memory.
save_memory   — Write facts to user's memory (agent-initiated).
"""

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.agent_runtime.tool_registry import AgentToolContext, ToolEntry, registry

logger = logging.getLogger(__name__)


# ── recall_memory ────────────────────────────────────────────────────────

class RecallMemoryArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Semantic search query over user memories")
    memory_types: list[str] = Field(
        default=["user_profile", "interview_fact"],
        description="Types to search: 'user_profile', 'interview_fact'",
    )
    max_items: int = Field(default=5, ge=1, le=10, description="Max memories to return")


async def _recall_memory_handler(args: RecallMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    from app.services.memory.retrieval_service import memory_retrieval_service

    # Also load user profile (always available, like Hermes USER.md)
    profile_items = memory_retrieval_service.load_user_profile(ctx.user_id)

    # Semantic recall for interview facts
    relevant = await memory_retrieval_service.recall_relevant(
        user_id=ctx.user_id,
        query=args.query,
        max_items=args.max_items,
        memory_types=args.memory_types,
    )

    return {
        "user_profile": profile_items,
        "relevant_memories": relevant,
        "profile_count": len(profile_items),
        "relevant_count": len(relevant),
    }


# ── save_memory ──────────────────────────────────────────────────────────

class SaveMemoryArgs(BaseModel):
    memory_type: str = Field(
        ...,
        description="Type: 'user_profile' (durable personal fact) or 'interview_fact' (specific learning)",
    )
    description: str = Field(..., min_length=1, max_length=200, description="Short label for the memory")
    content: str = Field(..., min_length=1, max_length=2000, description="The fact to remember (1-2 sentences)")
    normalized_key: str = Field(default="", max_length=100, description="Snake_case identifier for dedup (optional)")


async def _save_memory_handler(args: SaveMemoryArgs, ctx: AgentToolContext) -> dict[str, Any]:
    import re

    from sqlalchemy.orm import Session as DBSession

    from app.db.database import SessionLocal
    from app.models.memory import MemoryItem
    from app.services.memory.vector_service import memory_vector_service

    _VALID_MEMORY_TYPES = {"user_profile", "interview_fact", "interaction_preference", "feedback_rule", "project_reference"}
    if args.memory_type not in _VALID_MEMORY_TYPES:
        return {"error": f"Invalid memory_type: {args.memory_type}", "valid_types": list(_VALID_MEMORY_TYPES)}

    normalized_key = args.normalized_key.strip()
    if not normalized_key:
        normalized_key = re.sub(r"[^a-z0-9]+", "_", args.description.lower()).strip("_")[:100] or "memory"

    db: DBSession = SessionLocal()
    try:
        existing = (
            db.query(MemoryItem)
            .filter(
                MemoryItem.user_id == ctx.user_id,
                MemoryItem.type == args.memory_type,
                MemoryItem.normalized_key == normalized_key,
            )
            .first()
        )

        if existing:
            existing.description = args.description
            existing.content = args.content
            existing.confidence = 0.9
            existing.importance = max(existing.importance or 0.5, 0.9)
            existing.embedding_status = "pending"
            existing.source_session_id = ctx.session_id
            existing.updated_at = datetime.utcnow()
            action = "updated"
        else:
            existing = MemoryItem(
                user_id=ctx.user_id,
                type=args.memory_type,
                scope="user",
                description=args.description,
                normalized_key=normalized_key,
                content=args.content,
                confidence=0.9,
                importance=0.9,
                embedding_status="pending",
                source_session_id=ctx.session_id,
            )
            db.add(existing)
            action = "created"

        db.flush()

        try:
            memory_vector_service.upsert_memory(existing, db=db)
        except Exception as exc:
            existing.embedding_status = "failed"
            logger.warning("Memory vector upsert failed: %s", exc)

        db.commit()

        return {
            "action": action,
            "memory_id": existing.id,
            "type": args.memory_type,
            "description": args.description,
            "normalized_key": normalized_key,
        }
    except Exception as exc:
        db.rollback()
        logger.error("save_memory failed: %s", exc)
        return {"error": f"Failed to save memory: {exc}"}
    finally:
        db.close()


# ── Registration ─────────────────────────────────────────────────────────

registry.register(ToolEntry(
    name="recall_memory",
    description="Search user's long-term memory. Returns user profile facts and semantically relevant interview memories. Use to understand user's background, tech stack, career goals, and past interview learnings.",
    args_model=RecallMemoryArgs,
    handler=_recall_memory_handler,
    max_result_chars=8000,
    emoji="🧠",
))

registry.register(ToolEntry(
    name="save_memory",
    description="Save an important fact to user's long-term memory. Use for: key findings from analysis, user's stated preferences, learning progress notes, preparation milestones. Memory persists across sessions.",
    args_model=SaveMemoryArgs,
    handler=_save_memory_handler,
    max_result_chars=2000,
    emoji="💾",
))
