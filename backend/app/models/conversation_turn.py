import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text

from app.db.database import Base


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode = Column(String(16), nullable=False)
    message = Column(Text, nullable=False)
    user_message_seq = Column(Integer, nullable=True)
    assistant_message_seq = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    error = Column(Text, nullable=True)
    owner_id = Column(String(128), nullable=True, index=True)
    heartbeat_at = Column(DateTime, nullable=True, index=True)
    capability_snapshot_json = Column(JSON, nullable=False, default=dict)
    loaded_schemas_json = Column(JSON, nullable=False, default=list)
    budget_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
