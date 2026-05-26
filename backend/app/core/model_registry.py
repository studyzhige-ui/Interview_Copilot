"""Model registry — runtime view of "what models exist + what's selected".

The universe of available models is sourced live from each vendor's
own ``/v1/models`` endpoint via per-vendor adapters in
``app.services.model_sources.vendors``. Pipeline writes per-provider
entries to Redis (24h TTL) plus a no-TTL last-known-good snapshot;
this module mirrors the cache into a small process-local map for
the sync code paths (LlamaIndex Settings.llm, validators, etc.).

What lives in THIS file:
  * ``ModelProfile`` — runtime row shape used by every chat / agent
    call site as the type
  * ``ROLE_DEFAULTS`` — fallback selection when a user hasn't picked
  * Profile lookup helpers backed by the vendor-adapter pipeline cache
  * Per-user runtime selection (``users.model_selection_json``)
  * API-key resolution priority (user_api_keys → env var fallback)
  * LLM client caches (LlamaIndex + raw AsyncOpenAI), per-user-keyed
  * Per-user api_base / organization / extra_headers override
    (consumes ``user_provider_settings`` from P6-M)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict
from dataclasses import asdict, dataclass
from threading import Lock
from time import time
from typing import Any

from llama_index.llms.openai_like import OpenAILike
from openai import AsyncOpenAI

from app.core.config import settings  # noqa: F401 — kept for back-compat callers
from app.db.redis import sync_redis_client
from app.services.model_sources import (
    PROVIDERS,
    ModelEntry,
    ProviderDefaults,
    get_provider_defaults,
)
from app.services.model_sources.pipeline import (  # internal helpers reused below
    _CACHE_PREFIX,
    _deserialize_entries,
    _redis_key,
    _redis_key_lkg,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelProfile:
    """Runtime row: one (provider, model) entry exposed to chat / agent code.

    Built dynamically by the pipeline (vendor adapter output joined to
    ``ProviderDefaults`` for connection metadata, then polished by the
    curated UX layer for display_name + tier_rank). Consumers — every
    chat call site, every LLM-build call — pull these via
    ``get_profile`` / ``get_profile_for_role``.
    """
    id: str
    provider: str
    display_name: str
    model: str
    api_base: str
    api_key_env: str
    supports_function_calling: bool = False
    description: str = ""
    context_window: int = 128_000
    max_output_tokens: int = 4_096


# ── Role defaults ───────────────────────────────────────────────────────
# Used when (a) we have no user_id (startup, global LlamaIndex Settings.llm),
# OR (b) a user hasn't set anything in ``model_selection_json``. Values
# are profile ids in ``"{provider}/{model}"`` form — must match what the
# vendor's /v1/models endpoint actually returns. If the catalog is cold
# / a default id isn't yet present, ``get_profile_for_role`` falls back
# to the first function-calling profile in the catalog so the system
# never deadlocks on a missing default.
ROLE_DEFAULTS: dict[str, str] = {
    # Three user-facing roles:
    #   primary        — chat / debrief default model (must support function
    #                    calling when the user toggles the AGENT panel button)
    #   agent          — agentic / tool-use chains (function calling required)
    #   mock_interview — drives mock-interview plan + interviewer responses;
    #                    aliased internally as `fast` for back-compat (older
    #                    code paths still read `fast`).
    "primary":        "deepseek/deepseek-chat",
    "fast":           "deepseek/deepseek-chat",
    "agent":          "deepseek/deepseek-chat",
    "mock_interview": "deepseek/deepseek-chat",
}


# ── Profile cache ───────────────────────────────────────────────────────
# Process-local view of the vendor-adapter-driven catalog. Built by
# joining each ``ModelEntry`` from the pipeline cache with the matching
# ``ProviderDefaults``. Sync read path: refreshes from Redis on first
# call AND when older than ``_PROFILE_CACHE_REFRESH_S``. The async
# pipeline write path also calls ``repopulate_profile_cache`` directly
# so refreshes done in this process show up without a Redis round-trip.
_PROFILE_CACHE_REFRESH_S = 60.0
_profile_cache: dict[str, ModelProfile] = {}
_profile_cache_loaded_at: float = 0.0
_profile_cache_lock = Lock()


def _build_profile(entry: ModelEntry, defaults: ProviderDefaults) -> ModelProfile:
    """Join one ``ModelEntry`` to its ``ProviderDefaults`` → ``ModelProfile``.

    Profile id uses the ``"{provider}/{model}"`` form so two vendors
    that happen to ship a same-named model (e.g. ``llama-3.1-70b``
    available via both Together AI and NVIDIA NIM) get distinct
    profile ids the user can select between.
    """
    return ModelProfile(
        id=f"{defaults.id}/{entry.model}",
        provider=defaults.id,
        display_name=entry.display_name,
        model=entry.model,
        api_base=defaults.default_api_base,
        api_key_env=defaults.api_key_env,
        supports_function_calling=entry.supports_function_calling,
        description="",
        context_window=entry.context_window,
        max_output_tokens=entry.max_output_tokens,
    )


def _load_entries_from_sync_redis() -> dict[str, list[ModelEntry]]:
    """Sync read of the pipeline's cached entries.

    We can't ``await`` from the sync ``get_profile`` path (called from
    LlamaIndex Settings.llm initialisation, validators, etc.) so we use
    the parallel sync Redis client. The async pipeline still owns the
    cache writes — this is a read-only sync mirror.
    """
    out: dict[str, list[ModelEntry]] = {}
    try:
        # Try per-provider keys first.
        for provider_id in PROVIDERS:
            raw = sync_redis_client.get(_redis_key(provider_id))
            if raw is None:
                continue
            entries = _deserialize_entries(raw)
            if entries:
                out[provider_id] = entries
        if out:
            return out
        # All per-provider keys missing — try the LKG sentinel.
        raw_lkg = sync_redis_client.get(_redis_key_lkg())
        if raw_lkg is None:
            return out
        try:
            snapshot = json.loads(raw_lkg)
        except (json.JSONDecodeError, TypeError):
            return out
        if not isinstance(snapshot, dict):
            return out
        for provider_id, serialized in snapshot.items():
            if not isinstance(serialized, str):
                continue
            entries = _deserialize_entries(serialized)
            if entries:
                out[provider_id] = entries
    except Exception as exc:  # noqa: BLE001 — Redis outage shouldn't crash chat
        logger.warning("model_registry: sync catalog read failed: %s", exc)
    return out


def _rebuild_cache_locked(grouped: dict[str, list[ModelEntry]]) -> None:
    """Replace the in-process profile cache. Caller MUST hold the lock."""
    new_cache: dict[str, ModelProfile] = {}
    for provider_id, entries in grouped.items():
        defaults = get_provider_defaults(provider_id)
        if defaults is None:
            continue
        for entry in entries:
            profile = _build_profile(entry, defaults)
            new_cache[profile.id] = profile
    _profile_cache.clear()
    _profile_cache.update(new_cache)


def repopulate_profile_cache(grouped: dict[str, list[ModelEntry]]) -> None:
    """Public hook for the pipeline's async refresh path.

    Called from ``app.services.model_sources.pipeline.refresh_catalog``
    after a successful Redis write so this process's sync cache stays
    aligned without a separate Redis round-trip.
    """
    global _profile_cache_loaded_at
    with _profile_cache_lock:
        _rebuild_cache_locked(grouped)
        _profile_cache_loaded_at = time()


def _ensure_cache_warm() -> dict[str, ModelProfile]:
    """Return the profile cache, refreshing from Redis if stale.

    Stale = empty (first call) OR older than ``_PROFILE_CACHE_REFRESH_S``.
    Refresh is sync (sync_redis_client). If Redis is unreachable, we
    keep serving whatever we already have — callers must tolerate an
    empty cache gracefully (typically by falling back to ROLE_DEFAULTS
    or returning an empty catalog).
    """
    global _profile_cache_loaded_at
    now = time()
    with _profile_cache_lock:
        if _profile_cache and (now - _profile_cache_loaded_at) < _PROFILE_CACHE_REFRESH_S:
            return _profile_cache
    # Slow path — Redis read outside the lock (Redis ops are blocking
    # I/O; holding the lock across them would serialise all chat
    # requests behind one process).
    grouped = _load_entries_from_sync_redis()
    with _profile_cache_lock:
        if grouped:
            _rebuild_cache_locked(grouped)
            _profile_cache_loaded_at = now
        elif not _profile_cache:
            # Cold start AND Redis empty (e.g., very first deploy before
            # any cron has run). Bump the timestamp so we don't thrash
            # Redis on every chat — wait the refresh interval before
            # trying again.
            _profile_cache_loaded_at = now
        return _profile_cache


def _get_all_profiles() -> dict[str, ModelProfile]:
    """Snapshot of the current profile cache, warmed on demand."""
    return _ensure_cache_warm()


# ── Selection (per-user role → profile_id) ──────────────────────────────


_selection_lock = Lock()
_llm_cache: dict[tuple[str, str], Any] = {}


def _normalize_selection(raw: dict[str, str]) -> dict[str, str]:
    """Clamp a raw selection dict to known-valid profile ids.

    Unknown ids fall back to ROLE_DEFAULTS for that role. Agent role
    additionally requires function-calling support; a non-FC selection
    is replaced by ROLE_DEFAULTS["agent"]. Retired alias safeguards
    (the legacy ``deepseek-chat`` / ``deepseek-reasoner`` short ids
    from pre-P6-L) are still dropped so old persisted selections
    upgrade cleanly without surfacing as "missing profile" errors.
    """
    profiles = _get_all_profiles()
    selection = dict(ROLE_DEFAULTS)
    for role in ROLE_DEFAULTS:
        candidate = raw.get(role)
        # Drop pre-P6-L bare ids (no "provider/" prefix). They aren't
        # valid in the new "provider/model" id scheme.
        if not candidate or "/" not in candidate:
            continue
        if candidate in profiles:
            selection[role] = candidate

    # Agent role guard: if the selected agent profile doesn't support
    # function calling (or isn't in the cache), fall back to the role
    # default. The lookup tolerates a missing default too — we just
    # keep whatever's in selection and let downstream surface the error.
    agent_profile = profiles.get(selection["agent"])
    if agent_profile is None or not agent_profile.supports_function_calling:
        selection["agent"] = ROLE_DEFAULTS["agent"]
    return selection


def _load_user_selection(user_id: str) -> dict[str, str]:
    """Read a user's persisted ``model_selection_json`` from the DB."""
    from app.db.database import SessionLocal
    from app.models.user import User

    try:
        with SessionLocal() as db:
            row = (
                db.query(User.model_selection_json)
                .filter(User.username == user_id)
                .first()
            )
        if row is None or not row[0]:
            return dict(ROLE_DEFAULTS)
        data = json.loads(row[0])
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load model selection for user=%s: %s", user_id, exc,
        )
    return dict(ROLE_DEFAULTS)


