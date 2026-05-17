"""Email verification codes — issue, send, verify.

Redis-backed; everything namespaced under ``email_code_v1:*``. All counters
update atomically via a single Lua script so a process crash between
``INCR`` and ``EXPIRE`` can't leave a non-expiring counter behind.

Anti-abuse layers
-----------------
* **Per-email code**: 6-digit code, 10-min TTL (from settings).
* **Per-email cooldown**: configurable resend gap (default 60 s).
* **Per-(email, purpose) attempts**: 5 wrong tries → code invalidated.
* **Per-IP attempts**: 20 verify failures in 10 minutes → IP frozen for
  the rest of that window. Covers the case where an attacker rotates
  emails to keep each ``_MAX_ATTEMPTS`` counter from tripping.
"""

from __future__ import annotations

import logging
import secrets
from typing import Literal

from app.core.config import settings
from app.db.redis import redis_client
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

Purpose = Literal["register", "reset_password", "change_email"]

# Versioned key prefixes — bumping the suffix invalidates all in-flight
# codes from the previous schema (e.g. on format change).
_CODE_PREFIX = "email_code_v1"
_COOLDOWN_PREFIX = "email_code_cooldown_v1"
_ATTEMPT_PREFIX = "email_code_attempts_v1"
_IP_ATTEMPT_PREFIX = "email_code_ip_attempts_v1"

_MAX_ATTEMPTS_PER_CODE = 5
_MAX_ATTEMPTS_PER_IP = 20
_IP_WINDOW_SECONDS = 600  # 10 min


# Atomic "increment, set TTL on first call". Returns the post-increment count.
# Without this, INCR + EXPIRE in two separate round-trips creates a window
# where a crash between them produces a counter that never expires.
_INCR_WITH_TTL_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return n
"""


def _code_key(email: str, purpose: Purpose) -> str:
    return f"{_CODE_PREFIX}:{purpose}:{email.lower()}"


def _cooldown_key(email: str, purpose: Purpose) -> str:
    return f"{_COOLDOWN_PREFIX}:{purpose}:{email.lower()}"


def _attempts_key(email: str, purpose: Purpose) -> str:
    return f"{_ATTEMPT_PREFIX}:{purpose}:{email.lower()}"


def _ip_attempts_key(ip: str) -> str:
    return f"{_IP_ATTEMPT_PREFIX}:{ip}"


def _generate_code() -> str:
    """6-digit numeric code, zero-padded."""
    return f"{secrets.randbelow(1_000_000):06d}"


async def _incr_with_ttl(key: str, ttl: int) -> int:
    """Atomic INCR + EXPIRE-if-new. Returns the new counter value."""
    return int(await redis_client.eval(_INCR_WITH_TTL_LUA, 1, key, ttl))


class CodeError(Exception):
    """Raised for user-visible verification flow errors."""


# ── Public API ────────────────────────────────────────────────────────


async def request_code(email: str, purpose: Purpose = "register") -> int:
    """Generate a code, send it, and return remaining TTL seconds.

    Raises ``CodeError`` if a recent code was just sent (resend cooldown).
    """
    r = redis_client
    cooldown_key = _cooldown_key(email, purpose)
    if await r.exists(cooldown_key):
        ttl = await r.ttl(cooldown_key)
        raise CodeError(f"请 {ttl} 秒后重试发送")

    code = _generate_code()
    code_key = _code_key(email, purpose)
    await r.set(code_key, code, ex=settings.EMAIL_CODE_TTL_SECONDS)
    await r.set(cooldown_key, "1", ex=settings.EMAIL_CODE_RESEND_COOLDOWN)
    # Reset the per-email attempt counter so the user gets a fresh 5 tries.
    await r.delete(_attempts_key(email, purpose))

    subject_map = {
        "register": "Interview Copilot · 注册验证码",
        "reset_password": "Interview Copilot · 重置密码验证码",
        "change_email": "Interview Copilot · 更换邮箱验证码",
    }
    minutes = max(1, settings.EMAIL_CODE_TTL_SECONDS // 60)
    body = (
        f"您的验证码是: {code}\n\n"
        f"此验证码 {minutes} 分钟内有效，请勿泄露。\n"
        "如果这不是您本人的操作，请忽略本邮件。"
    )
    await send_email(email, subject_map[purpose], body)
    return settings.EMAIL_CODE_TTL_SECONDS


async def assert_ip_not_locked(ip: str | None) -> None:
    """Block known-abusive IPs from verifying anything.

    Called *before* ``verify_code`` so a frozen IP gets a uniform error
    and we don't waste a Redis lookup on a doomed attempt.
    """
    if not ip:
        return
    raw = await redis_client.get(_ip_attempts_key(ip))
    if raw is not None and int(raw) > _MAX_ATTEMPTS_PER_IP:
        raise CodeError("此 IP 的验证尝试次数过多，请稍后再试")


async def record_verify_failure_for_ip(ip: str | None) -> None:
    """Bump the per-IP failure counter atomically. No-op if ``ip`` is None."""
    if not ip:
        return
    await _incr_with_ttl(_ip_attempts_key(ip), _IP_WINDOW_SECONDS)


async def reset_ip_failures(ip: str | None) -> None:
    """Clear the per-IP failure counter after a successful verify."""
    if not ip:
        return
    await redis_client.delete(_ip_attempts_key(ip))


async def verify_code(email: str, code: str, purpose: Purpose = "register") -> bool:
    """Check a submitted code. On success the stored code is consumed.

    Raises ``CodeError`` on rate-limit, expired, or wrong-code outcomes.

    NB: IP-level rate limiting is the caller's responsibility — call
    ``assert_ip_not_locked(ip)`` before and ``record_verify_failure_for_ip``
    / ``reset_ip_failures`` after. The service stays IP-agnostic so it can
    be reused from non-HTTP contexts (CLI tools, background jobs).
    """
    r = redis_client
    code_key = _code_key(email, purpose)
    attempts_key = _attempts_key(email, purpose)

    stored = await r.get(code_key)
    if stored is None:
        raise CodeError("验证码已过期或未发送，请重新获取")

    attempts = await _incr_with_ttl(attempts_key, settings.EMAIL_CODE_TTL_SECONDS)
    if attempts > _MAX_ATTEMPTS_PER_CODE:
        await r.delete(code_key)
        await r.delete(attempts_key)
        raise CodeError("尝试次数过多，请重新获取验证码")

    if not secrets.compare_digest(stored, code.strip()):
        raise CodeError("验证码错误")

    # Success — consume the code + reset counters.
    await r.delete(code_key)
    await r.delete(attempts_key)
    return True


__all__ = [
    "CodeError",
    "Purpose",
    "request_code",
    "verify_code",
    "assert_ip_not_locked",
    "record_verify_failure_for_ip",
    "reset_ip_failures",
]
