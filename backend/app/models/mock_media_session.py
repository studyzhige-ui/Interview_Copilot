"""Durable media leases and client-reported playback, never proof of hearing."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from app.db.database import Base
from app.db.types import UTCDateTime, utc_now


class MockMediaSession(Base):
    __tablename__ = "mock_media_sessions"
    __table_args__ = (
        UniqueConstraint("record_id", "client_session_id", name="uq_mock_media_client"),
    )
    id = Column(String(36), primary_key=True)
    record_id = Column(
        String,
        ForeignKey("interview_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_session_id = Column(String(36), nullable=False)
    generation = Column(Integer, nullable=False, default=1)
    lease_until = Column(UTCDateTime, nullable=False)
    pending_request_id = Column(String(36), nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)


class MockMediaPlayback(Base):
    __tablename__ = "mock_media_playback"
    __table_args__ = (
        CheckConstraint(
            "generated_samples > 0 AND reported_samples >= 0 AND reported_samples <= generated_samples",
            name="ck_media_sample_bounds",
        ),
    )
    id = Column(String(36), primary_key=True)
    session_id = Column(
        String(36),
        ForeignKey("mock_media_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation = Column(Integer, nullable=False)
    question_message_id = Column(Integer, nullable=False)
    text_sha256 = Column(String(64), nullable=False)
    audio_sha256 = Column(String(64), nullable=False)
    sample_rate = Column(Integer, nullable=False)
    generated_samples = Column(Integer, nullable=False)
    reported_samples = Column(Integer, nullable=False, default=0)
    state = Column(String(20), nullable=False, default="generated")
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
