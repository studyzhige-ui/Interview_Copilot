"""API error classification and jittered backoff for the Agent Harness.

Design reference: Hermes Agent ``run_agent.py`` — ``jittered_backoff``
and ``classify_api_error`` patterns.
"""

import asyncio
import logging
import random
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    RETRYABLE = "retryable"
    CONTEXT_TOO_LONG = "context_too_long"
    FATAL = "fatal"


def classify_api_error(error: Exception) -> ErrorCategory:
    """Classify an OpenAI-compatible API error into a recovery category."""
    msg = str(error).lower()
    err_type = type(error).__name__

    # Context length exceeded — need compaction
    if any(phrase in msg for phrase in (
        "context_length_exceeded",
        "maximum context length",
        "token limit",
        "reduce the length",
    )):
        return ErrorCategory.CONTEXT_TOO_LONG

    # Payment / balance / quota exhausted — retrying NEVER helps (DeepSeek
    # returns HTTP 402 here). Must be checked before the rate-limit /
    # default-retryable branches so we fail fast instead of burning the
    # full backoff schedule on a hopeless call.
    status = getattr(error, "status_code", None)
    if status == 402 or any(phrase in msg for phrase in (
        "insufficient_balance",
        "insufficient account balance",
        "insufficient_quota",
        "payment required",
        "余额不足",
        "欠费",
    )):
        return ErrorCategory.FATAL

    # Rate limit / server errors — retryable
    if any(phrase in msg for phrase in ("429", "rate_limit", "rate limit")):
        return ErrorCategory.RETRYABLE
    if any(phrase in msg for phrase in ("500", "502", "503", "overloaded", "server_error")):
        return ErrorCategory.RETRYABLE
    if "timeout" in msg or "timed out" in msg:
        return ErrorCategory.RETRYABLE
    if err_type in ("Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError"):
        return ErrorCategory.RETRYABLE

    # Auth / bad request — fatal
    if any(phrase in msg for phrase in ("401", "403", "invalid_api_key", "authentication")):
        return ErrorCategory.FATAL
    if "400" in msg and "context" not in msg:
        return ErrorCategory.FATAL

    # Default: treat as retryable (optimistic)
    return ErrorCategory.RETRYABLE


def jittered_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Compute a jittered exponential backoff delay in seconds.

    Formula: ``min(cap, base * 2^attempt) * uniform(0.5, 1.0)``
    """
    delay = min(cap, base * (2 ** attempt))
    return delay * random.uniform(0.5, 1.0)


async def call_with_retry(
    coro_factory,
    *,
    max_retries: int = 3,
    on_context_too_long=None,
):
    """Call *coro_factory()* with retry and error classification.

    Parameters
    ----------
    coro_factory:
        A zero-arg callable that returns an awaitable (called fresh each
        retry so that the coroutine is not reused).
    max_retries:
        Maximum number of retry attempts for retryable errors.
    on_context_too_long:
        Optional async callable invoked when the error is
        ``CONTEXT_TOO_LONG``.  If it returns ``True``, the call is
        retried once after compaction; otherwise the error propagates.

    Returns
    -------
    The result of *coro_factory()* on success.

    Raises
    ------
    Exception
        The original exception after exhausting retries or on fatal
        errors.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except Exception as exc:
            last_error = exc
            category = classify_api_error(exc)

            if category == ErrorCategory.FATAL:
                logger.error("Fatal API error (not retryable): %s", exc)
                raise

            if category == ErrorCategory.CONTEXT_TOO_LONG:
                logger.warning("Context too long error: %s", exc)
                if on_context_too_long is not None:
                    compacted = await on_context_too_long()
                    if compacted:
                        continue  # retry after compaction
                raise

            # RETRYABLE
            if attempt < max_retries:
                delay = jittered_backoff(attempt)
                logger.warning(
                    "Retryable API error (attempt %d/%d, backoff %.1fs): %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("API error after %d retries: %s", max_retries, exc)
                raise

    # Should not reach here, but just in case
    raise last_error  # type: ignore[misc]
