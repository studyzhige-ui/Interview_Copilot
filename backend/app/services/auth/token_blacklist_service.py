"""JWT revocation via Redis blacklist.

Every issued token carries a ``jti`` claim (UUID hex). On logout / refresh-
rotation we mark the jti as revoked in Redis with a TTL equal to the
token's remaining lifetime — once the JWT itself expires the entry is
auto-evicted, no cleanup needed.

The blacklist is consulted on every authenticated request via the
``is_revoked`` check in ``app.core.security.get_current_user`` and on
``/auth/refresh`` for the old refresh token.

Key shape:  revoked_jti:<jti>  → "1"

Failure mode: if Redis is unreachable the safe default is to *deny* —
better to ask the user to re-login than to honour a revoked token. The
check raises so the auth dependency converts it to 401.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.db.redis import redis_client

logger = logging.getLogger(__name__)

_PREFIX = "revoked_jti:"


def _key(jti: str) -> str:
    return f"{_PREFIX}{jti}"


def _ttl_from_exp(exp: int | float | None) -> int:
    """Return seconds remaining until ``exp`` (UNIX timestamp). Floor at 1."""
    if not exp:
        # Token without exp → use a 7-day TTL as upper bound; longer than any
        # legitimately-issued refresh token in this project.
        return 7 * 24 * 3600
    remaining = int(exp) - int(time.time())
    return max(1, remaining)


async def revoke(jti: str, exp: int | float | None = None) -> None:
    """Mark ``jti`` as revoked. ``exp`` is the JWT's ``exp`` claim; if given,
    the Redis TTL matches so the key auto-cleans when the token would expire.
    """
    if not jti:
        return
    try:
        await redis_client.set(_key(jti), "1", ex=_ttl_from_exp(exp))
    except Exception as exc:  # noqa: BLE001
        # Don't break the request flow on Redis hiccup — log loudly so this
        # surfaces during monitoring; the token will still expire naturally.
        logger.error("Failed to revoke jti=%s in Redis: %s", jti, exc)


async def is_revoked(jti: str | None) -> bool:
    """Return True if the jti has been revoked. Tokens without jti are
    treated as not revoked (backward-compat for tokens issued before this
    rollout); they expire naturally on their own short access TTL.
    """
    if not jti:
        return False
    try:
        val = await redis_client.get(_key(jti))
        return val is not None
    except Exception as exc:  # noqa: BLE001
        # Fail-closed: a Redis outage shouldn't let revoked tokens through.
        logger.error("Blacklist check failed for jti=%s; failing closed: %s", jti, exc)
        return True


def utcnow_ts() -> int:
    """Standard helper for token issuers — current UTC as integer seconds."""
    return int(datetime.now(timezone.utc).timestamp())


__all__ = ["revoke", "is_revoked", "utcnow_ts"]
