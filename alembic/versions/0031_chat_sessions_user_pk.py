"""CLEANUP #2 (5/N): chat_sessions.user_id -> users.id FK.

The final table in the username->users.id migration. Chat sessions now key on
the stable users.id. The API + chat-history service resolve the caller's
username via resolve_user_pk; the dreaming worker resolves username->pk for its
debrief-activity gate; recall_policy resolves at its ownership guard. A debrief
session's owner pk equals its bound interview_record's owner pk, so
build_interview_reference matches pk==pk directly (no bridge).

Clean rebuild: drop the username-keyed ``user_id`` + its three indexes (single +
two composites) and re-add as an integer FK to ``users.id`` (no backfill).
``chat_messages`` carries no user_id (keyed via session_id) and is untouched.

Revision ID: 0031_chat_sessions_user_pk
Revises: 0030_interview_records_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0031_chat_sessions_user_pk"
down_revision: Union[str, None] = "0030_interview_records_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "chat_sessions"
_IDX_SINGLE = "ix_chat_sessions_user_id"
_IDX_TYPE_ARCH = "ix_chat_sessions_user_type_arch"
_IDX_UPDATED = "ix_chat_sessions_user_updated"


def _indexes(insp) -> set[str]:
    return {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def _swap_user_id(bind, new_type) -> None:
    insp = inspect(bind)
    idx = _indexes(insp)
    for name in (_IDX_TYPE_ARCH, _IDX_UPDATED, _IDX_SINGLE):
        if name in idx:
            op.drop_index(name, table_name=_TABLE)
    if _has_column(insp, "user_id"):
        op.drop_column(_TABLE, "user_id")
    if new_type == "int":
        op.add_column(
            _TABLE,
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
        )
    else:
        op.add_column(_TABLE, sa.Column("user_id", sa.String(), nullable=False))
    op.create_index(_IDX_SINGLE, _TABLE, ["user_id"])
    op.create_index(_IDX_TYPE_ARCH, _TABLE, ["user_id", "session_type", "archived_at"])
    op.create_index(_IDX_UPDATED, _TABLE, ["user_id", "updated_at"])


def upgrade() -> None:
    _swap_user_id(op.get_bind(), "int")


def downgrade() -> None:
    _swap_user_id(op.get_bind(), "str")
