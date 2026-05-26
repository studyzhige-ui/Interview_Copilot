"""Add per-user model_selection_json column to ``users``.

Pre-fix: ``data/runtime/model_selection.json`` was a single shared
file. Every process read it; ``PUT /models/runtime`` by User A
changed which LLM model the answer / agent / mock-interview /
fast roles used for **every** user on that worker. The audit
flagged this as cross-tenant: A switching to GPT-4 billed B's
API key (or worse, broke B's chat when B hadn't configured OpenAI).

Resolution: per-user storage in ``users.model_selection_json``
(JSON-encoded dict, NULL = use ROLE_DEFAULTS). The model_registry
helpers (``get_runtime_selection`` / ``persist_runtime_selection``
/ ``get_profile_for_role``) now accept a ``user_id`` parameter
and read/write THIS column. Without a user_id (startup-time
contexts like RAG embedding init), the helpers fall back to
ROLE_DEFAULTS — single-tenant behaviour preserved.

The legacy ``data/runtime/model_selection.json`` file is no
longer read or written. Migration leaves it on disk; ops can
delete it after the next deploy completes if they want.

Revision ID: 0012_user_model_selection
Revises: 0011_drop_dup_chat_seq_idx
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0012_user_model_selection"
down_revision: Union[str, None] = "0011_drop_dup_chat_seq_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: dev DBs that ran ``Base.metadata.create_all()`` after
    # the User model gained the new column (P6-C) will already have it.
    bind = op.get_bind()
    insp = inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")}
    if "model_selection_json" not in cols:
        op.add_column(
            "users",
            sa.Column("model_selection_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("users", "model_selection_json")
