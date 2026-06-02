"""Catalog pipeline: per-vendor /v1/models → curated → cache → serve.

Each vendor's own ``/v1/models`` endpoint is the authoritative data
source — no third-party dependency, no upstream lag. The ``vendors/``
package holds one ``VendorAdapterSpec`` per vendor; this pipeline
orchestrates them.

  refresh_catalog():
    For each spec in vendors.ALL_SPECS:
      resolve api_base + api_key (user_api_keys → env fallback)
      fetch_one_vendor(spec) — runs the spec's chat_filter + sort
      apply_overrides() — curated UX layer (display name / tier / hide)
      on success: persist to Redis (per-provider key + LKG sentinel)
      on failure: that vendor falls back to its LKG slice; others
                  proceed independently

  load_catalog():
    Pure Redis read — never hits the network. Used by /catalog
    endpoint. Falls back through: per-provider key → LKG sentinel →
    repo-shipped seed_catalog.json → empty.

Cache key is GLOBAL (per-provider, not per-user). A vendor's
/v1/models returns the same list regardless of which key signed the
request, so a shared cache means one nightly refresh warms the entry
every user reads from. Per-user differences (ready / selected_for /
enabled) are computed at /catalog read time, not stored here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from app.db.redis import redis_client

from .base import ModelEntry
from .curated import apply_overrides
from .providers import PROVIDERS, get_provider_defaults
from .vendors import ALL_SPECS, VendorAdapterSpec, fetch_one_vendor
from .vendors.base import VendorFetchFailed

logger = logging.getLogger(__name__)


# Seed catalog: a snapshot of the live catalog at packaging time,
# shipped with the repo so a fresh `git clone` shows a populated
# Models page even before the user configures any API keys. Loaded
# once at module import; the in-memory copy is the third fallback
# layer (per-provider Redis → LKG sentinel → seed → empty).
#
# Models served from the seed always show as `ready=false` because
# the user has no key — that's correct UX (browse to see what's
# available; configure a key to actually use).
#
# Regenerate via: scripts/refresh_models.py --write-seed
_SEED_PATH = Path(__file__).parent / "seed_catalog.json"


def _load_seed_catalog() -> dict[str, list[ModelEntry]]:
    """Read seed_catalog.json once at import. Returns empty dict if
    the file is absent or malformed — fresh repos may not have it."""
    if not _SEED_PATH.exists():
        return {}
    try:
        with _SEED_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("seed_catalog.json load failed: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[ModelEntry]] = {}
    for provider, entries in raw.items():
        if not isinstance(entries, list):
            continue
        deserialized = _deserialize_entries(json.dumps(entries, ensure_ascii=False))
        if deserialized:
            out[provider] = deserialized
    return out


# Computed lazily so we can import _deserialize_entries below. See
# the module-end `_SEED_CATALOG = _load_seed_catalog()` line.
_SEED_CATALOG: dict[str, list[ModelEntry]] = {}


# Cache key namespace. Versioned so a schema-incompatible payload
# change (renamed field, etc.) doesn't blow up readers — bump the
# suffix and ``invalidate_all`` will reap older variants on the
# first refresh.
_CACHE_PREFIX = "model_catalog:v5:"
_CACHE_TTL_S = 24 * 3600


def _redis_key(provider: str) -> str:
    return f"{_CACHE_PREFIX}{provider}"


def _redis_key_lkg() -> str:
    """Last-known-good ALL-providers snapshot. NO TTL — survives the
    24h per-provider expiry so we can still serve stale-but-complete
    data when the cron has been failing for >24h."""
    return f"{_CACHE_PREFIX}_last_known_good"


# Gemini's chat-completion endpoint and its list-models endpoint
# live at DIFFERENT paths on the same host:
#   chat:        /v1beta/openai/chat/completions
#   list models: /v1beta/models
# PROVIDERS['gemini'].default_api_base points at the chat path so
# the chat client works out of the box; we adjust here for the
# list-models fetch. Other vendors don't have this split.
_GEMINI_LIST_MODELS_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _resolve_list_models_base(spec: VendorAdapterSpec, defaults_api_base: str) -> str:
    """Some vendors split list-models / chat into different paths.
    For all-but-one, the spec's models_path appended to the provider's
    default_api_base gives the right URL; Gemini is the exception."""
    if spec.provider == "gemini":
        return os.getenv("GOOGLE_LIST_MODELS_BASE", _GEMINI_LIST_MODELS_BASE)
    return defaults_api_base


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
    current ModelEntry shape (schema drift) — better to serve a
    subset than to 500 the catalog."""
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
            continue
    return out


