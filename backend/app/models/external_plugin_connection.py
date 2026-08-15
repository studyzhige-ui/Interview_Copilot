"""Closed Canva/Notion account facts and short-lived OAuth state.

The application database stores only display-safe account facts and an
encrypted opaque credential handle. OAuth access and refresh tokens live in
the separately configured credential store.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import JSONValue as JSON
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


EXTERNAL_PLUGIN_PROVIDERS = ("canva", "notion")
EXTERNAL_PLUGIN_ACCOUNT_STATUSES = ("active", "invalid", "revoked")


def _account_id() -> str:
    return f"epa_{uuid.uuid4().hex}"


def _oauth_state_id() -> str:
    return f"eps_{uuid.uuid4().hex}"


class ExternalPluginAccount(Base):
    __tablename__ = "external_plugin_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_external_plugin_accounts_user_provider"
        ),
        CheckConstraint(
            "provider IN ('canva', 'notion')",
            name="ck_external_plugin_accounts_provider",
        ),
        CheckConstraint(
            "status IN ('active', 'invalid', 'revoked')",
            name="ck_external_plugin_accounts_status",
        ),
        CheckConstraint(
            "(status = 'revoked' AND credential_handle_ciphertext IS NULL) OR "
            "(status IN ('active', 'invalid') AND credential_handle_ciphertext IS NOT NULL)",
            name="ck_external_plugin_accounts_handle_state",
        ),
        Index("ix_external_plugin_accounts_user_status", "user_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=_account_id)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(String(16), nullable=False)
    external_account_id = Column(String(255), nullable=False)
    account_hint = Column(String(320), nullable=False)
    scopes_json = Column(JSON, nullable=False, default=list)
    credential_handle_ciphertext = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    last_checked_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class ExternalPluginOAuthState(Base):
    __tablename__ = "external_plugin_oauth_states"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            name="uq_external_plugin_oauth_states_user_provider",
        ),
        UniqueConstraint("state_digest", name="uq_external_plugin_oauth_states_digest"),
        CheckConstraint(
            "provider IN ('canva', 'notion')",
            name="ck_external_plugin_oauth_states_provider",
        ),
        Index("ix_external_plugin_oauth_states_user_expires", "user_id", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=_oauth_state_id)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String(16), nullable=False)
    state_digest = Column(String(64), nullable=False)
    code_verifier_ciphertext = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "EXTERNAL_PLUGIN_ACCOUNT_STATUSES",
    "EXTERNAL_PLUGIN_PROVIDERS",
    "ExternalPluginAccount",
    "ExternalPluginOAuthState",
]
