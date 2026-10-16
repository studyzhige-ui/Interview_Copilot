"""One durable recording draft; model ownership remains in the voice worker."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text
from app.db.database import Base
from app.db.types import UTCDateTime, utc_now


class MockAudioTranscription(Base):
    __tablename__ = "mock_audio_transcriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','transcribing','completed','failed')",
            name="ck_mock_audio_transcription_status",
        ),
    )
    record_id = Column(
        String, ForeignKey("interview_records.id", ondelete="CASCADE"), primary_key=True
    )
    request_id = Column(String(36), primary_key=True)
    question_message_id = Column(Integer, nullable=False)
    audio_file_asset_id = Column(
        String, ForeignKey("file_assets.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(20), nullable=False, default="queued")
    text = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    started_at = Column(UTCDateTime, nullable=True)
    heartbeat_at = Column(UTCDateTime, nullable=True)
    completed_at = Column(UTCDateTime, nullable=True)