async def _persist_all(grouped: dict[str, list[ModelEntry]]) -> None:
    """Write every provider's entries to Redis + refresh the LKG snapshot."""
    snapshot: dict[str, str] = {}
    for provider, entries in grouped.items():
        serialized = _serialize_entries(entries)
        snapshot[provider] = serialized
        try:
            await redis_client.set(_redis_key(provider), serialized, ex=_CACHE_TTL_S)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "catalog: per-provider cache write failed for %s: %s",
                provider, exc,
            )
    try:
        await redis_client.set(
            _redis_key_lkg(), json.dumps(snapshot, ensure_ascii=False),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG snapshot write failed: %s", exc)


async def _load_one_provider(provider: str) -> list[ModelEntry]:
    """3-layer fallback: per-provider Redis → LKG sentinel → seed snapshot.

    The seed is the static JSON shipped with the repo so a fresh
    `git clone` shows a populated catalog even before any vendor
    fetch has run. Models served from the seed will still show as
    ``ready=false`` because the user has no key — accurate UX.
    """
    try:
        raw = await redis_client.get(_redis_key(provider))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: Redis get failed for %s: %s", provider, exc)
        raw = None
    if raw is not None:
        return _deserialize_entries(raw)
    lkg_entries = await _load_one_from_lkg(provider)
    if lkg_entries:
        return lkg_entries
    # Final fallback: the shipped seed. Always available unless someone
    # deleted seed_catalog.json or this provider isn't in the snapshot.
    return list(_SEED_CATALOG.get(provider, []))


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


async def _load_all_from_lkg() -> dict[str, list[ModelEntry]]:
    """Full-catalog LKG read. Falls back to the shipped seed snapshot
    when no LKG exists — so even a brand-new deploy with cold Redis
    serves something for the /catalog endpoint."""
    try:
        raw = await redis_client.get(_redis_key_lkg())
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG read failed during refresh fallback: %s", exc)
        raw = None
    if raw is not None:
        try:
            snapshot = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            snapshot = None
        if isinstance(snapshot, dict):
            return {
                provider: _deserialize_entries(serialized)
                for provider, serialized in snapshot.items()
                if isinstance(serialized, str)
            }
    # Final fallback: shipped seed.
    return {p: list(es) for p, es in _SEED_CATALOG.items()}


def _resolve_key_for_provider(provider: str, user_id: str | None) -> str:
    """API-key resolution priority for fetching /v1/models:
       1) user_api_keys[user_id, provider] (encrypted DB row, P4-E)
       2) env var named by ProviderDefaults.api_key_env (P6-L)
    """
    defaults = get_provider_defaults(provider)
    if defaults is None:
        return ""
    if user_id:
        try:
            from app.services.auth.user_api_key_service import get_user_api_key_plaintext
            key = get_user_api_key_plaintext(user_id, provider)
            if key:
                return key
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "user_api_key lookup failed for %s/%s: %s",
                user_id, provider, exc,
            )
    return (os.getenv(defaults.api_key_env) or "").strip()


# ── Public API ──────────────────────────────────────────────────────


async def refresh_catalog(
    *, user_id: str | None = None,
) -> dict[str, list[ModelEntry]]:
    """Re-fetch every vendor's /v1/models in parallel and replace the cache.

    Per-vendor failure does NOT block other vendors — each adapter is
    awaited independently. A vendor whose fetch raises
    ``VendorFetchFailed`` falls back to its slice of the last-known-good
    snapshot (if any), so a single outage doesn't blank that card.

    ``user_id`` is forwarded to the key resolver so a user with their
    own UI-saved key gets a fetch through THEIR key (the user can
    see fine-tunes / preview models their personal account unlocked).
    Without a user_id (cron context), env-only fallback.
    """
    specs = ALL_SPECS
    api_keys = {s.provider: _resolve_key_for_provider(s.provider, user_id) for s in specs}

    async def _one(spec: VendorAdapterSpec) -> tuple[str, list[ModelEntry], bool]:
        defaults = get_provider_defaults(spec.provider)
        if defaults is None:
            return spec.provider, [], False
        api_key = api_keys[spec.provider]
        if not api_key:
            # No key for this vendor — serve the shipped seed snapshot
            # so the user still sees what's available (cards with
            # ready=false). They configure a key and re-refresh to
            # replace with live data.
            seed_entries = list(_SEED_CATALOG.get(spec.provider, []))
            return spec.provider, seed_entries, True
        api_base = _resolve_list_models_base(spec, defaults.default_api_base)
        try:
            entries = await fetch_one_vendor(spec, api_base, api_key)
        except VendorFetchFailed as exc:
            logger.error("catalog: %s fetch failed (%s) — using LKG", spec.provider, exc)
            entries = await _load_one_from_lkg(spec.provider)
            # LKG entries were stored AFTER curated overrides applied
            # (we persist post-curation), so no second pass here.
            return spec.provider, entries, False
        # Apply curated UX layer: hide variant noise + dated aliases,
        # override display names, re-sort by tier_rank. Stored to
        # Redis post-curation so /catalog reads serve the polished
        # view directly.
        entries = apply_overrides(spec.provider, entries)
        return spec.provider, entries, True

    results = await asyncio.gather(*[_one(s) for s in specs])

    fresh: dict[str, list[ModelEntry]] = {}
    success_count = 0
    for provider, entries, ok in results:
        fresh[provider] = entries
        if ok:
            success_count += 1

    # Only persist when at least ONE vendor returned data. If everything
    # failed (e.g. global network outage), keep whatever's in the cache.
    if any(entries for entries in fresh.values()):
        await _persist_all(fresh)
        logger.info(
            "catalog refresh: %d vendors OK, %d total models",
            success_count, sum(len(e) for e in fresh.values()),
        )
    else:
        logger.error("catalog refresh: ALL vendors failed — cache untouched")
        return await _load_all_from_lkg()
    return fresh


