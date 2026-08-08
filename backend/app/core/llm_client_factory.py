"""LLM + AsyncOpenAI client construction and per-user caching.

Sits on top of the catalog, per-user answer-model selection, and the
deployment-owned internal model configuration. All model call sites end up
here when they need an actual callable LLM object.

What lives here:
  * Answer-model API-key resolution (user credential → deployment fallback)
  * Internal-model API-key resolution (deployment environment only)
  * Per-user api_base / organization / extra_headers override
    (consumes ``user_model_provider_settings``)
  * Two caches, both process-local:
      - LlamaIndex ``OpenAILike`` keyed by (role, profile_id)
      - Raw ``AsyncOpenAI`` keyed by (user_id, profile_id) with an
        LRU bound + auto-invalidate on key/base/header changes
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from llama_index.llms.openai_like import OpenAILike
from openai import AsyncOpenAI, OpenAI

from app.core import user_model_selection
from app.core.config import settings
from app.core.internal_models import get_internal_model_profile
from app.core.model_catalog import ModelProfile
from app.core.model_readiness import (
    profile_ready,
    ready_profile_ids,
    resolve_api_key,
    validate_role_update,
)

logger = logging.getLogger(__name__)
LLM_TEMPERATURE = 0.2


# Single lock guarding the two caches below. Lookups are quick enough
# that contention isn't observable, so one lock keeps the invariants
# (LRU ordering + cleanup) easy to reason about.
_llm_cache_lock = Lock()
# key: (user_id, role, profile_id) → (credential fingerprint, LLM instance)
_llm_cache: dict[tuple[str | None, str, str], tuple[str, Any]] = {}


# ── Per-user provider overrides ────────────────────────────────────────


@dataclass(frozen=True)
class _UserProviderOverrides:
    """Cached snapshot of one (user, provider) row used at chat-completion
    time. Pulled from ``user_model_provider_settings``."""

    api_base: str
    organization_id: str | None
    extra_headers: dict[str, str]


_NO_OVERRIDES = _UserProviderOverrides(
    api_base="", organization_id=None, extra_headers={}
)


def _load_user_provider_overrides(
    profile: ModelProfile,
    user_id: str | None,
) -> _UserProviderOverrides:
    """Single DB read for the per-user (api_base / org_id / extra_headers).

    Returns a sentinel with empty api_base when no row exists OR no
    user_id is given — caller falls back to the profile's default
    api_base in that case. We do ONE query and return all three fields
    together so chat completion isn't hit by three sequential queries.
    """
    from app.core.edition import current_edition_policy

    if not user_id or not current_edition_policy().allow_provider_connection_overrides:
        return _NO_OVERRIDES
    try:
        from app.db.database import SessionLocal
        from app.models.user import User
        from app.models.user_model_provider_settings import UserModelProviderSettings
        from app.services.auth.user_provider_settings_service import parse_extra_headers

        with SessionLocal() as db:
            row = (
                db.query(
                    UserModelProviderSettings.api_base_override,
                    UserModelProviderSettings.organization_id,
                    UserModelProviderSettings.extra_headers_json,
                )
                .join(User, User.id == UserModelProviderSettings.user_id)
                .filter(
                    User.username == user_id,
                    UserModelProviderSettings.provider == profile.provider,
                )
                .first()
            )
        if row is None:
            return _NO_OVERRIDES
        api_base_override, org_id, extra_headers_json = row
        return _UserProviderOverrides(
            api_base=str(api_base_override) if api_base_override else "",
            organization_id=str(org_id) if org_id else None,
            extra_headers=parse_extra_headers(extra_headers_json),
        )
    except Exception as exc:  # noqa: BLE001 — never crash chat on DB blip
        logger.warning(
            "user_model_provider_settings lookup failed for user=%s provider=%s: %s",
            user_id,
            profile.provider,
            exc,
        )
        return _NO_OVERRIDES


def _resolve_api_base(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolve the api_base to call, honouring per-user overrides.

    ``user_model_provider_settings.api_base_override`` covers users on
    subscription endpoints / self-hosted gateways. If the user has no
    row OR the override is NULL, we use the profile's default api_base.
    """
    overrides = _load_user_provider_overrides(profile, user_id)
    return overrides.api_base or profile.api_base


# ── AsyncOpenAI client cache ────────────────────────────────────────────
# Process-local LRU. Avoids spinning up a fresh client (TLS handshake +
# new TCP pool) per call when many requests hit the same (user, profile).
# Bound at 256 entries — ~10 active users × 25 profiles. Each evicted
# client is closed gracefully so the underlying TCP pool releases.
_ASYNC_OPENAI_CACHE_MAX = 256
_async_openai_cache: "OrderedDict[tuple[str | None, str], tuple[str, AsyncOpenAI]]" = (
    OrderedDict()
)


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16] if api_key else ""


