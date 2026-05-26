"""Tests for the request-id contextvar + middleware + log formatter.

These pin the contract: every HTTP request has a correlation id
that's stable across the request, visible to every logger call, and
echoed back to the client in the ``X-Request-ID`` response header.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_id import (
    RequestIdFormatter,
    get_request_id,
    new_request_id,
    set_request_id,
)


def test_new_request_id_is_short_and_hex():
    """12 hex chars — short enough to keep the log column tight, long
    enough that the birthday-collision risk is negligible at any
    realistic QPS."""
    rid = new_request_id()
    assert len(rid) == 12
    assert all(c in "0123456789abcdef" for c in rid)
    # Two consecutive calls produce different ids.
    assert rid != new_request_id()


def test_get_request_id_defaults_to_dash_outside_request():
    """Outside a request the contextvar's default is ``"-"`` so the
    log line still aligns and doesn't render ``None``."""
    # Reset to default (we don't have a clean fixture for the
    # ContextVar; the default-value semantics are what we're testing
    # here so this is acceptable).
    set_request_id("-")
    assert get_request_id() == "-"


def test_set_and_get_round_trip():
    set_request_id("abc123def456")
    assert get_request_id() == "abc123def456"


def test_formatter_injects_request_id_into_record(monkeypatch):
    """``%(request_id)s`` in the format string resolves to whatever
    the contextvar holds at format time."""
    set_request_id("test_rid_1")
    fmt = RequestIdFormatter("%(request_id)s | %(message)s")
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=".", lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    formatted = fmt.format(record)
    assert formatted == "test_rid_1 | hello"


def test_middleware_echoes_response_header():
    """End-to-end through ``app.main:app`` — verify the production
    wiring (not just an inline copy of the middleware). If someone
    accidentally removes the middleware registration from main.py,
    this test fails.

    NB: TestClient WITHOUT a ``with`` block skips the lifespan
    startup so the alembic-migration check (which runs against the
    local SQLite that doesn't have our latest head) doesn't fire.
    We're testing middleware wiring, not startup checks.
    """
    from app.main import app

    client = TestClient(app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-ID", "")
    # Auto-generated (no X-Request-ID inbound) is the 12-char hex form.
    assert len(rid) == 12
    assert all(c in "0123456789abcdef" for c in rid)


def test_middleware_honors_incoming_x_request_id():
    """If the caller already supplied an X-Request-ID, the production
    middleware uses it verbatim instead of minting a fresh one. Lets
    a frontend (or upstream gateway) correlate IDs across systems."""
    from app.main import app

    client = TestClient(app)
    resp = client.get("/ping", headers={"X-Request-ID": "client-supplied-id"})
    assert resp.headers.get("X-Request-ID") == "client-supplied-id"


def test_unhandled_exception_handler_attaches_request_id_header():
    """Source-level pin: ``unhandled_exception_logger`` in main.py
    must build its 500 JSONResponse with ``headers={"X-Request-ID":
    get_request_id()}``. A live end-to-end test would need to drive
    Starlette's ServerErrorMiddleware which the new starlette 1.0 +
    httpx TestClient combo handles differently across versions —
    instead we read the source and assert the contract literally.

    Why source inspection here: the actual production behaviour is
    that ServerErrorMiddleware short-circuits past our request_id
    middleware on the exception path, so the explicit ``headers=``
    kwarg in main.py is the ONLY thing keeping the header on a 500.
    A future refactor that drops that kwarg breaks the
    client↔server correlation contract silently.
    """
    import inspect
    from app.main import unhandled_exception_logger

    src = inspect.getsource(unhandled_exception_logger)
    # The body must reference get_request_id and the JSONResponse
    # headers= kwarg (regardless of exact formatting).
    assert "get_request_id" in src, (
        "unhandled_exception_logger must import + call get_request_id()"
    )
    assert "X-Request-ID" in src, (
        "unhandled_exception_logger must stamp X-Request-ID into the response"
    )
    assert "headers=" in src, (
        "unhandled_exception_logger must pass headers= to JSONResponse"
    )
