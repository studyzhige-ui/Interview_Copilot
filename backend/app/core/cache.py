"""Tiny Redis-backed cache helper for read-mostly hot paths.

Pattern: ``cached(key, ttl, loader)`` — checks Redis, calls ``loader()`` on
miss, stores the JSON-serialised result, returns it. Plus an
``invalidate(*keys)`` for write paths to drop stale entries after mutating
state.

Why not functools.lru_cache: that's per-process and doesn't survive
restarts. With multi-worker uvicorn (P5-1) every worker would have its
own LRU and an API-key change in one worker wouldn't propagate. Redis
is shared, so all workers see the same view + invalidation is one
``DEL`` call.

Why not a fancier cache library: this is 30 lines, has zero deps beyond
the existing redis client, and is the right shape for the 2–3 endpoints
we actually want to cache. Don't add an LRU library to chase 1% wins.
"""

from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable, TypeVar

from app.db.redis import redis_client

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Versioned namespace — bump the suffix to invalidate every cached entry
# at once (e.g. when the response shape of a cached endpoint changes).
_PREFIX = "cache:v1:"


def _key(name: str) -> str:
    return f"{_PREFIX}{name}"


async def cached(
    name: str,
    ttl: int,
    loader: Callable[[], Awaitable[T]],
) -> T:
    """Read-through cache. Returns the cached value on hit, calls loader on miss.

    `loader` MUST be async + idempotent — it may be invoked concurrently
    from multiple workers when they all miss at the same time. We don't
    use a lock because the worst case is N parallel computes for the same
    key, which is fine for the workloads we target.

    Cache misses on Redis errors fall through to ``loader()`` so a Redis
    outage degrades to "no cache" instead of "site down".
    """
    redis_key = _key(name)
    try:
        raw = await redis_client.get(redis_key)
        if raw is not None:
            return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache get failed for %s, falling through: %s", name, exc)

    value = await loader()

    try:
        await redis_client.set(redis_key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:  # noqa: BLE001
        # Don't propagate cache-write failures to the caller — they got the
        # right value, we just couldn't memoise it.
        logger.warning("cache set failed for %s: %s", name, exc)

    return value


async def invalidate(*names: str) -> None:
    """Drop one or more cache entries. Called from write paths after mutating state."""
    if not names:
        return
    keys = [_key(n) for n in names]
    try:
        await redis_client.delete(*keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache invalidate failed for %s: %s", names, exc)


async def invalidate_prefix(prefix: str) -> int:
    """Drop every cache entry whose name starts with ``prefix``.

    Useful when one mutation invalidates many derived keys (e.g. saving a
    user's API key invalidates every catalog entry for that user). Uses
    SCAN so a big keyspace doesn't block Redis. Returns the number of
    keys deleted.
    """
    pattern = f"{_PREFIX}{prefix}*"
    deleted = 0
    try:
        async for key in redis_client.scan_iter(match=pattern, count=200):
            await redis_client.delete(key)
            deleted += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("cache invalidate_prefix failed for %s: %s", prefix, exc)
    return deleted


__all__ = ["cached", "invalidate", "invalidate_prefix"]
