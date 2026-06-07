"""CRUD helpers for the ``user_model_provider_settings`` table.

One row per (user, provider) when the user has overridden anything
about how the system talks to that vendor. Missing row = use defaults
from ``app.services.model_sources.providers``.

The service layer here is thin — just enough to encapsulate session
handling + idempotent upsert so the API layer doesn't deal with
SQLAlchemy directly.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.user_model_provider_settings import UserModelProviderSettings
from app.services.model_sources.providers import (
    PROVIDERS,
    ProviderDefaults,
    get_provider_defaults,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedProviderSettings:
    """Per-user effective view: defaults merged with overrides.

    Returned by ``resolve_provider_settings`` for every provider that
    appears in ``PROVIDERS``. Whether or not the user has a row, the
    caller gets a complete record — defaults filled in for any
    unoverridden field.
    """
    provider: str
    display_label: str
    icon_slug: str | None
    enabled: bool                        # effective (default OR user-set)
    has_user_row: bool                   # True if user_provider_settings has a row
    api_base: str                        # effective (default if no override)
    api_base_override: str | None        # user's override, if any
    organization_id: str | None
    extra_headers_json: str | None
    api_key_env: str
    has_user_api_key: bool               # whether user_model_credentials[provider] exists

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Internal helpers ────────────────────────────────────────────────────


def _session(db: Session | None) -> Session:
    """Context-manager-friendly session. Pass-through (nullcontext) when the
    caller already opened one; otherwise mint a fresh ``SessionLocal()`` that
    closes on ``__exit__``."""
    if db is not None:
        # Caller manages lifecycle.
        from contextlib import nullcontext
        return nullcontext(db)  # type: ignore[return-value]
    return SessionLocal()


def _get_row(
    db: Session, user_pk: int | None, provider: str,
) -> UserModelProviderSettings | None:
    if user_pk is None:
        return None
    return (
        db.query(UserModelProviderSettings)
        .filter(
            UserModelProviderSettings.user_id == user_pk,
            UserModelProviderSettings.provider == provider,
        )
        .first()
    )


def _has_user_credential(db: Session, user_pk: int | None, provider: str) -> bool:
    """Cheap existence check. Reuses the encrypted-credential table without
    decrypting — we only need to know IF a key exists, not the value."""
    if user_pk is None:
        return False
    from app.models.user_model_credentials import UserModelCredential
    return (
        db.query(UserModelCredential.id)
        .filter(
            UserModelCredential.user_id == user_pk,
            UserModelCredential.provider == provider,
        )
        .first()
    ) is not None


# ── Public API ──────────────────────────────────────────────────────────


def resolve_provider_settings(
    user_id: str, provider: str, *, db: Session | None = None,
) -> ResolvedProviderSettings | None:
    """Return the effective settings for one (user, provider).

    ``None`` if ``provider`` isn't in ``PROVIDERS`` (caller should 404).
    """
    defaults = get_provider_defaults(provider)
    if defaults is None:
        return None
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        row = _get_row(s, user_pk, provider)
        return _resolve_one(
            defaults, row, has_key=_has_user_credential(s, user_pk, provider),
        )


def resolve_all_provider_settings(
    user_id: str, *, db: Session | None = None,
) -> list[ResolvedProviderSettings]:
    """Return effective settings for EVERY provider in ``PROVIDERS``.

    Used by ``GET /models/providers`` so the frontend can render both
    the user's enabled providers AND the "show more vendors" picker
    in a single round trip.
    """
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        rows_by_provider = {
            row.provider: row
            for row in s.query(UserModelProviderSettings)
            .filter(UserModelProviderSettings.user_id == user_pk)
            .all()
        }
        # Existence check for ALL providers in one query (per-provider
        # query would be N+1).
        from app.models.user_model_credentials import UserModelCredential
        keys_present = {
            row[0] for row in s.query(UserModelCredential.provider)
            .filter(UserModelCredential.user_id == user_pk)
            .all()
        }
        return [
            _resolve_one(defaults, rows_by_provider.get(provider), has_key=provider in keys_present)
            for provider, defaults in PROVIDERS.items()
        ]


def _resolve_one(
    defaults: ProviderDefaults,
    row: UserModelProviderSettings | None,
    *,
    has_key: bool,
) -> ResolvedProviderSettings:
    return ResolvedProviderSettings(
        provider=defaults.id,
        display_label=defaults.display_label,
        icon_slug=defaults.icon_slug,
        enabled=row.enabled if row is not None else defaults.enabled_by_default,
        has_user_row=row is not None,
        api_base=row.api_base_override if (row and row.api_base_override) else defaults.default_api_base,
        api_base_override=row.api_base_override if row else None,
        organization_id=row.organization_id if row else None,
        extra_headers_json=row.extra_headers_json if row else None,
        api_key_env=defaults.api_key_env,
        has_user_api_key=has_key,
    )


# ── Mutations ──────────────────────────────────────────────────────────


@dataclass
class SettingsPatch:
    """Each field is None → "don't touch". A field set to a value writes
    it; an explicit ``api_base_override=""`` clears the override (back
    to default).
    """
    enabled: bool | None = None
    api_base_override: str | None = None
    organization_id: str | None = None
    extra_headers_json: str | None = None


# Sentinel used by the API layer to distinguish "unset" from "clear".
# Pydantic input layer translates explicit nulls / empty strings into
# this sentinel; our service treats it as "delete the column".
_CLEAR = object()


def upsert_settings(
    user_id: str, provider: str, patch: SettingsPatch,
    *, db: Session | None = None,
) -> ResolvedProviderSettings:
    """Create-or-update the user's settings row for one provider.

    Raises ``ValueError`` if ``provider`` isn't in ``PROVIDERS``. The
    caller (API endpoint) maps that to HTTP 404.
    """
    defaults = get_provider_defaults(provider)
    if defaults is None:
        raise ValueError(f"unknown provider: {provider}")

    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            raise ValueError(f"unknown user: {user_id}")
        row = _get_row(s, user_pk, provider)
        if row is None:
            row = UserModelProviderSettings(
                id=str(uuid.uuid4()),
                user_id=user_pk,
                provider=provider,
                enabled=defaults.enabled_by_default,
            )
            s.add(row)

        if patch.enabled is not None:
            row.enabled = patch.enabled
        if patch.api_base_override is not None:
            # "" means "clear the override, revert to default" — store
            # NULL not "" so resolve_provider_settings falls back cleanly.
            row.api_base_override = patch.api_base_override or None
        if patch.organization_id is not None:
            row.organization_id = patch.organization_id or None
        if patch.extra_headers_json is not None:
            row.extra_headers_json = patch.extra_headers_json or None

        s.commit()
        s.refresh(row)
        # Re-read key existence — could have changed if another request
        # raced. Cheap, so just include.
        has_key = _has_user_credential(s, user_pk, provider)
    return _resolve_one(defaults, row, has_key=has_key)


def delete_settings(
    user_id: str, provider: str, *, db: Session | None = None,
) -> bool:
    """Remove the user's overrides row for one provider, reverting to
    defaults. Returns ``True`` if a row was deleted, ``False`` if there
    was nothing to delete.

    Does NOT touch ``user_api_keys`` — the user keeps their encrypted
    key. Use the existing ``DELETE /models/api-keys/{provider}``
    endpoint for that.
    """
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        row = _get_row(s, user_pk, provider)
        if row is None:
            return False
        s.delete(row)
        s.commit()
        return True


def parse_extra_headers(payload: str | None) -> dict[str, str]:
    """Safe parse of ``extra_headers_json``. Used by the chat-completion
    path to inject these into the outbound httpx call.

    Returns ``{}`` on any malformed input — failing closed is safer
    than crashing the chat path on a bad row. The PATCH endpoint
    validates the shape on write so this branch should be unreachable
    in practice, but we belt-and-brace it for legacy rows / out-of-
    band edits.
    """
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


__all__ = [
    "ResolvedProviderSettings",
    "SettingsPatch",
    "resolve_provider_settings",
    "resolve_all_provider_settings",
    "upsert_settings",
    "delete_settings",
    "parse_extra_headers",
]