def _close_client_quietly(client: AsyncOpenAI) -> None:
    """Best-effort cleanup of a cached AsyncOpenAI when we drop it."""
    import asyncio

    aclose = getattr(client, "aclose", None) or getattr(client, "close", None)
    if not callable(aclose):
        return
    try:
        result = aclose()
    except Exception:  # noqa: BLE001
        return
    if asyncio.iscoroutine(result):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and not loop.is_closed():
            loop.create_task(result)
        else:
            result.close()


def get_async_openai_client(
    profile: ModelProfile, user_id: str | None = None
) -> AsyncOpenAI:
    """Return a process-cached ``AsyncOpenAI`` for ``profile`` + ``user_id``.

    Auto-invalidates when the user changes ANY of (api_key, api_base,
    organization_id, extra_headers) by baking all of them into the
    cache-entry fingerprint. LRU-bounded — least-recently-used entries
    get evicted at the cap.
    """
    api_key = resolve_api_key(profile, user_id=user_id)
    overrides = _load_user_provider_overrides(profile, user_id)
    api_base = overrides.api_base or profile.api_base
    organization = overrides.organization_id
    extra_headers = overrides.extra_headers

    # Fingerprint covers EVERY configurable bit so any user-side change
    # invalidates the cached client. Including the headers dict means
    # an edit to extra_headers_json forces a rebuild on next call.
    fp_input = (
        f"{api_key}|{api_base}|org={organization or ''}|"
        f"hdr={json.dumps(extra_headers, sort_keys=True) if extra_headers else ''}"
    )
    fp = _key_fingerprint(fp_input)
    cache_key = (user_id, profile.id)
    with _llm_cache_lock:
        cached = _async_openai_cache.get(cache_key)
        if cached is not None and cached[0] == fp:
            _async_openai_cache.move_to_end(cache_key)
            return cached[1]
        if cached is not None:
            _close_client_quietly(cached[1])

        # AsyncOpenAI accepts ``organization`` and ``default_headers``
        # constructor kwargs; we pass them only when set so the
        # default behaviour is unchanged for users with no overrides.
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": api_base,
            "timeout": float(settings.LLM_REQUEST_TIMEOUT_SECONDS),
            # Retry policy belongs to the caller. SDK retries here would
            # invisibly multiply Agent/planner retry loops.
            "max_retries": 0,
        }
        if organization:
            kwargs["organization"] = organization
        if extra_headers:
            kwargs["default_headers"] = dict(extra_headers)
        client = AsyncOpenAI(**kwargs)

        _async_openai_cache[cache_key] = (fp, client)
        _async_openai_cache.move_to_end(cache_key)
        while len(_async_openai_cache) > _ASYNC_OPENAI_CACHE_MAX:
            _, evicted = _async_openai_cache.popitem(last=False)
            _close_client_quietly(evicted[1])
        return client


def clear_llm_cache_for_provider(provider: str) -> None:
    """Drop cached LLM + AsyncOpenAI instances for ``provider``.

    Called after a user changes their API key / api_base so the next
    LLM call rebuilds with fresh credentials. We can't iterate
    ``_get_all_profiles`` synchronously here without risking a Redis
    call inside a lock, so we use a string-prefix check on the
    profile id (always ``"{provider}/..."``).
    """
    prefix = f"{provider}/"
    with _llm_cache_lock:
        # LlamaIndex LLM cache: key is (user_id, role, profile_id)
        to_drop_llm = [
            key
            for key in _llm_cache
            if isinstance(key[2], str) and key[2].startswith(prefix)
        ]
        for k in to_drop_llm:
            _llm_cache.pop(k, None)
        # AsyncOpenAI cache: key is (user_id, profile_id)
        to_drop_async = [
            key
            for key in _async_openai_cache
            if isinstance(key[1], str) and key[1].startswith(prefix)
        ]
        for k in to_drop_async:
            entry = _async_openai_cache.pop(k, None)
            if entry is not None:
                _close_client_quietly(entry[1])


# ── Catalog serialization ───────────────────────────────────────────────


def _serialize_profile(
    profile: ModelProfile, selection: dict, user_id: str | None
) -> dict[str, Any]:
    return {
        **asdict(profile),
        "ready": profile_ready(profile, user_id=user_id),
        "selected_for": [role for role, pid in selection.items() if pid == profile.id],
    }


# ── LLM construction ────────────────────────────────────────────────────


