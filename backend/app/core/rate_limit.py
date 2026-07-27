"""Centralised rate-limit configuration.

Built on slowapi (Redis-backed) so quotas are shared across uvicorn workers.
Authenticated traffic is keyed by the stable JWT subject; unauthenticated or
invalid traffic falls back to client IP.

Tiers:

    auth      5/minute    login, send-code, register
    expensive 10/minute   LLM streams, transcribe, embedding ingestion
    upload    20/minute   file uploads (avatar, resume, JD, knowledge)
    default   60/minute   everything else that opts in

The limiter is exported as ``limiter`` and registered on the FastAPI app
in main.py via ``app.state.limiter = limiter``.
"""

from __future__ import annotations

from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import settings
from app.core.security import decode_token


def user_or_ip_key(request: Request) -> str:
    """Return a non-forgeable user quota key, or the caller IP.

    SlowAPI evaluates this before FastAPI dependencies, so the normal
    ``current_user`` object is not available yet. A verified access JWT is
    sufficient for quota identity; authorization and revocation remain the
    endpoint dependency's responsibility.
    """
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            payload = decode_token(token)
            if payload.get("type") == "access" and payload.get("sub"):
                return f"user:{payload['sub']}"
        except JWTError:
            pass
    return f"ip:{get_remote_address(request)}"


# Shared Redis backend so worker processes don't each have their own counter.
# slowapi accepts redis://, redis+sentinel://, memory://, etc.
limiter = Limiter(
    key_func=user_or_ip_key,
    storage_uri=settings.REDIS_URL,
    headers_enabled=True,  # surface X-RateLimit-* headers for debugging
    default_limits=[],  # opt-in per-endpoint; no global default
    # Rate limiting here is an availability guard, not a security boundary
    # (auth endpoints have their own verification-code IP lockout). Without
    # this fallback a Redis blip turns every @limiter.limit endpoint —
    # including chat turn submission — into a 500. Degraded mode = per-process counters.
    in_memory_fallback_enabled=True,
)

# Tier constants — change once, applied everywhere.
RATE_AUTH = "5/minute"
RATE_EXPENSIVE = "10/minute"
RATE_UPLOAD = "20/minute"
RATE_DEFAULT = "60/minute"

__all__ = [
    "RATE_AUTH",
    "RATE_DEFAULT",
    "RATE_EXPENSIVE",
    "RATE_UPLOAD",
    "limiter",
    "user_or_ip_key",
]
