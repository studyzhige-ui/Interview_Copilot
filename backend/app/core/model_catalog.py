"""Process-local view of the vendor-adapter-driven model catalog.

The universe of available models is sourced live from each vendor's
own ``/v1/models`` endpoint via per-vendor adapters in
``app.services.model_sources.vendors``. The pipeline writes
per-provider entries to Redis (24h TTL) plus a no-TTL last-known-good
snapshot. THIS module mirrors that cache into a small process-local
map for the sync code paths (LlamaIndex Settings.llm, validators,
etc.) so a chat request doesn't pay a Redis round-trip every call.

What lives here:
  * ``ModelProfile``      — runtime row shape used by every chat /
                            agent call site as the type
  * ``ROLE_DEFAULTS``     — fallback selection when a user hasn't
                            picked one yet
  * Profile-cache helpers — lazy refresh from Redis; the async
                            pipeline calls ``repopulate_profile_cache``
                            after a successful write so this process
                            sees the new entries without a round-trip
  * ``get_profile``       — by-id lookup against the warmed cache
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from threading import Lock
from time import time

from app.db.redis import sync_redis_client
from app.services.model_sources import (
    PROVIDERS,
    ModelEntry,
    ProviderDefaults,
    get_provider_defaults,
)
from app.services.model_sources.pipeline import (  # internal helpers reused below
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
        logger.warning("model_catalog: sync catalog read failed: %s", exc)
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


def get_profile(profile_id: str) -> ModelProfile:
    profiles = _get_all_profiles()
    if profile_id not in profiles:
        raise ValueError(f"Unknown model profile: {profile_id}")
    return profiles[profile_id]


__all__ = [
    "ModelProfile",
    "ROLE_DEFAULTS",
    "repopulate_profile_cache",
    "_get_all_profiles",
    "get_profile",
]
