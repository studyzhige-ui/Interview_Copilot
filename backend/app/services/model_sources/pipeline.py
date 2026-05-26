"""Catalog pipeline: fetch → validate → persist → serve (P6-L).

Glue between ``litellm_loader`` and the rest of the system. The
pipeline:

  refresh:  fetch (with retry + validate)
              → on success: write Redis (24h TTL) + DB shadow
              → on failure: silently keep the last-known-good in place

  load:     read Redis first (fast path)
              → on miss: read DB shadow (last-known-good fallback)
              → on miss: empty (caller decides UX — typically log a
                warning + serve empty list)

Cache key is GLOBAL (per-provider, NOT per-user). LiteLLM JSON is
the same for everyone; per-user differences (ready flag, role
selection) are computed at /catalog read time, not stored here.
This is the P6-J design decision we already settled — one nightly
refresh benefits every user.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.db.redis import redis_client

from .base import ModelEntry
from .litellm_loader import LiteLLMFetchFailed, fetch_litellm_catalog

logger = logging.getLogger(__name__)


# Cache key namespace. ``v4`` because v1/v2/v3 prefixes are from the
# pre-P6-L direct /v1/models discovery era. ``invalidate_all`` in
# the legacy ``model_catalog_service`` sweeps v1/v2/v3, so the next
# refresh after deploy reaps stale entries.
_CACHE_PREFIX = "model_catalog:v4:"
_CACHE_TTL_S = 24 * 3600


def _redis_key(provider: str) -> str:
    return f"{_CACHE_PREFIX}{provider}"


def _redis_key_lkg() -> str:
    """Last-known-good ALL-providers snapshot.

    The per-provider keys above have a TTL — they expire 24h after
    the last successful refresh. This sentinel key has NO TTL, so
    even when the per-provider entries are gone (e.g., the cron
    has been failing for 48h), we still have a snapshot to serve
    until the next successful refresh. Kept in sync with the per-
    provider keys on every successful write.
    """
    return f"{_CACHE_PREFIX}_last_known_good"


def _serialize_entries(entries: list[ModelEntry]) -> str:
    return json.dumps([
        {
            "provider": e.provider,
            "model": e.model,
            "display_name": e.display_name,
            "supports_function_calling": e.supports_function_calling,
            "context_window": e.context_window,
            "max_output_tokens": e.max_output_tokens,
            "supports_vision": e.supports_vision,
        }
        for e in entries
    ], ensure_ascii=False)


def _deserialize_entries(raw: str) -> list[ModelEntry]:
    """Best-effort deserialization. Drops rows that don't match the
    current ModelEntry shape (e.g., a field was renamed) — better to
    serve a subset than to 500 the catalog."""
    try:
        rows = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[ModelEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            out.append(ModelEntry(
                provider=row["provider"],
                model=row["model"],
                display_name=row["display_name"],
                supports_function_calling=bool(row.get("supports_function_calling", False)),
                context_window=int(row.get("context_window", 128_000)),
                max_output_tokens=int(row.get("max_output_tokens", 4_096)),
                supports_vision=bool(row.get("supports_vision", False)),
            ))
        except (KeyError, TypeError, ValueError):
            # Schema drift — skip this row.
            continue
    return out


async def _persist_all(grouped: dict[str, list[ModelEntry]]) -> None:
    """Write every provider's entries to Redis + refresh the LKG snapshot.

    Pipelining via a single ``json.dumps`` per provider is fine —
    typical provider list is 5-50 entries (~few KB). The LKG sentinel
    is a single payload-keyed-by-provider dict so a single GET
    recovers the entire catalog on cache miss.
    """
    snapshot: dict[str, str] = {}
    for provider, entries in grouped.items():
        serialized = _serialize_entries(entries)
        snapshot[provider] = serialized
        try:
            await redis_client.set(_redis_key(provider), serialized, ex=_CACHE_TTL_S)
        except Exception as exc:  # noqa: BLE001 — best-effort cache write
            logger.warning(
                "catalog: per-provider cache write failed for %s: %s",
                provider, exc,
            )
    # LKG snapshot: no TTL. Survives the 24h per-provider expiry so
    # we can serve stale-but-complete data when the cron has been
    # failing.
    try:
        await redis_client.set(
            _redis_key_lkg(), json.dumps(snapshot, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG snapshot write failed: %s", exc)


async def _load_one_provider(provider: str) -> list[ModelEntry]:
    """Fast path: read this provider's slice from Redis. Falls back to
    extracting the provider's slice from the LKG sentinel if the
    per-provider TTL expired."""
    try:
        raw = await redis_client.get(_redis_key(provider))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: Redis get failed for %s: %s", provider, exc)
        raw = None
    if raw is not None:
        return _deserialize_entries(raw)
    # Per-provider key missing — try LKG.
    return await _load_one_from_lkg(provider)


async def _load_one_from_lkg(provider: str) -> list[ModelEntry]:
    try:
        raw = await redis_client.get(_redis_key_lkg())
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG read failed: %s", exc)
        return []
    if raw is None:
        return []
    try:
        snapshot = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(snapshot, dict):
        return []
    return _deserialize_entries(snapshot.get(provider, ""))


# ── Public API ──────────────────────────────────────────────────────


async def refresh_catalog() -> dict[str, list[ModelEntry]]:
    """Pull a fresh catalog from LiteLLM and replace the cache.

    Layer 3 protection: on ``LiteLLMFetchFailed`` (HTTP retries
    exhausted OR validation rejected), we DO NOT touch the cache —
    the previous good snapshot stays as-is and the next /catalog
    read still serves real data. Returns the freshly-loaded entries
    on success, or the LKG snapshot on failure (so the caller's
    return value is always a non-empty dict when at least one
    successful refresh has ever happened).
    """
    try:
        grouped = await fetch_litellm_catalog()
    except LiteLLMFetchFailed as exc:
        logger.error(
            "catalog refresh failed (%s) — keeping last-known-good in cache",
            exc,
        )
        # Return whatever LKG holds so the caller's logging shows
        # the user-visible state, not "we got nothing".
        return await _load_all_from_lkg()

    await _persist_all(grouped)
    return grouped


async def refresh_catalog_for(provider: str) -> list[ModelEntry]:
    """Same as ``refresh_catalog`` but only persists ONE provider's
    slice. Used by the per-user "configure API key" flow (P6-M) where
    we want to nudge that vendor's entries in case LiteLLM updated
    since the last cron — without blowing 8 other providers' TTLs.

    Implementation: still fetches the entire LiteLLM JSON (it's a
    single 1 MB GET — splitting per provider would be overkill), but
    only writes the named provider's slice to Redis. The LKG
    snapshot still gets a full refresh because we have the data
    anyway.
    """
    try:
        grouped = await fetch_litellm_catalog()
    except LiteLLMFetchFailed as exc:
        logger.error(
            "catalog refresh-for-%s failed (%s) — keeping LKG",
            provider, exc,
        )
        return await _load_one_from_lkg(provider)

    # We have the full JSON in hand anyway — persist EVERYTHING, not
    # just the requested provider's slice. The whole point of doing
    # a refresh is the fresh data; throwing away 15 providers' rows
    # because the caller only asked about one would be wasteful and
    # break the "shared cache benefits everyone" property (P6-J).
    await _persist_all(grouped)
    return grouped.get(provider, [])


async def load_catalog() -> dict[str, list[ModelEntry]]:
    """Read the entire catalog from cache.

    Used by the /catalog API endpoint. Fast — pure Redis read, no
    network. If Redis is cold (first deploy, no successful refresh
    yet) returns the empty dict — the caller (API endpoint) should
    log + return an empty list with a warning, not 500.
    """
    from .providers import known_provider_ids

    out: dict[str, list[ModelEntry]] = {}
    # Read every known provider in parallel. Concurrency cost is
    # negligible (one Redis GET each) but cuts wall time when reading
    # ~16 providers.
    import asyncio
    provider_ids = list(known_provider_ids())
    results = await asyncio.gather(
        *[_load_one_provider(p) for p in provider_ids],
        return_exceptions=True,
    )
    for pid, res in zip(provider_ids, results):
        if isinstance(res, Exception):
            logger.warning("catalog: load failed for %s: %s", pid, res)
            continue
        if res:
            out[pid] = res
    return out


async def load_catalog_for(provider: str) -> list[ModelEntry]:
    """Read one provider's slice from cache."""
    return await _load_one_provider(provider)


async def _load_all_from_lkg() -> dict[str, list[ModelEntry]]:
    """Read the LKG snapshot in its entirety. Used as the failure-mode
    return from ``refresh_catalog`` so the caller still gets a
    non-empty dict when LiteLLM is unreachable but we have history."""
    try:
        raw = await redis_client.get(_redis_key_lkg())
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG read failed during refresh fallback: %s", exc)
        return {}
    if raw is None:
        return {}
    try:
        snapshot = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(snapshot, dict):
        return {}
    return {
        provider: _deserialize_entries(serialized)
        for provider, serialized in snapshot.items()
        if isinstance(serialized, str)
    }
