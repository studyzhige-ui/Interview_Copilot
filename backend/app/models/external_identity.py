"""Cloud identity mapping and independent credentials for this installation only."""

from sqlalchemy import Column, ForeignKey, Integer, String, Text, UniqueConstraint
from app.db.database import Base
from app.db.types import UTCDateTime, utc_now


class ExternalIdentity(Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_external_identity_subject"),
    )

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    issuer = Column(String(255), nullable=False)
    subject = Column(String(36), nullable=False)
    email = Column(String(320), nullable=False, index=True)
    created_at = Column(UTCDateTime, default=utc_now, nullable=False)


class LocalUnlockCredential(Base):
    __tablename__ = "local_unlock_credentials"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash = Column(Text, nullable=False)
    credential_version = Column(Integer, nullable=False, default=1, server_default="1")
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(UTCDateTime, nullable=True)
    updated_at = Column(UTCDateTime, default=utc_now, onupdate=utc_now, nullable=False)