def _save_user_selection(user_id: str, selection: dict[str, str]) -> None:
    from app.db.database import SessionLocal
    from app.models.user import User

    payload = json.dumps(selection, ensure_ascii=False)
    with SessionLocal() as db:
        db.query(User).filter(User.username == user_id).update(
            {"model_selection_json": payload},
            synchronize_session=False,
        )
        db.commit()


def get_runtime_selection(user_id: str | None = None) -> dict[str, str]:
    """Return the active model selection for ``user_id``.

    Without ``user_id`` (startup contexts) returns ROLE_DEFAULTS. With
    it, reads ``users.model_selection_json`` and falls back to defaults
    on any error.
    """
    with _selection_lock:
        if user_id is None:
            return dict(ROLE_DEFAULTS)
        return _normalize_selection(_load_user_selection(user_id))


def persist_runtime_selection(
    selection: dict[str, str], user_id: str,
) -> dict[str, str]:
    """Save ``selection`` for ``user_id``. Returns the normalized form."""
    normalized = _normalize_selection(selection)
    with _selection_lock:
        _save_user_selection(user_id, normalized)
        # Clear the (role, profile_id) → LLM-instance cache so the
        # user's next chat constructs a fresh LLM honouring the new
        # selection.
        _llm_cache.clear()
    return normalized


