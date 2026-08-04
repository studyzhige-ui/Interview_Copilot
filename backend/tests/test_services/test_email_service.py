from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.services.auth.email_service import send_email


@pytest.mark.asyncio
async def test_smtp_logs_never_include_verification_code(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    caplog.set_level(logging.INFO)

    with patch("app.services.auth.email_service._send_sync"):
        sent = await send_email(
            "alice@example.com",
            "重置密码验证码",
            "您的验证码是: 123456",
        )

    assert sent is True
    assert "sent OK" in caplog.text
    assert "123456" not in caplog.text


@pytest.mark.asyncio
async def test_smtp_failure_log_does_not_include_verification_code(monkeypatch, caplog):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    caplog.set_level(logging.ERROR)

    with patch(
        "app.services.auth.email_service._send_sync",
        side_effect=RuntimeError("connection failed"),
    ):
        sent = await send_email(
            "alice@example.com",
            "重置密码验证码",
            "您的验证码是: 654321",
        )

    assert sent is False
    assert "SMTP send FAILED" in caplog.text
    assert "654321" not in caplog.text
