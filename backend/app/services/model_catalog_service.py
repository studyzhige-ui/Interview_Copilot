"""Live LLM model discovery — keeps the catalog fresh without code edits.

Every OpenAI-compatible vendor exposes ``GET /v1/models`` (or close enough)
returning the list of model ids the API key can call. We hit each
configured vendor on demand, cache the result in Redis for 24h, and
expose it as a list of ``DiscoveredModel`` records that ``model_registry``
merges with the curated ``MODEL_PROFILES``.

Curated entries always win on metadata (display_name, description,
context_window, etc.). Auto-discovered models that aren't in the curated
list show up in the dropdown with sensible defaults so users see new
releases the moment the vendor ships them — no waiting for a code update.

Vendors covered: any provider with a curated entry whose ``api_base``
serves an OpenAI-style ``/v1/models`` endpoint. Anthropic uses the same
shape (``/v1/models`` returns ``{"data": [{"id": "..."}, ...]}``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Optional

import httpx

from app.db.redis import redis_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredModel:
    """One model id pulled from a vendor's /v1/models endpoint."""
    provider: str       # e.g. "openai" / "deepseek" / "anthropic"
    model: str          # the bare model id the vendor returns
    api_base: str
    api_key_env: str


# Redis key namespace; bump suffix to invalidate every cached entry.
_CACHE_PREFIX = "model_catalog:v1:"
_CACHE_TTL = 24 * 3600  # 24h — vendors release new models on ~weekly cadence


def _key(provider: str) -> str:
    return f"{_CACHE_PREFIX}{provider}"


# Some vendors put the model list at a non-standard path. The defaults
# below cover the OpenAI-compatible majority; add overrides as needed.
_PATH_OVERRIDES: dict[str, str] = {
    # provider_id → relative path under api_base
    # (empty here means use "/models" — the default)
}


def _models_url(api_base: str, provider: str) -> str:
    base = api_base.rstrip("/")
    path = _PATH_OVERRIDES.get(provider, "models")
    return f"{base}/{path}"


# Some vendors return /v1/models entries that aren't actual chat models
# (embeddings, rerankers, image gen, audio, etc.). We coarsely filter
# those out so the LLM dropdown doesn't get polluted with `whisper-1` or
# `text-embedding-3-small`. The substrings are conservative — false
# positives are better than false negatives because the user can pick
# a "filtered" model by adding it to the curated MODEL_PROFILES.
_NON_CHAT_HINTS = (
    "embedding", "embed-",
    "rerank", "reranker",
    "whisper", "tts-", "audio-",
    "moderation",
    "dall-e", "image-",
    "vision-",
)


def _looks_like_chat_model(model_id: str) -> bool:
    lower = model_id.lower()
    return not any(hint in lower for hint in _NON_CHAT_HINTS)


async def _fetch_one_provider(
    provider: str,
    api_base: str,
    api_key: str,
    timeout: float = 10.0,
) -> list[str]:
    """Issue ``GET {api_base}/models`` with the user's key and parse model ids.

    Returns an empty list on any error (auth failure, network blip, vendor
    that doesn't serve /v1/models). Never raises — discovery is best-effort
    and a flaky vendor must not break ``list_profiles``.
    """
    url = _models_url(api_base, provider)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.info("Model discovery skipped for %s: %s", provider, exc)
        return []

    # OpenAI / Anthropic / DeepSeek / Moonshot / Qwen all use {"data": [{"id": ...}]}.
    # Cohere uses {"models": [{"name": ...}]}. Zhipu uses {"data": [{"id": ...}]}.
    raw = payload.get("data") or payload.get("models") or []
    if not isinstance(raw, list):
        return []
    ids: list[str] = []
    created_by_id: dict[str, int] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("id") or entry.get("name") or entry.get("model")
        if not (isinstance(mid, str) and _looks_like_chat_model(mid)):
            continue
        ids.append(mid)
        # Per-vendor timestamp field naming differs:
        #   OpenAI / DeepSeek / Moonshot → ``created`` as Unix int (seconds)
        #   Anthropic                    → ``created_at`` as ISO-8601 string
        # We coerce either form to a Unix int so the sort key is uniform.
        # Last-write-wins on duplicate ids is fine: vendors don't ship
        # multiple rows for the same id with materially different timestamps.
        ts = _coerce_created(entry.get("created") or entry.get("created_at"))
        if ts is not None:
            created_by_id[mid] = ts
    # Dedupe ids (vendors occasionally ship the same id twice).
    unique_ids = list(dict.fromkeys(ids))
    # Sort: prefer vendor-supplied timestamp desc; for ids without one
    # fall back to reverse-alphabetical. For the version-suffixed naming
    # OpenAI / DeepSeek / Google / Moonshot / Zhipu use, reverse-alpha
    # already lands on newest-first (gpt-5.2 > gpt-5 > gpt-4o > gpt-4.1;
    # glm-5 > glm-4.7 > glm-4.6; gemini-3-pro > gemini-2.5-pro). For
    # Anthropic (claude-opus / claude-sonnet / claude-haiku) reverse-alpha
    # is NOT a meaningful recency signal — the tier name dominates the
    # version — which is exactly why we parse ``created_at`` for them.
    #
    # Two-pass stable sort: first by id reverse-alpha, then by timestamp
    # desc. Python's sort is stable, so within equal timestamps (or both
    # ids missing one) the alpha-desc order from the first pass survives.
    # This handles the "gpt-5" vs "gpt-5.2" prefix-equality case that a
    # tuple-of-negated-ords key would mishandle (the shorter tuple sorts
    # before the longer one in tuple compare, which reverses what we want).
    unique_ids.sort(reverse=True)
    unique_ids.sort(key=lambda mid: created_by_id.get(mid, 0), reverse=True)
    return unique_ids