def update_runtime_selection(
    updates: dict[str, str], user_id: str,
) -> dict[str, str]:
    current = get_runtime_selection(user_id)
    current.update({k: v for k, v in updates.items() if v is not None})
    return persist_runtime_selection(current, user_id)


def get_profile(profile_id: str) -> ModelProfile:
    profiles = _get_all_profiles()
    if profile_id not in profiles:
        raise ValueError(f"Unknown model profile: {profile_id}")
    return profiles[profile_id]


def get_profile_for_role(role: str, user_id: str | None = None) -> ModelProfile:
    """Resolve role → ModelProfile.

    Falls back to ROLE_DEFAULTS if the user's selection points at a
    profile that's no longer in the catalog (rare: vendor retired the
    model since last refresh). Falls back to "first function-calling
    profile in the catalog" if even ROLE_DEFAULTS isn't present (e.g.,
    the vendor's /v1/models temporarily dropped that id).
    """
    profiles = _get_all_profiles()
    selection = get_runtime_selection(user_id)
    pid = selection.get(role, ROLE_DEFAULTS[role])
    if pid in profiles:
        return profiles[pid]
    # Fallback chain.
    default_pid = ROLE_DEFAULTS.get(role)
    if default_pid and default_pid in profiles:
        return profiles[default_pid]
    if role == "agent":
        for p in profiles.values():
            if p.supports_function_calling:
                return p
    for p in profiles.values():
        return p
    raise ValueError(
        f"No profile available for role={role!r} — catalog is empty. "
        "Run scripts/refresh_models.py or wait for the daily Celery beat.",
    )


