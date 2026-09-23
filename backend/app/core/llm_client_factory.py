"""LLM + AsyncOpenAI client construction and per-user caching.

Sits on top of the catalog, per-user answer-model selection, and the
deployment-owned internal model configuration. All model call sites end up
here when they need an actual callable LLM object.

What lives here:
  * Answer-model API-key resolution (user credential → deployment fallback)
  * Internal-model API-key resolution (deployment environment only)
  * Per-user api_base / organization / extra_headers override
    (consumes ``user_model_provider_settings``)
  * Bounded caches owned by the executing event loop:
      - LlamaIndex ``OpenAILike`` keyed by (role, profile_id)
      - Native ``AsyncOpenAI`` and ``AsyncAnthropic`` clients keyed by
        (user_id, profile_id), with an LRU bound + auto-invalidate on
        key/base/header changes
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI, OpenAI

from app.core import user_model_selection
from app.core.config import settings
from app.core.runtime_resources import current_resources
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
_provider_versions: dict[str, int] = {}
# key: (user_id, role, profile_id) → (credential fingerprint, LLM instance)


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
# Loop-owned LRU. Avoids spinning up a fresh client (TLS handshake +
# new TCP pool) per call when many requests hit the same (user, profile).
# Bound at 256 entries — ~10 active users × 25 profiles. Each evicted
# client is closed gracefully so the underlying TCP pool releases.
_ASYNC_OPENAI_CACHE_MAX = 256


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16] if api_key else ""


def _native_anthropic_base_url(api_base: str) -> str:
    """Translate the catalog's REST base into the native SDK base.

    Provider discovery stores bases such as ``https://api.anthropic.com/v1``
    because it appends ``/models`` itself.  The official Anthropic SDK instead
    appends ``/v1/messages`` to ``base_url``.  Passing the catalog value
    unchanged therefore calls ``/v1/v1/messages``.  Strip exactly one terminal
    API-version segment while preserving any gateway prefix before it.
    """

    normalized = str(api_base or "").rstrip("/")
    return normalized[:-3] if normalized.endswith("/v1") else normalized


def _close_client_quietly(client: Any) -> None:
    current_resources().retire(client)


async def get_async_openai_client(
    profile: ModelProfile, user_id: str | None = None
) -> AsyncOpenAI:
    """Return a loop-cached ``AsyncOpenAI`` for ``profile`` + ``user_id``.

    Auto-invalidates when the user changes ANY of (api_key, api_base,
    organization_id, extra_headers) by baking all of them into the
    cache-entry fingerprint. LRU-bounded — least-recently-used entries
    get evicted at the cap.
    """
    api_key = await asyncio.to_thread(resolve_api_key, profile, user_id=user_id)
    overrides = await asyncio.to_thread(_load_user_provider_overrides, profile, user_id)
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
    fp = _key_fingerprint(
        fp_input + str(_provider_versions.get(profile.id.split("/")[0], 0))
    )
    cache_key = (user_id, profile.id)
    _async_openai_cache = current_resources().openai
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


async def get_async_anthropic_client(
    profile: ModelProfile,
    user_id: str | None = None,
) -> AsyncAnthropic:
    """Return a cached native Anthropic client for one resolved profile.

    Credentials and user endpoint/header overrides use the same resolution
    path as every other answer model. The SDK retry count stays zero because
    the Agent strategy owns bounded retry and compaction recovery.
    """

    if profile.provider != "anthropic":
        raise ValueError("native Anthropic client requires an anthropic profile")
    api_key = await asyncio.to_thread(resolve_api_key, profile, user_id=user_id)
    overrides = await asyncio.to_thread(_load_user_provider_overrides, profile, user_id)
    api_base = _native_anthropic_base_url(overrides.api_base or profile.api_base)
    extra_headers = overrides.extra_headers
    fp_input = (
        f"{api_key}|{api_base}|org={overrides.organization_id or ''}|"
        f"hdr={json.dumps(extra_headers, sort_keys=True) if extra_headers else ''}"
    )
    fp = _key_fingerprint(
        fp_input + str(_provider_versions.get(profile.id.split("/")[0], 0))
    )
    cache_key = (user_id, profile.id)
    _async_anthropic_cache = current_resources().anthropic
    with _llm_cache_lock:
        cached = _async_anthropic_cache.get(cache_key)
        if cached is not None and cached[0] == fp:
            _async_anthropic_cache.move_to_end(cache_key)
            return cached[1]
        if cached is not None:
            _close_client_quietly(cached[1])

        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": api_base,
            "timeout": float(settings.LLM_REQUEST_TIMEOUT_SECONDS),
            "max_retries": 0,
        }
        if extra_headers:
            kwargs["default_headers"] = dict(extra_headers)
        client = AsyncAnthropic(**kwargs)
        _async_anthropic_cache[cache_key] = (fp, client)
        _async_anthropic_cache.move_to_end(cache_key)
        while len(_async_anthropic_cache) > _ASYNC_OPENAI_CACHE_MAX:
            _, evicted = _async_anthropic_cache.popitem(last=False)
            _close_client_quietly(evicted[1])
        return client


def clear_llm_cache_for_provider(provider: str) -> None:
    """Drop cached LLM + native provider clients for ``provider``.

    Called after a user changes their API key / api_base so the next
    LLM call rebuilds with fresh credentials. We can't iterate
    ``_get_all_profiles`` synchronously here without risking a Redis
    call inside a lock, so we use a string-prefix check on the
    profile id (always ``"{provider}/..."``).
    """
    # Every lookup fingerprints current credentials. No cross-loop mutation:
    # the owner retires a changed client when next used.
    with _llm_cache_lock:
        _provider_versions[provider] = _provider_versions.get(provider, 0) + 1


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
    """Construct the legacy LlamaIndex ``OpenAILike`` fallback for ``profile``.

    Production Chat/Agent calls use the native provider adapters.  This object
    remains for older internal call sites and test doubles, so its optional
    LlamaIndex/Transformers dependency must stay behind this function boundary;
    importing the Cloud API must not load the Community ML stack.

    ``user_id`` is honoured so the user's API key + api_base override
    (P6-M) flow through. ``None`` → falls back to env-only.

    LangSmith tracing: when ``LANGSMITH_TRACING=true`` we force-wrap
    the LLM's internal AsyncOpenAI / OpenAI clients here. Redundant
    with ``app.core.llm_tracing``'s module-level patch when import
    order works in our favour — but kept as a defence in depth.
    """
    from llama_index.llms.openai_like import OpenAILike

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
    # Synchronous consumers own their instance. Async reuse is bounded and
    # belongs to the loop that will actually use the underlying transport.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _build_llm_instance(
            profile, user_id=user_id, request_overrides=request_overrides
        )
    resources = current_resources()
    overrides = _load_user_provider_overrides(profile, user_id)
    fp = _key_fingerprint(
        json.dumps(
            {
                "key": resolve_api_key(profile, user_id=user_id),
                "base": overrides.api_base or profile.api_base,
                "org": overrides.organization_id,
                "headers": overrides.extra_headers,
                "request": request_overrides,
            },
            sort_keys=True,
        )
    )
    key = (user_id, cache_role, profile.id)
    cached = resources.llms.get(key)
    if cached is not None and cached[0] == fp:
        resources.llms.move_to_end(key)
        return cached[1]
    if cached is not None:
        resources.retire(cached[1])
    instance = _build_llm_instance(
        profile, user_id=user_id, request_overrides=request_overrides
    )
    resources.llms[key] = (fp, instance)
    resources.llms.move_to_end(key)
    while len(resources.llms) > _ASYNC_OPENAI_CACHE_MAX:
        resources.retire(resources.llms.popitem(last=False)[1][1])
    return instance


def _legacy_request_overrides(profile: ModelProfile) -> dict[str, Any] | None:
    """Provider fixes for legacy LlamaIndex completion call sites.

    Native Chat/Agent adapters own their own payloads. Older structured JSON
    workflows still use ``OpenAILike``; DeepSeek's thinking mode can put the
    response outside ``message.content`` there, yielding an empty JSON body.
    """

    if profile.provider == "deepseek":
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return None


def get_llm_for_role(role: str, user_id: str | None = None):
    """Return an answer model selected for one user-facing role."""
    profile = user_model_selection.get_profile_for_role(role, user_id=user_id)
    return _get_cached_llm(
        cache_role=role,
        profile=profile,
        user_id=user_id,
        request_overrides=_legacy_request_overrides(profile),
    )


def get_internal_llm(role: str):
    """Return a platform-owned model using deployment credentials only."""
    profile = get_internal_model_profile(role)
    return _get_cached_llm(
        cache_role=f"internal:{role}",
        profile=profile,
        user_id=None,
        request_overrides=_legacy_request_overrides(profile),
    )


async def build_provider_client_for_role(
    role: str,
    user_id: str | None = None,
) -> tuple[Any, ModelProfile]:
    """Return the selected role's native transport client and profile."""

    profile = await asyncio.to_thread(
        user_model_selection.get_profile_for_role, role, user_id=user_id
    )
    if profile.provider == "anthropic":
        return await get_async_anthropic_client(profile, user_id=user_id), profile
    return await get_async_openai_client(profile, user_id=user_id), profile


__all__ = [
    "resolve_api_key",
    "get_async_openai_client",
    "get_async_anthropic_client",
    "clear_llm_cache_for_provider",
    "profile_ready",
    "ready_profile_ids",
    "validate_role_update",
    "get_llm_for_role",
    "get_internal_llm",
    "build_provider_client_for_role",
    "_serialize_profile",
]
