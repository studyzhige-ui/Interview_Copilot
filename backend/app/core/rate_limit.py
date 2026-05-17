"""Centralised rate-limit configuration.

Built on slowapi (Redis-backed) so quotas are shared across uvicorn workers.
Decorators are imported at endpoint definition sites.

Tiers (per-IP by default — switch to per-user via ``key_func=user_key`` once
auth is on JWT subjects everywhere):

    auth      5/minute    login, send-code, register
    expensive 10/minute   LLM streams, transcribe, embedding ingestion
    upload    20/minute   file uploads (avatar, resume, JD, knowledge)
    default   60/minute   everything else that opts in

The limiter is exported as ``limiter`` and registered on the FastAPI app
in main.py via ``app.state.limiter = limiter``.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Shared Redis backend so worker processes don't each have their own counter.
# slowapi accepts redis://, redis+sentinel://, memory://, etc.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    headers_enabled=True,  # surface X-RateLimit-* headers for debugging
    default_limits=[],     # opt-in per-endpoint; no global default
)

# Tier constants — change once, applied everywhere.
RATE_AUTH = "5/minute"
RATE_EXPENSIVE = "10/minute"
RATE_UPLOAD = "20/minute"
RATE_DEFAULT = "60/minute"
