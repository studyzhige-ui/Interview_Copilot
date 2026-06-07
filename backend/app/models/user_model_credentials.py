"""Per-user, per-provider encrypted model-API credential.

Plaintext is NEVER stored — only the Fernet ciphertext plus a masked hint
(e.g. ``sk-****abcd``) for the UI to display.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE): a username change
never orphans a credential, and deleting the user reaps its keys. ``provider``
holds the stable provider key (``openai`` / ``deepseek`` / ...) — there is no
provider catalog table; the runtime catalog lives in code / Redis.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class UserModelCredential(Base):
    __tablename__ = "user_model_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_user_model_credentials_user_provider",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider = Column(String(64), nullable=False)
    key_ciphertext = Column(Text, nullable=False)
    key_masked = Column(String(32), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
