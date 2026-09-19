"""Durable UI ingress, not a second owner of invitation business facts."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String

from app.db.database import Base
from app.db.types import JSONValue, UTCDateTime, utc_now


class InvitationSubmission(Base):
    __tablename__ = "invitation_submissions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','committed','rejected','cancelled')",
            name="ck_invitation_submissions_status",
        ),
        Index("ix_invitation_submissions_owner_status", "user_id", "status"),
    )
    id = Column(String(64), primary_key=True)  # owner + exact idempotency key
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # A cancelled tombstone can arrive BEFORE the delayed original request.
    request_fingerprint = Column(String(64), nullable=True)
    request_json = Column(JSONValue, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    operation_id = Column(
        String(36),
        ForeignKey("application_operations.id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_code = Column(String(80), nullable=True)
    created_at = Column(UTCDateTime, nullable=False, default=utc_now)
    updated_at = Column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)
