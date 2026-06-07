"""LLM + AsyncOpenAI client construction and per-user caching.

Sits on top of the catalog (``app.core.model_catalog``) + per-user
selection (``app.core.user_model_selection``). All chat / agent
call sites end up here when they need an actual callable LLM
object.

What lives here:
  * API-key resolution priority (user_model_credentials → env-var fallback)
  * Per-user api_base / organization / extra_headers override
    (consumes ``user_model_provider_settings``)
  * Two caches, both process-local:
      - LlamaIndex ``OpenAILike`` keyed by (role, profile_id)
      - Raw ``AsyncOpenAI`` keyed by (user_id, profile_id) with an
        LRU bound + auto-invalidate on key/base/header changes
  * ``RuntimeLLMProxy`` — wired into LlamaIndex ``Settings.llm`` so
    runtime selection changes are picked up without recreating
    the proxy
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any

from llama_index.llms.openai_like import OpenAILike
from openai import AsyncOpenAI

from app.core import model_catalog, user_model_selection
from app.core.model_catalog import ModelProfile, get_profile

logger = logging.getLogger(__name__)


# Single lock guarding the two caches below. Lookups are quick enough
# that contention isn't observable, so one lock keeps the invariants
# (LRU ordering + cleanup) easy to reason about.
_llm_cache_lock = Lock()
_llm_cache: dict[tuple[str, str], Any] = {}


# ── API-key resolution ──────────────────────────────────────────────────


def resolve_api_key(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolve the API key to use when calling this profile.

    Priority:
      1) ``user_model_credentials`` row for (user_id, provider) — encrypted DB
      2) ``os.environ[profile.api_key_env]`` — legacy / single-tenant path

    Returns ``""`` when nothing resolves; downstream auth then fails
    visibly instead of papering over a config bug.
    """
    if user_id:
        try:
            from app.services.auth.user_api_key_service import get_user_api_key_plaintext
            user_key = get_user_api_key_plaintext(user_id, profile.provider)
            if user_key:
                return user_key
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_api_key lookup failed: %s", exc)
    return os.getenv(profile.api_key_env, "")


# ── Per-user provider overrides ────────────────────────────────────────


@dataclass(frozen=True)
class _UserProviderOverrides:
    """Cached snapshot of one (user, provider) row used at chat-completion
    time. Pulled from ``user_model_provider_settings``."""
    api_base: str
    organization_id: str | None
    extra_headers: dict[str, str]


_NO_OVERRIDES = _UserProviderOverrides(api_base="", organization_id=None, extra_headers={})


def _load_user_provider_overrides(
    profile: ModelProfile, user_id: str | None,
) -> _UserProviderOverrides:
    """Single DB read for the per-user (api_base / org_id / extra_headers).

    Returns a sentinel with empty api_base when no row exists OR no
    user_id is given — caller falls back to the profile's default
    api_base in that case. We do ONE query and return all three fields
    together so chat completion isn't hit by three sequential queries.
    """
    if not user_id:
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
            user_id, profile.provider, exc,
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
_async_openai_cache: "OrderedDict[tuple[str | None, str], tuple[str, AsyncOpenAI]]" = OrderedDict()


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


def get_async_openai_client(profile: ModelProfile, user_id: str | None = None) -> AsyncOpenAI:
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
            "timeout": 30.0,
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


def _clear_llm_instance_cache() -> None:
    """Drop ALL cached LLM instances. Called from selection persistence
    so the user's next chat reflects their fresh role mapping."""
    with _llm_cache_lock:
        _llm_cache.clear()


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
        # LlamaIndex LLM cache: key is (role, profile_id)
        to_drop_llm = [
            key for key in _llm_cache if isinstance(key[1], str) and key[1].startswith(prefix)
        ]
        for k in to_drop_llm:
            _llm_cache.pop(k, None)
        # AsyncOpenAI cache: key is (user_id, profile_id)
        to_drop_async = [
            key for key in _async_openai_cache
            if isinstance(key[1], str) and key[1].startswith(prefix)
        ]
        for k in to_drop_async:
            entry = _async_openai_cache.pop(k, None)
            if entry is not None:
                _close_client_quietly(entry[1])


def profile_ready(profile: ModelProfile, user_id: str | None = None) -> bool:
    """A profile is "ready" when SOME key resolves for it.

    With ``user_id`` we check ``user_model_credentials`` first, then env.
    Without ``user_id`` we fall back to env-only (legacy / ping path).
    """
    return bool(resolve_api_key(profile, user_id=user_id)) and bool(profile.model.strip())


# ── Catalog serialization ───────────────────────────────────────────────


