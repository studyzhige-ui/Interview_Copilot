import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class Conversation(Base):
    __tablename__ = "conversations"
    # Production composite indexes — declared here so ORM is the single
    # source of truth and ``alembic revision --autogenerate`` doesn't
    # generate spurious DROP INDEX statements for them. See alembic
    # 0001_baseline (user_type_arch) and 0010_orm_alembic_drift_fixup
    # (user_updated).
    __table_args__ = (
        Index(
            "ix_conversations_user_type_arch",
            "user_id", "type", "archived_at",
        ),
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    # Stable users.id FK (CLEANUP #2). Resolved from the runtime username via
    # resolve_user_pk at every API/service boundary. A debrief session's owner
    # pk equals its bound interview_record's owner pk, so build_interview_reference
    # matches pk==pk directly — no pk->username bridge needed there.
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title = Column(String, default="新的面试对话")
    summary = Column(Text, default="")
    # Conversation type: general | debrief | mock_interview.
    type = Column(String, index=True, default="general", nullable=False)
    # Run mode for general/debrief: "chat" (L1 deterministic) or "agent" (L2
    # ReAct). mock_interview is always chat. Persisted snapshot of the mode the
    # SSE endpoint selects per request.
    mode = Column(String, nullable=False, default="chat")
    # Polymorphic subject binding (weak FK). subject_type whitelist =
    # {interview_record}; general -> NULL, debrief/mock_interview -> the bound
    # interview_record. The app layer validates existence + ownership. (The
    # legacy ``interview_id`` column it replaced was dropped in 0038.)
    subject_type = Column(String, nullable=True)
    subject_id = Column(String, nullable=True)
    # Per-session global-memory override (NULL = use users.global_memory_enabled
    # default). Resolved by services.memory.recall_policy.
    global_memory_enabled = Column(Boolean, nullable=True)
    compaction_cursor = Column(Integer, default=0)
    memory_extraction_cursor = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "ConversationMessage",
        back_populates="session",
        order_by="ConversationMessage.seq",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    # uq_conversation_messages_conversation_seq is a UNIQUE constraint (backed by
    # a unique B-tree) that does double duty: guards the concurrent-
    # append race AND serves read-time ``ORDER BY seq`` paginations
    # for the chat-history endpoint. 0001 originally created a
    # separate non-unique ``ix_conversation_messages_session_seq`` for the
    # read path; 0011 drops it (the unique B-tree is just as good for
    # the read direction and halves the per-INSERT index-write cost).
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "seq", name="uq_conversation_messages_conversation_seq"
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(
        String, ForeignKey("conversations.id"), index=True, nullable=False
    )
    seq = Column(Integer, index=True, nullable=False)
    # user | assistant | tool | system.
    role = Column(String, nullable=False)
    # Plain-text canonical form — used for session-list preview, memory
    # extraction input, and the read-time fallback when an old row has
    # no ``content_blocks_json``. Always populated.
    content = Column(Text, nullable=False)
    # Anthropic BetaContentBlock[]-shaped JSON. NULL on rows written
    # before the Stage-G conversation-engine refactor; non-NULL going
    # forward — even L1 chat turns store ``[{type: "text", text: ...}]``
    # so the frontend can render every message through the same code
    # path. L2 agent turns include tool_use blocks interleaved with
    # text blocks (Claude Code / Codex folded-card UX).
    content_blocks_json = Column(Text, nullable=True)
    rewritten_query = Column(Text, nullable=True)
    # Tool-message pairing helpers (RFC §conversation_messages). Optional;
    # populated on role="tool" turns so a tool_result can be matched back to
    # its tool_use without re-parsing content_blocks_json.
    tool_call_id = Column(String, nullable=True)
    tool_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Conversation", back_populates="messages")
