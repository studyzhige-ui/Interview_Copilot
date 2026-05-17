from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint

from app.db.database import Base


class UserAPIKey(Base):
    """Per-user, per-provider encrypted API key.

    Plaintext is NEVER stored — only the Fernet ciphertext + a masked
    hint string (e.g. 'sk-****abcd') for the UI to display.
    """

    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_api_keys_user_provider"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True, nullable=False)
    provider = Column(String(64), nullable=False)
    key_ciphertext = Column(Text, nullable=False)
    key_masked = Column(String(32), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
