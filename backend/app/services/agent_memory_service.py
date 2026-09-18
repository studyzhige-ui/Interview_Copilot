"""Single-owner lifecycle, recall, and consolidation for Agent Memory."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.agent_runtime.tool_redaction import redact_tool_text
from app.core.config import settings
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.conversation_turn import ConversationTurn
from app.models.copilot_preference import CopilotPreference
from app.models.long_term_memory import (
    AgentMemorySetting,
    LongTermAgentMemory,
    LongTermAgentMemorySource,
)
from app.models.pending_submission import PendingSubmission
from app.schemas.agent_memory import (
    AgentMemoryPromotionCommand,
    AgentMemorySettingsUpdate,
    AgentMemorySettingsView,
    AgentMemorySourceView,
    AgentMemoryStatusCommand,
    AgentMemoryUpdate,
    AgentMemoryView,
    ConversationMemoryControlsUpdate,
    ConversationMemoryControlsView,
)

_SEMANTIC_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,119}$")
_IGNORE_RECALL_SIGNALS = (
    "本轮不要使用记忆",
    "这次不要用记忆",
    "忽略长期记忆",
    "不要参考过去的记忆",
    "don't use memory",
    "ignore memory",
    "without memory",
)
_PERSONAL_DATA = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|"
    r"(?:password|token|secret|api[-_ ]?key)\s*[:=])",
    re.IGNORECASE,
)


class AgentMemoryError(ValueError):
    pass


class AgentMemoryNotFoundError(AgentMemoryError):
    pass


class AgentMemoryConflictError(AgentMemoryError):
    pass


class _Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_key: str = Field(min_length=3, max_length=120)
    content: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=400)
    tags: list[str] = Field(default_factory=list, max_length=12)
    valence: str
    confidence: float = Field(ge=0, le=1)
    support_quote: str = Field(min_length=1, max_length=500)

    @field_validator("semantic_key")
    @classmethod
    def key_shape(cls, value: str) -> str:
        normalized = value.strip().casefold().replace(" ", "-")
        if not _SEMANTIC_KEY.fullmatch(normalized):
            raise ValueError("invalid semantic key")
        return normalized

    @field_validator("content", "applicability")
    @classmethod
    def compact_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("valence")
    @classmethod
    def valid_valence(cls, value: str) -> str:
        if value not in {"effective", "ineffective", "mixed"}:
            raise ValueError("invalid valence")
        return value


@dataclass(frozen=True)
class EligibleMemorySource:
    turn_id: str
    conversation_id: str
    user_pk: int
    user_text: str
    assistant_text: str
    observed_at: datetime


def get_settings(db: Session, *, user_pk: int) -> AgentMemorySettingsView:
    row = _settings_row(db, user_pk)
    if row is None:
        return AgentMemorySettingsView(
            recall_enabled=True,
            contribution_enabled=False,
            producer_available=bool(settings.AGENT_MEMORY_PRODUCER_ENABLED),
            version=0,
            updated_at=None,
        )
    return _settings_view(row)


def update_settings(
    db: Session,
    *,
    user_pk: int,
    command: AgentMemorySettingsUpdate,
) -> AgentMemorySettingsView:
    row = (
        db.query(AgentMemorySetting)
        .filter(AgentMemorySetting.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        if command.expected_version != 0:
            raise AgentMemoryConflictError("Memory settings version changed")
        row = AgentMemorySetting(
            user_id=user_pk,
            recall_enabled=command.recall_enabled,
            contribution_enabled=command.contribution_enabled,
            version=1,
        )
        db.add(row)
    else:
        if row.version != command.expected_version:
            raise AgentMemoryConflictError("Memory settings version changed")
        row.recall_enabled = command.recall_enabled
        row.contribution_enabled = command.contribution_enabled
        row.version += 1
        row.updated_at = utc_now()
    db.flush()
    return _settings_view(row)


def get_conversation_controls(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
) -> ConversationMemoryControlsView:
    conversation = _owned_conversation(db, user_pk, conversation_id)
    return _conversation_controls_view(db, conversation)


def update_conversation_controls(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
    command: ConversationMemoryControlsUpdate,
) -> ConversationMemoryControlsView:
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if conversation is None:
        raise AgentMemoryNotFoundError("Conversation not found")
    if int(conversation.memory_control_version or 0) != command.expected_version:
        raise AgentMemoryConflictError("Conversation Memory controls changed")
    conversation.memory_recall_override = command.recall_override
    conversation.memory_contribution_override = command.contribution_override
    conversation.memory_control_version = (
        int(conversation.memory_control_version or 0) + 1
    )
    conversation.updated_at = utc_now()
    db.flush()
    return _conversation_controls_view(db, conversation)


def list_memories(
    db: Session,
    *,
    user_pk: int,
    include_inactive: bool = False,
    limit: int = 100,
) -> list[AgentMemoryView]:
    query = db.query(LongTermAgentMemory).filter(LongTermAgentMemory.user_id == user_pk)
    if not include_inactive:
        query = query.filter(LongTermAgentMemory.status == "active")
    rows = query.order_by(LongTermAgentMemory.updated_at.desc()).limit(limit).all()
    return [_memory_view(db, row) for row in rows]


def update_memory(
    db: Session,
    *,
    user_pk: int,
    memory_id: str,
    command: AgentMemoryUpdate,
) -> AgentMemoryView:
    row = _locked_memory(db, user_pk, memory_id)
    _require_version(row, command.expected_version)
    if row.status == "deleted":
        raise AgentMemoryConflictError("Deleted Memory cannot be revised or revived")
    _validate_memory_text(command.content, command.applicability)
    from app.services.memory_pipeline import invalidate_workspace

    invalidate_workspace(db, user_pk)
    row.content = command.content
    row.applicability = command.applicability
    row.tags_json = list(command.tags)
    row.content_hash = _content_hash(command.content, command.applicability)
    row.status = "active"
    row.status_reason = None
    row.origin = "manual"
    row.index_text = command.applicability
    row.invalidated_at = None
    row.last_confirmed_at = utc_now()
    row.version += 1
    row.updated_at = utc_now()
    db.flush()
    return _memory_view(db, row)


def invalidate_memory(
    db: Session,
    *,
    user_pk: int,
    memory_id: str,
    command: AgentMemoryStatusCommand,
) -> AgentMemoryView:
    row = _locked_memory(db, user_pk, memory_id)
    _require_version(row, command.expected_version)
    if row.status == "deleted":
        raise AgentMemoryConflictError("Deleted Memory cannot change status")
    row.status = "invalidated"
    row.status_reason = "user_invalidated"
    _suppress_memory_sources(db, row)
    row.invalidated_at = utc_now()
    row.version += 1
    row.updated_at = utc_now()
    db.flush()
    return _memory_view(db, row)


def delete_memory(
    db: Session,
    *,
    user_pk: int,
    memory_id: str,
    command: AgentMemoryStatusCommand,
) -> AgentMemoryView:
    row = _locked_memory(db, user_pk, memory_id)
    _require_version(row, command.expected_version)
    if row.status != "deleted":
        row.status = "deleted"
        row.status_reason = "user_deleted"
        _suppress_memory_sources(db, row)
        row.evidence_json = []
        row.index_text = ""
        row.deleted_at = utc_now()
        row.invalidated_at = row.invalidated_at or row.deleted_at
        # Preserve only the content-free suppression identity/hash. Deleted
        # text must not survive in the canonical row or any recall projection.
        row.content = ""
        row.applicability = ""
        row.tags_json = []
        row.version += 1
        row.updated_at = utc_now()
    db.flush()
    return _memory_view(db, row)


def promote_memory_to_preference(
    db: Session,
    *,
    user_pk: int,
    memory_id: str,
    command: AgentMemoryPromotionCommand,
) -> tuple[AgentMemoryView, CopilotPreference]:
    memory = _locked_memory(db, user_pk, memory_id)
    _require_version(memory, command.expected_memory_version)
    if memory.status != "active":
        raise AgentMemoryConflictError("Only active Memory can become a preference")
    preference = (
        db.query(CopilotPreference)
        .filter(CopilotPreference.user_id == user_pk)
        .with_for_update()
        .one_or_none()
    )
    if preference is None:
        if command.expected_preference_version != 0:
            raise AgentMemoryConflictError("CopilotPreference version changed")
        preference = CopilotPreference(
            user_id=user_pk,
            instructions_json=[command.instruction],
            version=1,
        )
        db.add(preference)
    else:
        if preference.version != command.expected_preference_version:
            raise AgentMemoryConflictError("CopilotPreference version changed")
        instructions = list(preference.instructions_json or [])
        if command.instruction not in instructions:
            instructions.append(command.instruction)
            preference.instructions_json = instructions
            preference.version += 1
            preference.updated_at = utc_now()
    memory.status = "invalidated"
    memory.status_reason = "promoted_to_copilot_preference"
    _suppress_memory_sources(db, memory)
    memory.invalidated_at = utc_now()
    memory.version += 1
    memory.updated_at = utc_now()
    db.flush()
    return _memory_view(db, memory), preference


def eligible_source_for_turn(
    db: Session, *, turn_id: str
) -> EligibleMemorySource | None:
    turn = db.get(ConversationTurn, turn_id)
    if turn is None or turn.status != "completed" or turn.completed_at is None:
        return None
    idle_seconds = max(0, int(settings.AGENT_MEMORY_IDLE_SECONDS))
    if utc_now() < turn.completed_at + timedelta(seconds=idle_seconds):
        return None
    conversation = db.get(Conversation, turn.conversation_id)
    if conversation is None or conversation.active_turn_id is not None:
        return None
    if (
        db.query(PendingSubmission.id)
        .filter(
            PendingSubmission.conversation_id == conversation.id,
            PendingSubmission.status.in_(("pending", "failed")),
        )
        .first()
        is not None
    ):
        return None
    if not _effective_controls(db, conversation)[1]:
        return None
    if turn.user_message_seq is None or turn.assistant_message_seq is None:
        return None
    messages = (
        db.query(ConversationMessage)
        .filter(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.seq.in_(
                (int(turn.user_message_seq), int(turn.assistant_message_seq))
            ),
        )
        .all()
    )
    by_seq = {int(item.seq): item for item in messages}
    user_message = by_seq.get(int(turn.user_message_seq))
    assistant_message = by_seq.get(int(turn.assistant_message_seq))
    if user_message is None or assistant_message is None:
        return None
    user_text = redact_tool_text(user_message.content)[:8_000]
    if _PERSONAL_DATA.search(user_text):
        return None
    return EligibleMemorySource(
        turn_id=turn.id,
        conversation_id=conversation.id,
        user_pk=turn.user_id,
        user_text=user_text,
        assistant_text=redact_tool_text(assistant_message.content)[:8_000],
        observed_at=turn.completed_at,
    )


async def consolidate_completed_turn(turn_id: str) -> int:
    """Stable dispatch boundary for the two-phase pipeline."""
    from app.services.memory_pipeline import process_turn

    return await process_turn(turn_id)


def _source_turn_was_processed(
    db: Session,
    *,
    user_pk: int,
    turn_id: str,
) -> bool:
    """Return whether this exact History Turn already formed any Memory.

    Source edges survive Memory deletion without user text, so this check is a
    content-free suppression marker.  It intentionally does not depend on a
    model-generated semantic key or a paraphrasable body hash.
    """

    return (
        db.query(LongTermAgentMemorySource.id)
        .join(
            LongTermAgentMemory,
            LongTermAgentMemory.id == LongTermAgentMemorySource.memory_id,
        )
        .filter(
            LongTermAgentMemory.user_id == user_pk,
            LongTermAgentMemorySource.source_turn_identity == turn_id,
        )
        .first()
        is not None
    )


def invalidate_sources_for_conversation(
    db: Session,
    *,
    user_pk: int,
    conversation_id: str,
) -> int:
    from app.services.memory_pipeline import suppress_sources
    from app.models.memory_pipeline import MemoryExtraction

    turn_ids = {
        r.turn_id
        for r in db.query(MemoryExtraction)
        .filter(
            MemoryExtraction.user_id == user_pk,
            MemoryExtraction.conversation_id == conversation_id,
        )
        .all()
    }
    suppress_sources(db, user_pk, turn_ids)
    now = utc_now()
    sources = (
        db.query(LongTermAgentMemorySource)
        .join(
            LongTermAgentMemory,
            LongTermAgentMemory.id == LongTermAgentMemorySource.memory_id,
        )
        .filter(
            LongTermAgentMemory.user_id == user_pk,
            LongTermAgentMemorySource.source_conversation_identity == conversation_id,
            LongTermAgentMemorySource.source_deleted_at.is_(None),
        )
        .all()
    )
    affected: set[str] = set()
    for source in sources:
        source.source_deleted_at = now
        affected.add(source.memory_id)
    for memory_id in affected:
        remaining = (
            db.query(LongTermAgentMemorySource.id)
            .filter(
                LongTermAgentMemorySource.memory_id == memory_id,
                LongTermAgentMemorySource.source_deleted_at.is_(None),
                LongTermAgentMemorySource.source_conversation_identity
                != conversation_id,
            )
            .first()
        )
        memory = db.get(LongTermAgentMemory, memory_id)
        if memory is not None and memory.status == "active" and remaining is None:
            memory.status = "invalidated"
            memory.status_reason = "all_source_conversations_deleted"
            memory.invalidated_at = now
            memory.version += 1
            memory.updated_at = now
    db.flush()
    return len(affected)


def _effective_controls(db: Session, conversation: Conversation) -> tuple[bool, bool]:
    settings_row = _settings_row(db, int(conversation.user_id))
    account_recall = bool(settings_row.recall_enabled) if settings_row else True
    account_contribution = (
        bool(settings_row.contribution_enabled) if settings_row else False
    )
    recall = (
        account_recall
        if conversation.memory_recall_override is None
        else bool(conversation.memory_recall_override)
    )
    contribution_requested = (
        account_contribution
        if conversation.memory_contribution_override is None
        else bool(conversation.memory_contribution_override)
    )
    contribution = contribution_requested and bool(
        settings.AGENT_MEMORY_PRODUCER_ENABLED
    )
    return recall, contribution


def _conversation_controls_view(
    db: Session,
    conversation: Conversation,
) -> ConversationMemoryControlsView:
    recall, contribution = _effective_controls(db, conversation)
    return ConversationMemoryControlsView(
        conversation_id=conversation.id,
        recall_override=conversation.memory_recall_override,
        contribution_override=conversation.memory_contribution_override,
        effective_recall_enabled=recall,
        effective_contribution_enabled=contribution,
        producer_available=bool(settings.AGENT_MEMORY_PRODUCER_ENABLED),
        version=int(conversation.memory_control_version or 0),
        updated_at=conversation.updated_at,
    )


def _settings_row(db: Session, user_pk: int) -> AgentMemorySetting | None:
    return (
        db.query(AgentMemorySetting)
        .filter(AgentMemorySetting.user_id == user_pk)
        .one_or_none()
    )


def _settings_view(row: AgentMemorySetting) -> AgentMemorySettingsView:
    return AgentMemorySettingsView(
        recall_enabled=bool(row.recall_enabled),
        contribution_enabled=bool(row.contribution_enabled),
        producer_available=bool(settings.AGENT_MEMORY_PRODUCER_ENABLED),
        version=int(row.version),
        updated_at=row.updated_at,
    )


def _memory_view(db: Session, row: LongTermAgentMemory) -> AgentMemoryView:
    sources = (
        db.query(LongTermAgentMemorySource)
        .filter(LongTermAgentMemorySource.memory_id == row.id)
        .order_by(LongTermAgentMemorySource.observed_at)
        .all()
    )
    return AgentMemoryView(
        origin=row.origin,
        index_text=row.index_text,
        usage_count=row.usage_count,
        last_used_at=row.last_used_at,
        evidence=list(row.evidence_json or []),
        id=row.id,
        semantic_key=row.semantic_key,
        content=row.content,
        applicability=row.applicability,
        tags=list(row.tags_json or []),
        valence=row.valence,
        confidence=float(row.confidence),
        status=row.status,
        version=int(row.version),
        formed_at=row.formed_at,
        last_confirmed_at=row.last_confirmed_at,
        last_recalled_at=row.last_recalled_at,
        recall_count=int(row.recall_count or 0),
        status_reason=row.status_reason,
        invalidated_at=row.invalidated_at,
        deleted_at=row.deleted_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        sources=[
            AgentMemorySourceView(
                source_turn_identity=source.source_turn_identity,
                source_conversation_identity=source.source_conversation_identity,
                observed_at=source.observed_at,
                source_deleted_at=source.source_deleted_at,
            )
            for source in sources
        ],
    )


def _owned_conversation(
    db: Session, user_pk: int, conversation_id: str
) -> Conversation:
    row = (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_pk,
        )
        .one_or_none()
    )
    if row is None:
        raise AgentMemoryNotFoundError("Conversation not found")
    return row


def _locked_memory(db: Session, user_pk: int, memory_id: str) -> LongTermAgentMemory:
    from app.services.memory_pipeline import invalidate_workspace

    invalidate_workspace(db, user_pk)
    row = (
        db.query(LongTermAgentMemory)
        .filter(
            LongTermAgentMemory.id == memory_id,
            LongTermAgentMemory.user_id == user_pk,
        )
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise AgentMemoryNotFoundError("Long-term Agent Memory not found")
    return row


def _require_version(row: LongTermAgentMemory, expected: int) -> None:
    if int(row.version) != int(expected):
        raise AgentMemoryConflictError("Long-term Agent Memory version changed")


def _validate_memory_text(content: str, applicability: str) -> None:
    if _PERSONAL_DATA.search(f"{content}\n{applicability}"):
        raise AgentMemoryConflictError("Memory cannot contain contact data or secrets")


def _content_hash(content: str, applicability: str) -> str:
    normalized = json.dumps(
        {"content": content, "applicability": applicability},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


__all__ = [
    "AgentMemoryConflictError",
    "AgentMemoryError",
    "AgentMemoryNotFoundError",
    "consolidate_completed_turn",
    "delete_memory",
    "eligible_source_for_turn",
    "get_conversation_controls",
    "get_settings",
    "invalidate_memory",
    "invalidate_sources_for_conversation",
    "list_memories",
    "promote_memory_to_preference",
    "update_conversation_controls",
    "update_memory",
    "update_settings",
]


def _suppress_memory_sources(db, row):
    from app.services.memory_pipeline import suppress_sources

    turn_ids = {
        s.source_turn_identity
        for s in db.query(LongTermAgentMemorySource)
        .filter(LongTermAgentMemorySource.memory_id == row.id)
        .all()
    }
    suppress_sources(db, row.user_id, turn_ids)
