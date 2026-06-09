"""Tests for the shared error humanizer (``app.conversation.error_messages``).

These pin that every foreseeable upstream failure maps to a specific,
actionable Chinese message — so L1 chat, L2 agent, and the SSE net all
show the user what to DO, never a raw ``Error code: 402 - {...}`` dump.
"""
from __future__ import annotations

from app.core import error_messages as em
from app.core.error_messages import humanize_error


class _ApiErr(Exception):
    """Mimics an OpenAI-compatible ``APIStatusError``: a ``status_code``
    attribute plus a vendor message. DeepSeek's 402 arrives exactly like
    this — a generic status error, not a dedicated SDK subclass."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_insufficient_balance_402_is_actionable():
    # The reported bug: a model pointed at an expired / empty subscription
    # returns HTTP 402. Must read as the balance message, not generic.
    assert humanize_error(_ApiErr(402, "Insufficient account balance")) == em.MSG_BALANCE
    # Phrase-only (no status code) still classifies.
    assert humanize_error(Exception("insufficient_balance")) == em.MSG_BALANCE
    assert humanize_error(Exception("账户余额不足，已欠费")) == em.MSG_BALANCE
    # A 402 that ALSO looks like a bad request still reads as balance
    # (balance is checked first — it's the more actionable signal).
    assert humanize_error(_ApiErr(402, "bad request: insufficient_balance")) == em.MSG_BALANCE


def test_auth_errors_point_to_model_settings():
    assert humanize_error(_ApiErr(401, "invalid api key")) == em.MSG_AUTH
    assert humanize_error(_ApiErr(403, "forbidden")) == em.MSG_AUTH


def test_rate_limit():
    assert humanize_error(_ApiErr(429, "rate limited")) == em.MSG_RATE_LIMIT


def test_model_not_found():
    assert humanize_error(_ApiErr(404, "not found")) == em.MSG_MODEL_NOT_FOUND
    assert humanize_error(Exception("the model `foo` does not exist")) == em.MSG_MODEL_NOT_FOUND


def test_context_too_long():
    assert humanize_error(Exception("maximum context length exceeded")) == em.MSG_CONTEXT


def test_timeout():
    assert humanize_error(Exception("request timed out")) == em.MSG_TIMEOUT


def test_server_error():
    assert humanize_error(_ApiErr(503, "service unavailable")) == em.MSG_SERVER
    assert humanize_error(Exception("the model is overloaded")) == em.MSG_SERVER


def test_unknown_falls_back_to_generic():
    assert humanize_error(Exception("something totally unexpected")) == em.MSG_GENERIC
