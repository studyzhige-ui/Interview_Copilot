"""Per-user provider-level overrides (P6-L scaffold, P6-M wiring).

One row per (user, provider) when the user has customised ANYTHING
about how they talk to that vendor. Missing row = the user is happy
with the defaults declared in ``app/services/model_sources/providers.py``.

Stored separately from ``user_api_keys`` (encrypted credential) because
this table holds NON-SENSITIVE configuration (api_base, organization
id, headers), and mixing the two access patterns into one table makes
the encryption boundary fuzzy.

The row exists for THREE different reasons depending on what the
user did:

  1. They toggled the provider card visibility (``enabled``).
  2. They overrode the api_base — typical for subscription plans
     with a dedicated gateway, self-hosted vLLM/Ollama, internal
     OpenAI-compatible proxy.
  3. They set an organization / project id — OpenAI org-AAA,
     Azure deployment name, Aliyun project id.

``extra_headers_json`` exists in the schema but the v1 UI doesn't
expose it (P6-M decision). It's an escape hatch for the rare vendor
that requires a custom header (X-Tenant-ID, etc.). Settable via the
PATCH endpoint directly for now.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base


class UserProviderSettings(Base):
    __tablename__ = "user_provider_settings"

    id = Column(String, primary_key=True)
    user_id = Column(
        String,
        ForeignKey("users.username", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # MUST be a value present in ``providers.PROVIDERS``. Enforced
    # at the API layer (Pydantic validator), not at the DB layer —
    # adding/removing a provider from PROVIDERS shouldn't require a
    # DB migration. If a provider is removed, orphan rows are
    # ignored by the catalog (the join in the pipeline just drops
    # them).
    provider = Column(String, nullable=False)

    # Default True for newly-created rows. The "show more vendors"
    # picker (P6-M) creates rows with enabled=True; toggling a card
    # off updates this to False rather than deleting the row, so the
    # user's other settings (api_base, key) are preserved across
    # show/hide cycles.
    enabled = Column(Boolean, nullable=False, default=True)

    # NULL = use ProviderDefaults.default_api_base. Validated by the
    # API layer: HTTPS scheme required, SSRF check applied (reuses
    # ``app/agent_runtime/tools/web.py`` private-network blocklist).
    api_base_override = Column(String, nullable=True)

    # NULL = no organization sent. Free-form string capped at 100
    # chars at the API layer. Used as the ``OpenAI-Organization``
    # header for OpenAI / equivalent identifier for other vendors.
    organization_id = Column(String, nullable=True)

    # JSON-encoded {str: str} dict. NULL = no extra headers. v1 UI
    # does NOT surface this — only callable via direct PATCH for
    # rare per-vendor needs (X-Tenant-ID, X-Project-Id, etc.).
    # API layer enforces: <= 10 entries, value len <= 500, NEVER
    # accepts Authorization / Cookie / Host (these are system-
    # controlled).
    extra_headers_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider_settings"),
    )
