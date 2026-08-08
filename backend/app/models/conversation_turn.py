import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, Text

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


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
    created_at = Column(DateTime, nullable=False, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
