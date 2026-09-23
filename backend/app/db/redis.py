"""Loop-owned Redis clients, with separate blocking-event capacity.

Celery broker/result and rate-limiter pools have separate budgets. These
clients only own application commands; no process-global async connection.
"""

from __future__ import annotations

import redis as sync_redis
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.runtime_resources import current_resources


def get_redis_client(*, blocking: bool = False) -> aioredis.Redis:
    clients = current_resources().redis
    key = "events" if blocking else "commands"
    if key not in clients:
        clients[key] = aioredis.Redis.from_url(
            settings.REDIS_URL,
            max_connections=settings.REDIS_EVENT_POOL_SIZE
            if blocking
            else settings.REDIS_POOL_SIZE,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=20 if blocking else 5,
            health_check_interval=30,
        )
    return clients[key]


sync_redis_client = sync_redis.Redis.from_url(
    settings.REDIS_URL,
    max_connections=max(4, settings.REDIS_POOL_SIZE // 4),
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
)
