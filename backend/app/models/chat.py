import json
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


def default_working_state() -> str:
    return json.dumps(
        {
            "goal": "",
            "current_phase": "",
            "covered_topics": [],
            "pending_topics": [],
            "candidate_claims_to_verify": [],
            "observed_gaps": [],
            "next_best_question": "",
            "constraints": [],
            "summary": "",
        },
        ensure_ascii=False,
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=generate_uuid, index=True)
    user_id = Column(String, index=True, nullable=False)
    title = Column(String, default="新的面试对话")
    summary = Column(Text, default="")
    working_state = Column(Text, default=default_working_state)
    compaction_cursor = Column(Integer, default=0)
    memory_cursor = Column(Integer, default=0)
    turn_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        order_by="ChatMessage.seq",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, ForeignKey("chat_sessions.id"), index=True, nullable=False)
    seq = Column(Integer, index=True, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    rewritten_query = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ChatSession", back_populates="messages")
