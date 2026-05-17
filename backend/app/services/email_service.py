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
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=10) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email.

    Returns True on success (including the dev-log fallback path), False if
    SMTP was configured but the send failed.

    Logging policy — every send leaves a breadcrumb in the application log
    regardless of outcome, so support can reconstruct "did the user actually
    get a code?" from logs alone:

      * SMTP not configured  → WARNING with full body (dev fallback)
      * SMTP configured + OK → INFO with full body (traceability)
      * SMTP configured + fail → ERROR with full body + exception
    """
    if not settings.SMTP_HOST:
        logger.warning(
            "[email] SMTP not configured — body printed below.\n"
            "  To:      %s\n  Subject: %s\n  Body:    %s",
            to_email, subject, body,
        )
        return True
    try:
        await asyncio.to_thread(_send_sync, to_email, subject, body)
        # ALWAYS log the body too, even on success. Verification codes and
        # password-reset tokens are short-lived; logging them in the dev/prod
        # log lets operators answer "did Alice actually get her code?" without
        # asking her to forward the email. If you ever ship to a regulated
        # environment, gate this on settings.DEBUG.
        logger.info(
            "[email] sent OK.\n  To:      %s\n  Subject: %s\n  Body:    %s",
            to_email, subject, body,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[email] SMTP send FAILED — body printed below.\n"
            "  To:      %s\n  Subject: %s\n  Body:    %s\n  Error:   %s",
            to_email, subject, body, exc,
        )
        return False
