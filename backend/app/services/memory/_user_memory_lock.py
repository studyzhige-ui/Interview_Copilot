"""Per-user Redis lock for memory mutations.

Why we need this
----------------
Three independent paths can write to a user's memory docs:

* Realtime extraction (post-turn maintenance, called from chat pipeline)
* Dreaming worker (Celery, fires on a schedule per record)
* User edits via API (future — the management UI)

If two of them run simultaneously, they'll read the same "current
state", each produce a patch list against it, and the second writer
will overwrite the first's changes. The patch protocol's exact-match
defends against silently corrupting unrelated lines, but two parallel
writes of NEW content would still race.

Granularity
-----------
Lock key is per ``user_id`` — different users never block each other.
A single user's mutations serialise.

Lock lifetime
-------------
The lock auto-expires after ``DEFAULT_TIMEOUT`` so a crashed holder
(e.g. worker OOM, network split) can't deadlock the user's memory
forever. The timeout is generous (300s) because:

  * Dreaming may do a slow LLM call to compute patches.
  * Realtime extraction is faster but still does an LLM round-trip.

Callers must finish their work AND release the lock within that
window. If you need longer, raise the timeout for that call site
rather than the global default.

Graceful degradation
--------------------
If Redis is unreachable, ``acquire`` returns a no-op context manager
that does nothing. We log a warning but DON'T crash — losing the lock
for one turn is a degraded mode (occasional last-write-wins), not a
correctness disaster. The patch protocol still prevents silent
corruption of unrelated lines.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from typing import AsyncIterator

from app.db.redis import redis_client
from app.services.memory._metrics import incr as _metric_incr

logger = logging.getLogger(__name__)


def _emit_degraded(user_id: str, reason: str, *, sync: bool) -> None:
    """Fire-and-forget metric so ops can alarm on lock contention.

    ``reason`` is one of ``redis_down`` (Redis unreachable / errored)
    or ``wait_timeout`` (existing holder still running after the
    15s wait budget). ``sync`` distinguishes Celery-side calls from
    API-side calls — useful when triaging which path is degraded.
    """
    _metric_incr(
        "memory.lock_degraded",
        user_id=user_id,
        reason=reason,
        variant="sync" if sync else "async",
    )

# 5 minutes is comfortably above the slowest LLM call we issue inside
# the lock (dreaming, currently ~30-60s). Hardcoded — operators can
# override per-call if they ever need to.
DEFAULT_TIMEOUT_SEC = 300

# Polling cadence while waiting for an existing holder to release.
_POLL_INTERVAL_SEC = 0.05
# Hard ceiling on how long ``acquire`` blocks waiting for the lock.
# Beyond this we proceed anyway — degraded mode. Should be << caller
# timeouts so we don't stall the chat pipeline.
_WAIT_TIMEOUT_SEC = 15.0


def _lock_key(user_id: str) -> str:
    return f"memory_lock:{user_id}"


@contextlib.asynccontextmanager
async def user_memory_lock(
    user_id: str,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
) -> AsyncIterator[None]:
    """Async context manager that holds a Redis lock keyed by ``user_id``.

    Usage::

        async with user_memory_lock(user_id):
            current = load_doc(...)
            new = apply_patches(current, ...)
            save_doc(new)

    On Redis outage: yields immediately without acquiring; logs a
    warning. The caller proceeds in degraded mode.
    """
    if not user_id:
        # No-op lock for empty user_id — shouldn't happen in practice
        # but defensive.
        yield
        return

    key = _lock_key(user_id)
    # Random token so a different worker can't accidentally release
    # this holder's lock. Stored as the value; release compares before
    # delete (compare-and-delete via Lua to keep it atomic).
    token = secrets.token_urlsafe(16)

    acquired = False
    waited = 0.0
    try:
        while waited < _WAIT_TIMEOUT_SEC:
            try:
                # SET key value NX EX seconds → returns True iff set.
                acquired = bool(await redis_client.set(
                    key, token, nx=True, ex=timeout_sec,
                ))
            except Exception as exc:  # noqa: BLE001
                # Redis down — degrade to no-lock mode. One warning,
                # then carry on. We don't want every chat turn to spam
                # the log when Redis is having a bad day.
                logger.warning(
                    "user_memory_lock: Redis unavailable for user=%s, "
                    "proceeding without lock: %s",
                    user_id, exc,
                )
                _emit_degraded(user_id, "redis_down", sync=False)
                yield
                return

            if acquired:
                break
            await asyncio.sleep(_POLL_INTERVAL_SEC)
            waited += _POLL_INTERVAL_SEC

        if not acquired:
            # Couldn't grab the lock within the wait budget. Most likely
            # the previous holder is genuinely doing work (slow LLM)
            # rather than crashed. Proceed without the lock — risk is
            # the patch protocol's exact-match degenerates to
            # last-write-wins for genuinely concurrent edits to the
            # same line. The doc cannot become structurally corrupt.
            logger.warning(
                "user_memory_lock: timed out waiting for user=%s after %.1fs, "
                "proceeding without lock",
                user_id, waited,
            )
            _emit_degraded(user_id, "wait_timeout", sync=False)

        yield
    finally:
        if acquired:
            # Compare-and-delete so we never release someone else's lock
            # (e.g. ours expired, another worker took it, and we then
            # try to release).
            try:
                # Use Lua for atomic check-then-del. Falls back to a
                # plain delete on any error.
                lua = (
                    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                    "return redis.call('DEL', KEYS[1]) "
                    "else return 0 end"
                )
                await redis_client.eval(lua, 1, key, token)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "user_memory_lock: release failed for user=%s "
                    "(token=%s): %s — lock will auto-expire",
                    user_id, token[:6], exc,
                )


# ── Sync sibling for Celery workers ────────────────────────────────────


@contextlib.contextmanager
def user_memory_lock_sync(
    user_id: str,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
):
    """Synchronous version of :func:`user_memory_lock` for Celery.

    Celery tasks run sync. Calling the async lock from inside a Celery
    worker would require an event loop — fragile (a fresh loop per
    task burns memory and confuses the async Redis client). Use this
    instead.

    Implementation note: we lazily import ``redis`` (the sync client
    from the same package) here so the module isn't dragged into
    the async API hot path that already uses ``redis.asyncio``.
    """
    import time
    import redis as sync_redis  # type: ignore[import-untyped]
    from app.core.config import settings

    if not user_id:
        yield
        return

    key = _lock_key(user_id)
    token = secrets.token_urlsafe(16)

    # Construct a sync client. Reuse across calls would help, but this
    # path runs from Celery tasks (one per dream); the connection
    # overhead is negligible compared to the LLM call we're guarding.
    try:
        client = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "user_memory_lock_sync: Redis client init failed for user=%s, "
            "proceeding without lock: %s",
            user_id, exc,
        )
        _emit_degraded(user_id, "redis_down", sync=True)
        yield
        return

    acquired = False
    waited = 0.0
    try:
        while waited < _WAIT_TIMEOUT_SEC:
            try:
                acquired = bool(client.set(key, token, nx=True, ex=timeout_sec))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "user_memory_lock_sync: Redis unavailable for user=%s, "
                    "proceeding without lock: %s",
                    user_id, exc,
                )
                _emit_degraded(user_id, "redis_down", sync=True)
                yield
                return
            if acquired:
                break
            time.sleep(_POLL_INTERVAL_SEC)
            waited += _POLL_INTERVAL_SEC

        if not acquired:
            logger.warning(
                "user_memory_lock_sync: timed out waiting for user=%s after %.1fs, "
                "proceeding without lock",
                user_id, waited,
            )
            _emit_degraded(user_id, "wait_timeout", sync=True)

        yield
    finally:
        if acquired:
            try:
                lua = (
                    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                    "return redis.call('DEL', KEYS[1]) "
                    "else return 0 end"
                )
                client.eval(lua, 1, key, token)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "user_memory_lock_sync: release failed for user=%s "
                    "(token=%s): %s — lock will auto-expire",
                    user_id, token[:6], exc,
                )
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


__all__ = ["user_memory_lock", "user_memory_lock_sync", "DEFAULT_TIMEOUT_SEC"]