def _coerce_created(value: object) -> int | None:
    """Normalise a vendor's ``created`` / ``created_at`` field to Unix seconds.

    Returns ``None`` if the value is missing or unparseable — callers fall
    back to reverse-alpha ordering for those ids.
    """
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        # ISO-8601 — Anthropic and a few others. ``fromisoformat`` accepts
        # the trailing ``Z`` only on Python 3.11+, but the project pins
        # 3.11 so we can rely on it. If the string is malformed we just
        # return None (silent fallback to alpha sort).
        from datetime import datetime
        try:
            iso = value.replace("Z", "+00:00")
            return int(datetime.fromisoformat(iso).timestamp())
        except (ValueError, TypeError):
            return None
    return None


async def discover_provider(
    provider: str,
    api_base: str,
    api_key_env: str,
    *,
    force_refresh: bool = False,
) -> list[DiscoveredModel]:
    """Return the list of currently-callable chat models for ``provider``.

    Reads cached result from Redis unless ``force_refresh=True``. Persists
    fresh fetches with a 24h TTL so subsequent ``list_profiles`` calls are
    free.
    """
    import os

    api_key = (os.getenv(api_key_env) or "").strip()
    if not api_key:
        return []

    redis_key = _key(provider)
    if not force_refresh:
        try:
            cached = await redis_client.get(redis_key)
            if cached is not None:
                ids = json.loads(cached)
                return [
                    DiscoveredModel(provider=provider, model=mid,
                                    api_base=api_base, api_key_env=api_key_env)
                    for mid in ids
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Discovery cache read failed for %s: %s", provider, exc)

    ids = await _fetch_one_provider(provider, api_base, api_key)
    try:
        await redis_client.set(redis_key, json.dumps(ids), ex=_CACHE_TTL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Discovery cache write failed for %s: %s", provider, exc)

    return [
        DiscoveredModel(provider=provider, model=mid,
                        api_base=api_base, api_key_env=api_key_env)
        for mid in ids
    ]


async def discover_all(
    provider_specs: list[tuple[str, str, str]],
    *,
    force_refresh: bool = False,
) -> dict[str, list[DiscoveredModel]]:
    """Run discovery for many providers in parallel.

    ``provider_specs`` is a list of ``(provider_id, api_base, api_key_env)``
    tuples — usually built from ``MODEL_PROFILES`` by deduping on provider.
    Returns ``{provider_id: [DiscoveredModel, ...]}``; providers without an
    API key map to an empty list.
    """
    import asyncio

    async def _one(spec: tuple[str, str, str]) -> tuple[str, list[DiscoveredModel]]:
        provider, api_base, api_key_env = spec
        models = await discover_provider(
            provider, api_base, api_key_env, force_refresh=force_refresh,
        )
        return provider, models

    results = await asyncio.gather(*[_one(s) for s in provider_specs])
    return dict(results)


async def invalidate_all() -> int:
    """Drop every cached discovery result. Returns count of keys deleted."""
    deleted = 0
    try:
        async for key in redis_client.scan_iter(match=f"{_CACHE_PREFIX}*", count=200):
            await redis_client.delete(key)
            deleted += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("invalidate_all failed: %s", exc)
    return deleted


__all__ = [
    "DiscoveredModel",
    "discover_provider",
    "discover_all",
    "invalidate_all",
]
