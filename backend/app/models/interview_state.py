from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, UniqueConstraint

from app.db.database import Base


class InterviewState(Base):
    __tablename__ = "interview_states"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_interview_states_session_user"),
    )

    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    state_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
