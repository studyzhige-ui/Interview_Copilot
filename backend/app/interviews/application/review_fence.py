"""A cancelled/superseded review may retain external receipts, never current facts.

Each explicit review admission freezes a generation. All review writes acquire
its parent record first and validate that generation in the same transaction.
The context is scoped to one worker invocation, not a global mutable singleton.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models.interview_record import InterviewRecord


class ReviewSuperseded(RuntimeError):
    """The record was edited, cancelled, removed or explicitly restarted."""


@dataclass(frozen=True)
class ReviewIdentity:
    record_id: str
    generation: int


_current: ContextVar[ReviewIdentity | None] = ContextVar(
    "review_identity", default=None
)


@contextmanager
def review_scope(record_id: str, generation: int):
    token = _current.set(ReviewIdentity(record_id, generation))
    try:
        yield
    finally:
        _current.reset(token)


def lock_record(db: Session, record_id: str) -> InterviewRecord | None:
    """Parent-before-children lock order is shared by edits and publication."""
    row = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == record_id)
        .with_for_update()
        .populate_existing()
        .first()
    )
    identity = _current.get()
    if identity is not None:
        if identity.record_id != record_id:
            raise ReviewSuperseded("review_record_identity_mismatch")
        if row is None or row.review_generation != identity.generation:
            raise ReviewSuperseded("review_generation_superseded")
    return row
