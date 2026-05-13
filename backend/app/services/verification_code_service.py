"""Verification-code service backed by Redis with TTL.

Stores codes as plain strings under namespaced keys. Use a hash of the code if
you ever need to defend against Redis dumps; for local dev plaintext is fine.

Resend cooldown is enforced via a separate sentinel key.
"""

import logging
import secrets
from typing import Literal

import redis.asyncio as aioredis

from app.core.config import settings
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

Purpose = Literal["register", "reset_password", "change_email"]

_CODE_PREFIX = "email_code"
_COOLDOWN_PREFIX = "email_code_cooldown"
_ATTEMPT_PREFIX = "email_code_attempts"
_MAX_ATTEMPTS = 5

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _code_key(email: str, purpose: Purpose) -> str:
    return f"{_CODE_PREFIX}:{purpose}:{email.lower()}"


def _cooldown_key(email: str, purpose: Purpose) -> str:
    return f"{_COOLDOWN_PREFIX}:{purpose}:{email.lower()}"


def _attempts_key(email: str, purpose: Purpose) -> str:
    return f"{_ATTEMPT_PREFIX}:{purpose}:{email.lower()}"


def _generate_code() -> str:
    """6-digit numeric code, zero-padded."""
    return f"{secrets.randbelow(1_000_000):06d}"


class CodeError(Exception):
    """Raised for user-visible verification flow errors."""


async def request_code(email: str, purpose: Purpose = "register") -> int:
    """Generate a code, send it, and return remaining TTL seconds.

    Raises CodeError if a recent code was just sent (resend cooldown).
    """
    r = _get_redis()
    cooldown_key = _cooldown_key(email, purpose)
    if await r.exists(cooldown_key):
        ttl = await r.ttl(cooldown_key)
        raise CodeError(f"请 {ttl} 秒后重试发送")

    code = _generate_code()
    code_key = _code_key(email, purpose)
    await r.set(code_key, code, ex=settings.EMAIL_CODE_TTL_SECONDS)
    await r.set(cooldown_key, "1", ex=settings.EMAIL_CODE_RESEND_COOLDOWN)
    # Reset attempt counter when a new code is issued.
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


async def verify_code(email: str, code: str, purpose: Purpose = "register") -> bool:
    """Check a submitted code. On success the stored code is consumed.

    Raises CodeError on rate-limit, expired, or wrong-code outcomes.
    """
    r = _get_redis()
    code_key = _code_key(email, purpose)
    attempts_key = _attempts_key(email, purpose)

    stored = await r.get(code_key)
    if stored is None:
        raise CodeError("验证码已过期或未发送，请重新获取")

    # Increment attempts; if too many wrong tries, invalidate the code.
    attempts = await r.incr(attempts_key)
    if attempts == 1:
        await r.expire(attempts_key, settings.EMAIL_CODE_TTL_SECONDS)
    if attempts > _MAX_ATTEMPTS:
        await r.delete(code_key)
        await r.delete(attempts_key)
        raise CodeError("尝试次数过多，请重新获取验证码")

    if not secrets.compare_digest(stored, code.strip()):
        raise CodeError("验证码错误")

    # success — consume
    await r.delete(code_key)
    await r.delete(attempts_key)
    return True
