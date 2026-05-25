"""Shared DB-session plumbing for the v3 memory services.

The ``session_scope`` context manager lets each doc-service ``load``
function accept an optional ``db: Session | None`` parameter:

  * Called without a session — opens a fresh ``SessionLocal()``,
    closes it on exit. Backward-compatible with single-call callers
    (one query, one connection).
  * Called WITH a session — uses the passed session and leaves it
    OPEN for the caller to manage. Lets a higher-level orchestrator
    (``v3_context_loader.load_universal`` /
    ``v3_context_loader.attach_active_bodies``) open ONE session and
    funnel 4-10 doc-service calls through it — collapses the v3
    memory load from N+1 connections per agent turn down to 1.

Why not just open the session in the engine and thread it everywhere:
``attach_active_bodies`` runs in ``asyncio.to_thread`` (see the P1-D
audit fix — its sync DB body needs to NOT block the event loop). A
SQLAlchemy session is NOT thread-safe; passing one from the main loop
thread into a worker would be unsafe. Each orchestrator opens its
OWN session inside its own execution context (the engine never sees
one), and the doc services just plumb whatever they're given through.
"""
from __future__ import annotations

import contextlib
from typing import Iterator

from sqlalchemy.orm import Session

from app.db.database import SessionLocal


@contextlib.contextmanager
def session_scope(db: Session | None) -> Iterator[Session]:
    """Yield ``db`` if given, else open + close a fresh session."""
    if db is not None:
        yield db
        return
    own = SessionLocal()
    try:
        yield own
    finally:
        own.close()


__all__ = ["session_scope"]
