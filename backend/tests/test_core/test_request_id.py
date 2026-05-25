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
    """End-to-end: the middleware sets an id, the handler runs, the
    response header echoes the id back to the client."""
    from app.core.request_id import new_request_id, set_request_id

    app = FastAPI()

    @app.middleware("http")
    async def rid_mw(request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        rid = incoming if incoming else new_request_id()
        set_request_id(rid)
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        return resp

    @app.get("/echo")
    def echo():
        return {"rid": get_request_id()}

    with TestClient(app) as client:
        resp = client.get("/echo")
    assert resp.status_code == 200
    # The handler saw whatever the middleware set, and the response
    # header carries the same value.
    body_rid = resp.json()["rid"]
    header_rid = resp.headers["X-Request-ID"]
    assert body_rid == header_rid
    # Auto-generated (no X-Request-ID inbound) is the 12-char hex form.
    assert len(body_rid) == 12


def test_middleware_honors_incoming_x_request_id():
    """If the caller already supplied an X-Request-ID, the middleware
    uses it verbatim instead of minting a fresh one. Lets a frontend
    (or upstream gateway) correlate IDs across systems."""
    from app.core.request_id import new_request_id, set_request_id

    app = FastAPI()

    @app.middleware("http")
    async def rid_mw(request, call_next):
        incoming = request.headers.get("x-request-id", "").strip()
        rid = incoming if incoming else new_request_id()
        set_request_id(rid)
        resp = await call_next(request)
        resp.headers["X-Request-ID"] = rid
        return resp

    @app.get("/echo")
    def echo():
        return {"rid": get_request_id()}

    with TestClient(app) as client:
        resp = client.get("/echo", headers={"X-Request-ID": "client-supplied-id"})
    assert resp.json()["rid"] == "client-supplied-id"
    assert resp.headers["X-Request-ID"] == "client-supplied-id"