# ── API-key resolution ──────────────────────────────────────────────────


def resolve_api_key(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolve the API key to use when calling this profile.

    Priority:
      1) ``user_api_keys`` row for (user_id, provider) — encrypted DB
      2) ``os.environ[profile.api_key_env]`` — legacy / single-tenant path

    Returns ``""`` when nothing resolves; downstream auth then fails
    visibly instead of papering over a config bug.
    """
    if user_id:
        try:
            from app.services.user_api_key_service import get_user_api_key_plaintext
            user_key = get_user_api_key_plaintext(user_id, profile.provider)
            if user_key:
                return user_key
        except Exception as exc:  # noqa: BLE001
            logger.warning("user_api_key lookup failed: %s", exc)
    return os.getenv(profile.api_key_env, "")


@dataclass(frozen=True)
class _UserProviderOverrides:
    """Cached snapshot of one (user, provider) row used at chat-completion
    time. Pulled from ``user_provider_settings``."""
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
        from app.models.user_provider_settings import UserProviderSettings
        from app.services.user_provider_settings_service import parse_extra_headers

        with SessionLocal() as db:
            row = (
                db.query(
                    UserProviderSettings.api_base_override,
                    UserProviderSettings.organization_id,
                    UserProviderSettings.extra_headers_json,
                )
                .filter(
                    UserProviderSettings.user_id == user_id,
                    UserProviderSettings.provider == profile.provider,
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
            "user_provider_settings lookup failed for user=%s provider=%s: %s",
            user_id, profile.provider, exc,
        )
        return _NO_OVERRIDES


def _resolve_api_base(profile: ModelProfile, user_id: str | None = None) -> str:
    """Resolve the api_base to call, honouring per-user overrides.

    P6-M adds ``user_provider_settings.api_base_override`` for users on
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
    with _selection_lock:
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


def clear_llm_cache_for_provider(provider: str) -> None:
    """Drop cached LLM + AsyncOpenAI instances for ``provider``.

    Called after a user changes their API key / api_base so the next
    LLM call rebuilds with fresh credentials. We can't iterate
    ``_get_all_profiles`` synchronously here without risking a Redis
    call inside a lock, so we use a string-prefix check on the
    profile id (always ``"{provider}/..."``).
    """
    prefix = f"{provider}/"
    with _selection_lock:
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

    With ``user_id`` we check ``user_api_keys`` first, then env.
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
    profiles = _get_all_profiles()
    selection = get_runtime_selection(user_id)
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
    profile = get_profile_for_role(role, user_id=user_id)
    cache_key = (role, profile.id)
    with _selection_lock:
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
    profile = get_profile_for_role(role, user_id=user_id)
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
