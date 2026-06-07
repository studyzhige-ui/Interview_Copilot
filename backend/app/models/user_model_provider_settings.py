"""Per-user provider-level overrides (non-sensitive configuration).

One row per (user, provider) when the user has customised ANYTHING about how
they talk to that vendor. Missing row = the user is happy with the defaults in
``app/services/model_sources/providers.py``.

Stored separately from ``user_model_credentials`` (the encrypted key) because
this table holds NON-SENSITIVE config (api_base, organization id, headers);
mixing the two access patterns into one table makes the encryption boundary
fuzzy.

The row exists for one of three reasons:
  1. The user toggled the provider card visibility (``enabled``).
  2. They overrode ``api_base`` — subscription gateway, self-hosted vLLM /
     Ollama, internal OpenAI-compatible proxy.
  3. They set an organization / project id.

``extra_headers_json`` is an escape hatch for the rare vendor that needs a
custom header (X-Tenant-ID, etc.); set via the PATCH endpoint directly.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE). ``provider`` is the
stable provider key validated at the API layer against ``providers.PROVIDERS``
(not a DB FK — adding/removing a provider must not need a migration).
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class UserModelProviderSettings(Base):
    __tablename__ = "user_model_provider_settings"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", name="uq_user_model_provider_settings",
        ),
    )

    id = Column(String, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False)

    # Default True for newly-created rows. Toggling a card off updates this to
    # False rather than deleting the row, so the user's other settings
    # (api_base, key) survive show/hide cycles.
    enabled = Column(Boolean, nullable=False, default=True)

    # NULL = use ProviderDefaults.default_api_base. API layer requires HTTPS +
    # applies the SSRF private-network blocklist.
    api_base_override = Column(String, nullable=True)

    # NULL = no organization sent. Free-form, capped at 100 chars at the API
    # layer; used as the OpenAI-Organization header / vendor equivalent.
    organization_id = Column(String, nullable=True)

    # JSON-encoded {str: str}. NULL = none. API layer enforces <= 10 entries,
    # value len <= 500, and NEVER Authorization / Cookie / Host.
    extra_headers_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
