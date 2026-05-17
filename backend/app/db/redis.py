"""Unified Redis client + connection pool.

Single source of truth for the app's Redis access. Every module that needs
Redis (verification codes, rate limiter, ad-hoc cache, future pub/sub)
imports ``redis_client`` from here instead of opening its own connection,
so connection count stays bounded and pool config lives in one place.

Sync vs. async: the FastAPI / WS hot path is async, so we expose an async
client. Celery tasks use a sync client (a separate small pool) since
``celery_app.py`` uses the same REDIS_URL as broker/result backend and
runs in sync workers.
"""

from __future__ import annotations

import redis as sync_redis
import redis.asyncio as aioredis

from app.core.config import settings

# ── Async pool — used by FastAPI request handlers and WS endpoints ────
_async_pool = aioredis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=settings.REDIS_POOL_SIZE,
    decode_responses=True,
)
redis_client: aioredis.Redis = aioredis.Redis(connection_pool=_async_pool)


async def get_redis() -> aioredis.Redis:
    """FastAPI dependency form — yields the shared async client.

    Note: don't ``await client.close()`` in the dependency; the pool is
    process-global and reused across requests.
    """
    return redis_client


# ── Sync pool — used by Celery workers and any sync startup hook ─────
_sync_pool = sync_redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=max(8, settings.REDIS_POOL_SIZE // 4),
    decode_responses=True,
)
sync_redis_client: sync_redis.Redis = sync_redis.Redis(connection_pool=_sync_pool)


__all__ = ["redis_client", "sync_redis_client", "get_redis"]
