from unittest.mock import AsyncMock

import pytest
from app.services.auth import verification_code_service as service


@pytest.fixture
def redis(monkeypatch):
    fake = AsyncMock()
    fake.exists.return_value = 0
    monkeypatch.setattr(service, "redis_client", fake)
    return fake


@pytest.mark.asyncio
async def test_request_code_schedules_delivery_without_waiting(monkeypatch, redis):
    scheduled = []
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(service, "send_email", send)
    monkeypatch.setattr(
        service,
        "safe_background_task",
        lambda coro, **_kwargs: scheduled.append(coro),
    )

    ttl = await service.request_code("alice@example.com", purpose="reset_password")

    assert ttl == service.settings.EMAIL_CODE_TTL_SECONDS
    send.assert_not_awaited()
    assert len(scheduled) == 1
    await scheduled[0]
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_delivery_clears_code_and_cooldown(monkeypatch, redis):
    monkeypatch.setattr(service, "send_email", AsyncMock(return_value=False))

    await service._deliver_code_email(
        "alice@example.com",
        "subject",
        "body",
        deliver=True,
        code_key="code-key",
        cooldown_key="cooldown-key",
    )

    redis.delete.assert_awaited_once_with("code-key", "cooldown-key")


@pytest.mark.asyncio
async def test_unknown_account_delivery_path_is_a_noop(monkeypatch, redis):
    send = AsyncMock()
    monkeypatch.setattr(service, "send_email", send)

    await service._deliver_code_email(
        "unknown@example.com",
        "subject",
        "body",
        deliver=False,
        code_key="code-key",
        cooldown_key="cooldown-key",
    )

    send.assert_not_awaited()
    redis.delete.assert_not_awaited()
