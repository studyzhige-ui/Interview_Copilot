from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from app.db.database import Base


class ConversationCapabilityState(Base):
    __tablename__ = "conversation_capability_states"

    conversation_id = Column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    discovered_skills_json = Column(JSON, nullable=False, default=list)
    permissions_json = Column(JSON, nullable=False, default=dict)
    tool_history_json = Column(JSON, nullable=False, default=list)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
