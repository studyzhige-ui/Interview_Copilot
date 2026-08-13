"""Gmail-specific account and controlled OAuth credential state.

This is not a provider-neutral Connection registry.  The table stores only
the minimum user-visible Gmail account facts plus an encrypted opaque handle
issued by controlled credential infrastructure.  OAuth access/refresh tokens
never belong in this database row.

The provider-specific broker tables below are deliberately not a generic
Connection or Secret domain.  They are private implementation storage for the
one real Google OAuth adapter: raw OAuth state is never persisted, tokens are
always encrypted, and none of these models has a public schema or API.
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


GMAIL_ACCOUNT_STATUSES = ("active", "invalid", "revoked")


def generate_gmail_account_id() -> str:
    return f"gma_{uuid.uuid4().hex}"


def generate_gmail_oauth_state_id() -> str:
    return f"gos_{uuid.uuid4().hex}"


class GmailIntegrationAccount(Base):
    """The user's single connected Gmail account for the first read slice."""

    __tablename__ = "gmail_integration_accounts"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            name="uq_gmail_integration_accounts_user",
        ),
        CheckConstraint(
            "status IN ('active', 'invalid', 'revoked')",
            name="ck_gmail_integration_accounts_status",
        ),
        CheckConstraint(
            "(status = 'revoked' AND credential_handle_ciphertext IS NULL) OR "
            "(status IN ('active', 'invalid') AND "
            "credential_handle_ciphertext IS NOT NULL)",
            name="ck_gmail_integration_accounts_handle_state",
        ),
        Index(
            "ix_gmail_integration_accounts_user_status",
            "user_id",
            "status",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_gmail_account_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Google OpenID subject returned by the trusted OAuth/credential adapter.
    google_subject = Column(String(255), nullable=False)
    # Only a display-safe masked address (for example a***@gmail.com).
    account_hint = Column(String(320), nullable=False)
    scopes_json = Column(JSON, nullable=False, default=list)
    # Encrypted opaque `gch_...` reference. Never an access/refresh token.
    credential_handle_ciphertext = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    last_checked_at = Column(DateTime, nullable=True)
    # A bounded code owned by the adapter contract, never raw provider text.
    last_error_code = Column(String(64), nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class GmailOAuthCredential(Base):
    """Encrypted Google grant owned exclusively by the Gmail adapter.

    ``credential_handle`` is an opaque lookup identity, never an OAuth token.
    The public account row stores only an encrypted copy of that handle.
    """

    __tablename__ = "gmail_oauth_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_gmail_oauth_credentials_user"),
    )

    credential_handle = Column(String(256), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    google_subject = Column(String(255), nullable=False)
    scopes_json = Column(JSON, nullable=False, default=list)
    access_token_ciphertext = Column(Text, nullable=False)
    refresh_token_ciphertext = Column(Text, nullable=False)
    access_token_expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)
    updated_at = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)


class GmailOAuthState(Base):
    """One-time, user-bound CSRF state; only its SHA-256 digest is stored."""

    __tablename__ = "gmail_oauth_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_gmail_oauth_states_user"),
        UniqueConstraint("state_digest", name="uq_gmail_oauth_states_digest"),
        Index("ix_gmail_oauth_states_user_expires", "user_id", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_gmail_oauth_state_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    state_digest = Column(String(64), nullable=False)
    # PKCE verifier is short-lived, encrypted, and deleted with the state
    # during atomic callback claim. It is never part of a public DTO or log.
    code_verifier_ciphertext = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utc_now)


__all__ = [
    "GMAIL_ACCOUNT_STATUSES",
    "GmailIntegrationAccount",
    "GmailOAuthCredential",
    "GmailOAuthState",
    "generate_gmail_account_id",
    "generate_gmail_oauth_state_id",
]