def _build_llm_instance(
    profile: ModelProfile,
    user_id: str | None = None,
    *,
    request_overrides: dict[str, Any] | None = None,
):
    """Construct a LlamaIndex ``OpenAILike`` for ``profile``.

    Every supported provider is reached through the OpenAI-compatible
    ``/v1/chat/completions`` protocol — provider switching is purely
    a matter of (api_base, api_key, model_id), no per-vendor wrappers.

    ``user_id`` is honoured so the user's API key + api_base override
    (P6-M) flow through. ``None`` → falls back to env-only.

    LangSmith tracing: when ``LANGSMITH_TRACING=true`` we force-wrap
    the LLM's internal AsyncOpenAI / OpenAI clients here. Redundant
    with ``app.core.llm_tracing``'s module-level patch when import
    order works in our favour — but kept as a defence in depth.
    """
    api_key = resolve_api_key(profile, user_id=user_id)
    overrides = _load_user_provider_overrides(profile, user_id)
    api_base = overrides.api_base or profile.api_base
    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "base_url": api_base,
        "timeout": float(settings.LLM_REQUEST_TIMEOUT_SECONDS),
        "max_retries": 0,
    }
    if overrides.organization_id:
        client_kwargs["organization"] = overrides.organization_id
    if overrides.extra_headers:
        client_kwargs["default_headers"] = dict(overrides.extra_headers)

    sync_client = OpenAI(**client_kwargs)
    async_client = AsyncOpenAI(**client_kwargs)
    llm = OpenAILike(
        model=profile.model,
        api_key=api_key,
        api_base=api_base,
        is_chat_model=True,
        is_function_calling_model=profile.supports_function_calling,
        context_window=profile.context_window,
        temperature=LLM_TEMPERATURE,
        additional_kwargs=dict(request_overrides or {}),
        default_headers=dict(overrides.extra_headers) or None,
        openai_client=sync_client,
        async_openai_client=async_client,
    )

    try:
        from app.core.llm_tracing import wrap_existing_client

        wrap_existing_client(llm._get_aclient())
        wrap_existing_client(llm._get_client())
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangSmith client wrap failed for %s: %s", profile.id, exc)

    return llm


def _get_cached_llm(
    *,
    cache_role: str,
    profile: ModelProfile,
    user_id: str | None,
    request_overrides: dict[str, Any] | None = None,
):
    api_key = resolve_api_key(profile, user_id=user_id)
    overrides = _load_user_provider_overrides(profile, user_id)
    api_base = overrides.api_base or profile.api_base
    fp = _key_fingerprint(
        f"{api_key}|{api_base}|org={overrides.organization_id or ''}|"
        f"hdr={json.dumps(overrides.extra_headers, sort_keys=True)}|"
        f"req={json.dumps(request_overrides or {}, sort_keys=True)}"
    )
    cache_key = (user_id, cache_role, profile.id)
    with _llm_cache_lock:
        cached = _llm_cache.get(cache_key)
        if cached is not None and cached[0] == fp:
            return cached[1]
        instance = _build_llm_instance(
            profile,
            user_id=user_id,
            request_overrides=request_overrides,
        )
        _llm_cache[cache_key] = (fp, instance)
        return instance


def get_llm_for_role(role: str, user_id: str | None = None):
    """Return an answer model selected for one user-facing role."""
    profile = user_model_selection.get_profile_for_role(role, user_id=user_id)
    return _get_cached_llm(
        cache_role=role,
        profile=profile,
        user_id=user_id,
    )


def get_internal_llm(role: str):
    """Return a platform-owned model using deployment credentials only."""
    profile = get_internal_model_profile(role)
    request_overrides = (
        {"extra_body": {"thinking": {"type": "disabled"}}}
        if profile.provider == "deepseek"
        else None
    )
    return _get_cached_llm(
        cache_role=f"internal:{role}",
        profile=profile,
        user_id=None,
        request_overrides=request_overrides,
    )


def build_async_openai_client_for_role(
    role: str,
    user_id: str | None = None,
) -> tuple[AsyncOpenAI, ModelProfile]:
    """Return a cached ``AsyncOpenAI`` + profile for the current selection."""
    profile = user_model_selection.get_profile_for_role(role, user_id=user_id)
    return get_async_openai_client(profile, user_id=user_id), profile


def build_async_openai_client_for_internal_role(
    role: str,
) -> tuple[AsyncOpenAI, ModelProfile]:
    """Return a platform-owned raw client using deployment settings only."""
    profile = get_internal_model_profile(role)
    return get_async_openai_client(profile, user_id=None), profile


__all__ = [
    "resolve_api_key",
    "get_async_openai_client",
    "clear_llm_cache_for_provider",
    "profile_ready",
    "ready_profile_ids",
    "validate_role_update",
    "get_llm_for_role",
    "get_internal_llm",
    "build_async_openai_client_for_role",
    "build_async_openai_client_for_internal_role",
    "_serialize_profile",
]
