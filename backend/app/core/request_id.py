"""Request-scoped correlation IDs for structured logging.

Each HTTP request gets a short UUID-derived ``request_id`` (or the
incoming ``X-Request-ID`` header if the client supplied one). That id
is stored in a ``contextvars.ContextVar`` so any ``logger.X(...)`` call
during the request — including the ones that happen inside
``asyncio.to_thread`` workers — can pick it up via the
:class:`RequestIdFormatter` and stamp it onto the log line.

Why bother: an SSE turn fans out across the engine, retrieval, the
agent loop, several tool dispatches, and (background) post-turn
maintenance. Pre-fix, an on-call engineer staring at the logs had no
way to scope down "what happened during *this* user's turn" — every
request's log lines were intermixed across all in-flight requests
with no shared key.

The id round-trips back to the client via the ``X-Request-ID``
response header (already in CORS's ``expose_headers`` since P3-C) so
a user can attach it to a bug report and the engineer can grep the
log for a single string.
"""
from __future__ import annotations

import contextvars
import logging
import uuid

# ContextVar — NOT a thread-local. ``asyncio.to_thread`` copies the
# current context into the worker thread, so a logger.X call inside
# a sync helper run via to_thread still sees the request id. (Plain
# ``threading.Thread`` does NOT copy — but we don't spawn raw threads
# from request handlers.)
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-",
)


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def get_request_id() -> str:
    return _request_id.get()


def new_request_id() -> str:
    """Short 12-char hex slug — collision-safe at any realistic QPS,
    keeps log lines from being dominated by a 32-char UUID."""
    return uuid.uuid4().hex[:12]


class RequestIdFormatter(logging.Formatter):
    """Inject ``%(request_id)s`` into every log record's attrs.

    Drop-in for ``logging.Formatter`` — the only difference is that
    the format string can reference ``%(request_id)s`` and it'll be
    populated from the contextvar. Outside an HTTP request the
    contextvar's default ``"-"`` keeps the column aligned without
    polluting it with ``None``.
    """

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = get_request_id()
        return super().format(record)


__all__ = [
    "RequestIdFormatter",
    "get_request_id",
    "new_request_id",
    "set_request_id",
]
