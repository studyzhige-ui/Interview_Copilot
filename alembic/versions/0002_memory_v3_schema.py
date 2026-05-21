"""Memory v3 schema: knowledge_docs + strategy_docs + habit_docs + audit log

* knowledge_docs   — per (user, topic) markdown doc
* strategy_docs    — single doc per user (answering methodology)
* habit_docs       — single doc per user (practice routine + mindset)
* memory_audit_log — append-only audit trail for all memory mutations
* interview_records.last_dreamed_at — dreaming cursor

The old ``memory_items`` table is left in place for now. The migration
that drops it runs after the v3 path is proven and the
``interview_fact`` rows have been distilled into the new docs (a
separate one-shot data migration script, not an alembic revision).

Revision ID: 0002_memory_v3
Revises: 0001_baseline
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002_memory_v3"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── knowledge_docs ────────────────────────────────────────────
    op.create_table(
        "knowledge_docs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "mastery_level",
            sa.String(),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("fact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_discussed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "user_id", "topic", name="uq_knowledge_doc_user_topic",
        ),
    )
    # No separate ix_knowledge_docs_user_id — the unique constraint
    # ``(user_id, topic)`` is already a composite index whose leading
    # column is user_id, so "WHERE user_id = ?" queries use its
    # left-prefix.

    # ── strategy_docs ─────────────────────────────────────────────
    op.create_table(
        "strategy_docs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_strategy_docs_user_id", "strategy_docs", ["user_id"],
    )

    # ── habit_docs ────────────────────────────────────────────────
    op.create_table(
        "habit_docs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, unique=True),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_habit_docs_user_id", "habit_docs", ["user_id"],
    )

    # ── memory_audit_log ──────────────────────────────────────────
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
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_memory_audit_log_user_id", "memory_audit_log", ["user_id"],
    )
    op.create_index(
        "ix_memory_audit_log_doc_type", "memory_audit_log", ["doc_type"],
    )
    op.create_index(
        "ix_memory_audit_log_source_record_id",
        "memory_audit_log",
        ["source_record_id"],
    )
    op.create_index(
        "ix_memory_audit_user_created",
        "memory_audit_log",
        ["user_id", "created_at"],
    )

    # ── interview_records.last_dreamed_at ────────────────────────
    op.add_column(
        "interview_records",
        sa.Column("last_dreamed_at", sa.DateTime(), nullable=True),
    )
    # Composite index on (user_id, last_dreamed_at) supports the
    # dreaming worker's selection query:
    #   WHERE user_id = ? AND (last_dreamed_at IS NULL OR updated_at > last_dreamed_at)
    op.create_index(
        "ix_interview_records_user_last_dreamed",
        "interview_records",
        ["user_id", "last_dreamed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interview_records_user_last_dreamed", table_name="interview_records",
    )
    op.drop_column("interview_records", "last_dreamed_at")
    op.drop_index("ix_memory_audit_user_created", table_name="memory_audit_log")
    op.drop_index(
        "ix_memory_audit_log_source_record_id", table_name="memory_audit_log",
    )
    op.drop_index("ix_memory_audit_log_doc_type", table_name="memory_audit_log")
    op.drop_index("ix_memory_audit_log_user_id", table_name="memory_audit_log")
    op.drop_table("memory_audit_log")
    op.drop_index("ix_habit_docs_user_id", table_name="habit_docs")
    op.drop_table("habit_docs")
    op.drop_index("ix_strategy_docs_user_id", table_name="strategy_docs")
    op.drop_table("strategy_docs")
    op.drop_table("knowledge_docs")
