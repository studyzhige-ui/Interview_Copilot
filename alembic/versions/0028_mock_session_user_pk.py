"""CLEANUP #2 (2/N): mock_interview_sessions.user_id -> users.id FK.

``mock_interview_sessions`` is written only by the mock-finish path (which now
resolves the username via resolve_user_pk) and is never queried by user_id, so
the boundary is self-contained.

Clean rebuild: drop the username-keyed ``user_id`` + its index, re-add as an
integer FK to ``users.id`` (no backfill).

Revision ID: 0028_mock_session_user_pk
Revises: 0027_mock_runtime_user_pk
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0028_mock_session_user_pk"
down_revision: Union[str, None] = "0027_mock_runtime_user_pk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "mock_interview_sessions"
_IDX = "ix_mock_interview_sessions_user_id"


def _has_index(insp, name: str) -> bool:
    return name in {i["name"] for i in insp.get_indexes(_TABLE)}


def _has_column(insp, col: str) -> bool:
    return col in {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_index(insp, _IDX):
        op.drop_index(_IDX, table_name=_TABLE)
    if _has_column(insp, "user_id"):
        op.drop_column(_TABLE, "user_id")
    op.add_column(
        _TABLE,
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
    )
    op.create_index(_IDX, _TABLE, ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    if _has_index(insp, _IDX):
        op.drop_index(_IDX, table_name=_TABLE)
    if _has_column(insp, "user_id"):
        op.drop_column(_TABLE, "user_id")
    op.add_column(_TABLE, sa.Column("user_id", sa.String(), nullable=False))
    op.create_index(_IDX, _TABLE, ["user_id"])