async def refresh_catalog_for(
    provider: str, *, user_id: str | None = None,
) -> list[ModelEntry]:
    """Refresh ONE vendor's entries. Used by the "user just configured
    their key" hook so the catalog reflects the new state immediately
    instead of waiting for the daily Celery beat."""
    spec = next((s for s in ALL_SPECS if s.provider == provider), None)
    if spec is None:
        return []
    defaults = get_provider_defaults(provider)
    if defaults is None:
        return []
    api_key = _resolve_key_for_provider(provider, user_id)
    if not api_key:
        return []
    api_base = _resolve_list_models_base(spec, defaults.default_api_base)
    try:
        entries = await fetch_one_vendor(spec, api_base, api_key)
        entries = apply_overrides(provider, entries)
    except VendorFetchFailed as exc:
        logger.error("catalog: refresh-for-%s failed (%s) — using LKG", provider, exc)
        return await _load_one_from_lkg(provider)
    # Persist just this provider's slice + update LKG.
    try:
        await redis_client.set(
            _redis_key(provider), _serialize_entries(entries), ex=_CACHE_TTL_S,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: per-provider cache write failed for %s: %s", provider, exc)
    # Update LKG snapshot — merge this provider's fresh slice with
    # whatever's already cached for other providers.
    try:
        existing = await _load_all_from_lkg()
        existing[provider] = entries
        snapshot = {p: _serialize_entries(es) for p, es in existing.items()}
        await redis_client.set(_redis_key_lkg(), json.dumps(snapshot, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.warning("catalog: LKG merge for %s failed: %s", provider, exc)
    return entries


async def load_catalog() -> dict[str, list[ModelEntry]]:
    """Read the entire catalog from cache. Pure Redis read, no network."""
    provider_ids = list(PROVIDERS.keys())
    results = await asyncio.gather(
        *[_load_one_provider(p) for p in provider_ids],
        return_exceptions=True,
    )
    out: dict[str, list[ModelEntry]] = {}
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


async def invalidate_all() -> int:
    """Drop every cached discovery result across all prefix versions.
    Used by the manual ``POST /models/refresh-catalog`` endpoint and
    legacy callers that still call this name."""
    deleted = 0
    # Sweep current + every historical prefix so leftover entries
    # from earlier keying schemes get reaped on first refresh.
    patterns = (
        f"{_CACHE_PREFIX}*",
        "model_catalog:v4:*",
        "model_catalog:v3:*",
        "model_catalog:v2:*",
        "model_catalog:v1:*",
    )
    try:
        for pattern in patterns:
            async for key in redis_client.scan_iter(match=pattern, count=200):
                await redis_client.delete(key)
                deleted += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("invalidate_all failed: %s", exc)
    return deleted


__all__ = [
    "refresh_catalog",
    "refresh_catalog_for",
    "load_catalog",
    "load_catalog_for",
    "invalidate_all",
]


# Module-load: populate the seed cache. Done at the bottom so
# _deserialize_entries (used inside _load_seed_catalog) is defined.
# Failure is non-fatal — empty seed just means new clones get blank
# cards until they configure a key + refresh.
_SEED_CATALOG = _load_seed_catalog()
if _SEED_CATALOG:
    logger.info(
        "model_catalog seed loaded: %d providers, %d total models",
        len(_SEED_CATALOG), sum(len(es) for es in _SEED_CATALOG.values()),
    )
