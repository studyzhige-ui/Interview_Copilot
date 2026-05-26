"""Drop the redundant non-unique ``ix_chat_messages_session_seq``.

The DB audit caught this on the second pass: 0001_baseline created
``ix_chat_messages_session_seq (session_id, seq)`` as a non-unique
composite for read-time ``ORDER BY seq`` queries. 0010 then added
``uq_chat_messages_session_seq (session_id, seq)`` as a unique
constraint (backed by a unique B-tree index) to guard the
concurrent-append race in ``chat_history_service``.

Both indexes cover the same two columns in the same order. Postgres
uses whichever serves the query — but every INSERT now writes BOTH,
doubling the per-row index-write cost for no read benefit (a unique
B-tree handles read-time ``ORDER BY`` just as well as a non-unique
one with the same leading columns).

Drop the non-unique one. Match the ORM by removing the duplicate
``Index`` from ``ChatMessage.__table_args__``.

Revision ID: 0011_drop_dup_chat_seq_idx
Revises: 0010_orm_alembic_drift_fixup
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "0011_drop_dup_chat_seq_idx"
down_revision: Union[str, None] = "0010_orm_alembic_drift_fixup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: the index might already be missing on dev DBs where
    # ``Base.metadata.create_all()`` was used at some point (the ORM
    # has only the unique constraint in __table_args__, so create_all
    # never made the redundant non-unique index in the first place).
    bind = op.get_bind()
    insp = inspect(bind)
    existing = {ix["name"] for ix in insp.get_indexes("chat_messages")}
    if "ix_chat_messages_session_seq" in existing:
        op.drop_index("ix_chat_messages_session_seq", table_name="chat_messages")


def downgrade() -> None:
    # Restore the non-unique index. Note this reintroduces the
    # double-write cost; only run if 0010's unique constraint is
    # also being dropped (i.e. as part of a 0010 rollback).
    op.create_index(
        "ix_chat_messages_session_seq",
        "chat_messages",
        ["session_id", "seq"],
    )
