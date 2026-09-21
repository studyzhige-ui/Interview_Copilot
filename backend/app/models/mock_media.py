"""Media leases fence connections; playback reports do not certify human hearing."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String
from app.db.database import Base
from app.db.types import UTCDateTime, utc_now


class MockMediaLease(Base):
    __tablename__ = "mock_media_leases"
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), primary_key=True
    )
    client_session_id = Column(String(36), nullable=False)
    connection_id = Column(String(36), nullable=False)
    expires_at = Column(UTCDateTime, nullable=False)


class MockMediaPlayback(Base):
    __tablename__ = "mock_media_playback"
    __table_args__ = (
        CheckConstraint(
            "0 <= client_reported_samples AND client_reported_samples <= delivered_samples AND delivered_samples <= generated_samples",
            name="ck_media_sample_counts",
        ),
        CheckConstraint(
            "status IN ('completed', 'interrupted', 'failed')",
            name="ck_media_playback_status",
        ),
    )
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), primary_key=True
    )
    playback_id = Column(String(36), primary_key=True)
    message_id = Column(
        Integer,
        ForeignKey("conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_samples = Column(Integer, nullable=False)
    delivered_samples = Column(Integer, nullable=False)
    client_reported_samples = Column(Integer, nullable=False)
    sample_rate = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
