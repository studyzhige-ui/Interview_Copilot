"""Email delivery service.

Single responsibility: send an email. In dev mode (SMTP_HOST empty), the message
body is logged to stdout so the verification flow can be exercised without a
real SMTP server. In production, smtplib runs in a threadpool to avoid blocking
the event loop.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _build_message(to_email: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _send_sync(to_email: str, subject: str, body: str) -> None:
    """Blocking SMTP send — must run inside a threadpool."""
    msg = _build_message(to_email, subject, body)
    context = ssl.create_default_context()
    if settings.SMTP_USE_TLS:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.starttls(context=context)
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=10
        ) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email.

    Returns True on success (including the dev-log fallback path), False if
    SMTP was configured but the send failed.

    Logging policy — every send leaves a delivery breadcrumb, but production
    SMTP logs never contain the verification code:

      * SMTP not configured  → WARNING with full body (dev fallback)
      * SMTP configured + OK → INFO with recipient + subject
      * SMTP configured + fail → ERROR with recipient + subject + exception
    """
    if not settings.SMTP_HOST:
        logger.warning(
            "[email] SMTP not configured — body printed below.\n"
            "  To:      %s\n  Subject: %s\n  Body:    %s",
            to_email,
            subject,
            body,
        )
        return True
    try:
        await asyncio.to_thread(_send_sync, to_email, subject, body)
        logger.info(
            "[email] sent OK. To=%s Subject=%s",
            to_email,
            subject,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[email] SMTP send FAILED. To=%s Subject=%s Error=%s",
            to_email,
            subject,
            exc,
        )
        return False