def _serialize_profile(profile: ModelProfile, selection: dict, user_id: str | None) -> dict[str, Any]:
    return {
        **asdict(profile),
        "ready": profile_ready(profile, user_id=user_id),
        "selected_for": [role for role, pid in selection.items() if pid == profile.id],
    }


def list_profiles(user_id: str | None = None) -> list[dict[str, Any]]:
    """Snapshot of the runtime catalog for ``user_id``.

    Reads the pipeline cache (warmed lazily from Redis). Every entry
    comes from a vendor's own /v1/models endpoint via the adapter
    pipeline in ``app.services.model_sources``. Empty list means
    nothing has populated the catalog yet — operators should run
    ``scripts/refresh_models.py`` or wait for the daily Celery beat.
    """
    profiles = model_catalog._get_all_profiles()
    selection = user_model_selection.get_runtime_selection(user_id)
    return [_serialize_profile(p, selection, user_id) for p in profiles.values()]


def validate_role_update(role: str, profile_id: str, user_id: str | None = None) -> ModelProfile:
    profile = get_profile(profile_id)
    if not profile_ready(profile, user_id=user_id):
        raise ValueError(
            f"Model profile '{profile_id}' is not ready. "
            f"Please configure {profile.api_key_env} first."
        )
    if role == "agent" and not profile.supports_function_calling:
        raise ValueError(
            f"Model profile '{profile_id}' does not support function calling "
            "and cannot be used for agent role."
        )
    return profile


# ── LLM construction ────────────────────────────────────────────────────


def _build_llm_instance(profile: ModelProfile, user_id: str | None = None):
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
    api_base = _resolve_api_base(profile, user_id=user_id)
    llm = OpenAILike(
        model=profile.model,
        api_key=api_key,
        api_base=api_base,
        is_chat_model=True,
        is_function_calling_model=profile.supports_function_calling,
        context_window=profile.context_window,
        temperature=0.2,
    )

    try:
        from app.core.llm_tracing import wrap_existing_client

        wrap_existing_client(llm._get_aclient())
        wrap_existing_client(llm._get_client())
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangSmith client wrap failed for %s: %s", profile.id, exc)

    return llm


def get_llm_for_role(role: str, user_id: str | None = None):
    """Build (or fetch from cache) a llama-index LLM for ``role``."""
    profile = user_model_selection.get_profile_for_role(role, user_id=user_id)
    cache_key = (role, profile.id)
    with _llm_cache_lock:
        cached = _llm_cache.get(cache_key)
        if cached is not None:
            return cached
        instance = _build_llm_instance(profile, user_id=user_id)
        _llm_cache[cache_key] = instance
        return instance


def build_async_openai_client_for_role(
    role: str,
    user_id: str | None = None,
) -> tuple[AsyncOpenAI, ModelProfile]:
    """Return a cached ``AsyncOpenAI`` + profile for the current selection."""
    profile = user_model_selection.get_profile_for_role(role, user_id=user_id)
    return get_async_openai_client(profile, user_id=user_id), profile


class RuntimeLLMProxy:
    """Process-global LLM proxy wired into LlamaIndex ``Settings.llm``.

    Always resolves with ``user_id=None`` (ROLE_DEFAULTS) — there's no
    per-request user context at the import-time singleton level.
    Per-user model selection goes through
    ``build_async_openai_client_for_role(role, user_id=...)`` from the
    conversation engine instead.
    """
    def __init__(self, role: str):
        self.role = role

    def _delegate(self):
        return get_llm_for_role(self.role)

    def __getattr__(self, name):
        # Forward PUBLIC attribute access (chat, complete, stream_chat, ...)
        # to the underlying delegate. The delegate is re-resolved per
        # call so a runtime selection change (PUT /models/runtime) is
        # observed without recreating this proxy.
        #
        # Reject ANY name starting with ``_`` (dunder + ``_private``).
        # ``mock.patch.__enter__`` probes ``_is_coroutine_marker`` /
        # ``__func__`` / similar on its target to decide between AsyncMock
        # and MagicMock; if we forwarded those, we'd trigger
        # ``get_llm_for_role`` — which raises a hard ValueError when the
        # catalog is cold (test environments without Redis). Refusing
        # introspection lookups with AttributeError lets ``patch`` fall
        # back to its plain-MagicMock branch cleanly.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._delegate(), name)


__all__ = [
    "resolve_api_key",
    "get_async_openai_client",
    "clear_llm_cache_for_provider",
    "profile_ready",
    "list_profiles",
    "validate_role_update",
    "get_llm_for_role",
    "build_async_openai_client_for_role",
    "RuntimeLLMProxy",
    "_serialize_profile",
]
