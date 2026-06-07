"""Add ``token_version`` + ``password_changed_at`` to ``users``.

AUTH-IDENTITY: the JWT ``sub`` becomes the stable ``users.id`` and every
token now carries a ``token_version`` claim. ``get_current_user`` and
``/auth/refresh`` reject any token whose claim no longer matches the row, so
a password change (which bumps ``token_version``) invalidates every
outstanding access + refresh token at once — no per-jti blacklist sweep.

``token_version`` is NOT NULL with a server default of 0 so the column
backfills cleanly on existing rows. ``password_changed_at`` is audit/display
only and stays nullable (NULL = never changed since registration).

Revision ID: 0016_auth_token_version
Revises: 0015_rename_session_state
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0016_auth_token_version"
down_revision: Union[str, None] = "0015_rename_session_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: dev DBs that ran ``Base.metadata.create_all()`` after the
    # User model gained these columns will already have them.
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")}
    if "token_version" not in cols:
        op.add_column(
            "users",
            sa.Column(
                "token_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
    if "password_changed_at" not in cols:
        op.add_column(
            "users",
            sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "token_version")
