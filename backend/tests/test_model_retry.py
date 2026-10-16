"""Retry decisions use protocol evidence and never log provider payloads."""

import pytest

from app.agent_runtime import retry_utils


@pytest.mark.parametrize(
    "status,message,expected",
    [
        (403, "quoted 429 rate limit", "fatal"),
        (400, "invalid arguments 500", "fatal"),
        (400, "context_length_exceeded", "context_too_long"),
        (429, "retry later", "retryable"),
        (429, "insufficient_quota", "fatal"),
        (None, "unexpected program error", "fatal"),
        (None, "connection timeout", "fatal"),
    ],
)
def test_retry_classification(status, message, expected):
    error = RuntimeError(message)
    error.status_code = status
    assert retry_utils.classify_api_error(error).value == expected


@pytest.mark.asyncio
async def test_exhausted_context_retry_does_not_run_an_unused_compaction(caplog):
    calls, compactions = [], []

    async def request():
        calls.append(1)
        error = RuntimeError("context_length_exceeded SECRET_FROM_PROVIDER")
        error.status_code = 400
        raise error

    async def compact():
        compactions.append(1)
        return True

    with pytest.raises(RuntimeError):
        await retry_utils.call_with_retry(
            request, max_retries=1, on_context_too_long=compact
        )
    assert len(calls) == 2 and len(compactions) == 1
    assert "SECRET_FROM_PROVIDER" not in caplog.text
