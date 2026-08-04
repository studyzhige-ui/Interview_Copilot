"""Credential resolution and readiness checks for answer-model profiles."""

from __future__ import annotations

import logging
import os

from app.core import model_catalog
from app.core.model_catalog import ModelProfile, get_profile

logger = logging.getLogger(__name__)


def resolve_api_key(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolve a user's stored provider key, then the deployment fallback."""
    if user_id:
        try:
            from app.services.auth.user_api_key_service import (
                get_user_api_key_plaintext,
            )

            user_key = get_user_api_key_plaintext(user_id, profile.provider)
            if user_key:
                return user_key
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_api_key lookup failed: %s", exc)
    return os.getenv(profile.api_key_env, "")


def ready_profile_ids(
    profiles: dict[str, ModelProfile],
    user_id: str | None = None,
) -> set[str]:
    """Return profile ids whose provider credential resolves for the caller."""
    provider_ok: dict[str, bool] = {}
    ready: set[str] = set()
    for profile_id, profile in profiles.items():
        if not profile.model.strip():
            continue
        available = provider_ok.get(profile.provider)
        if available is None:
            available = bool(resolve_api_key(profile, user_id=user_id))
            provider_ok[profile.provider] = available
        if available:
            ready.add(profile_id)
    return ready


def profile_ready(profile: ModelProfile, user_id: str | None = None) -> bool:
    """Return whether a profile has both a model id and usable credential."""
    return bool(profile.model.strip()) and bool(
        resolve_api_key(profile, user_id=user_id)
    )


def validate_role_update(
    role: str, profile_id: str, user_id: str | None = None
) -> ModelProfile:
    """Validate a user-selectable role assignment and return its profile."""
    if role not in model_catalog.USER_SELECTABLE_ROLES:
        raise ValueError(f"Unknown user-selectable model role: {role}")
    profile = get_profile(profile_id)
    if not profile_ready(profile, user_id=user_id):
        raise ValueError(
            f"Model profile '{profile_id}' is not ready. "
            f"Please configure {profile.api_key_env} first."
        )
    return profile


__all__ = [
    "profile_ready",
    "ready_profile_ids",
    "resolve_api_key",
    "validate_role_update",
]
