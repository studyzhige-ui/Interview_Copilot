"""MEMORY-V3 (cutover): drop the old memory tables + users.user_profile_doc.

After MEM-CUTOVER rewired extraction / dreaming / api / agent tools / context
loader / diagnostics onto ``memory_documents`` + ``memory_ability_states`` +
``memory_audit_logs`` (0022), the legacy stores are unused. This drops them:

* ``knowledge_docs`` / ``strategy_docs`` / ``habit_docs`` — superseded by
  ability states + the two memory documents.
* ``memory_audit_log`` (singular) — superseded by ``memory_audit_logs``.
* ``users.user_profile_doc`` — moved to ``memory_documents(user_profile)``.

Clean rebuild: no data backfill (the new tables start empty).

Revision ID: 0023_drop_old_memory
Revises: 0022_memory_v3_schema
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0023_drop_old_memory"
down_revision: Union[str, None] = "0022_memory_v3_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_TABLES = ("knowledge_docs", "strategy_docs", "habit_docs", "memory_audit_log")


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    return _has_table(insp, table) and col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    for table in _OLD_TABLES:
        if _has_table(insp, table):
            op.drop_table(table)
    if _has_column(insp, "users", "user_profile_doc"):
        op.drop_column("users", "user_profile_doc")


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_column(insp, "users", "user_profile_doc"):
        op.add_column(
            "users",
            sa.Column("user_profile_doc", sa.Text(), nullable=False, server_default=""),
        )

    if not _has_table(insp, "knowledge_docs"):
        op.create_table(
            "knowledge_docs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("topic", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
            sa.Column("mastery_level", sa.String(), nullable=False, server_default="unknown"),
            sa.Column("fact_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_discussed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "topic", name="uq_knowledge_doc_user_topic"),
        )

    for table in ("strategy_docs", "habit_docs"):
        if not _has_table(insp, table):
            op.create_table(
                table,
                sa.Column("id", sa.String(), primary_key=True),
                sa.Column("user_id", sa.String(), nullable=False),
                sa.Column("body", sa.Text(), nullable=False, server_default=""),
                sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
                sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
                sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            )
            op.create_index(f"ix_{table}_user_id", table, ["user_id"], unique=True)

    if not _has_table(insp, "memory_audit_log"):
        op.create_table(
            "memory_audit_log",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("topic", sa.String(), nullable=True),
            sa.Column("change_type", sa.String(), nullable=False),
            sa.Column("source_record_id", sa.String(), nullable=True),
            sa.Column("source_session_id", sa.String(), nullable=True),
            sa.Column("before_body", sa.Text(), nullable=True),
            sa.Column("after_body", sa.Text(), nullable=True),
            sa.Column("summary", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_memory_audit_log_user_id", "memory_audit_log", ["user_id"])
        op.create_index("ix_memory_audit_log_doc_type", "memory_audit_log", ["doc_type"])
        op.create_index("ix_memory_audit_log_source_record_id", "memory_audit_log", ["source_record_id"])
        op.create_index("ix_memory_audit_user_created", "memory_audit_log", ["user_id", "created_at"])
