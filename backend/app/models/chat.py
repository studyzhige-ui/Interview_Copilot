import json
import uuid
from datetime import datetime

from sqlalchemy import (
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


def default_session_state() -> str:
    return json.dumps(
        {"mode": "general", "summary": ""},
        ensure_ascii=False,
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    # Production composite indexes — declared here so ORM is the single
    # source of truth and ``alembic revision --autogenerate`` doesn't
    # generate spurious DROP INDEX statements for them. See alembic
    # 0001_baseline (user_type_arch) and 0010_orm_alembic_drift_fixup
    # (user_updated).
    __table_args__ = (
        Index(
            "ix_chat_sessions_user_type_arch",
            "user_id", "session_type", "archived_at",
        ),
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
    )

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    user_id = Column(String, index=True, nullable=False)
    title = Column(String, default="新的面试对话")
    summary = Column(Text, default="")
    session_type = Column(String, index=True, default="general", nullable=False)
    interview_id = Column(
        String, ForeignKey("interview_records.id"), index=True, nullable=True,
    )
    session_state = Column(Text, default=default_session_state)
    compaction_cursor = Column(Integer, default=0)
    memory_extraction_cursor = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    # ix_*_session_seq: read-time order-by-seq for chat history pagination.
    # uq_*_session_seq: write-side guard against duplicate seqs under
    #   concurrent ``append``. See alembic 0001_baseline + 0010.
    __table_args__ = (
        Index("ix_chat_messages_session_seq", "session_id", "seq"),
        UniqueConstraint("session_id", "seq", name="uq_chat_messages_session_seq"),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, ForeignKey("chat_sessions.id"), index=True, nullable=False)
    seq = Column(Integer, index=True, nullable=False)
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
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")
