"""MEMORY-V3 (schema foundation): memory_documents + ability_states + audit_logs.

Additive slice: creates the three new Memory tables alongside the existing
``knowledge_docs`` / ``strategy_docs`` / ``habit_docs`` / ``memory_audit_log``
(which stay live until MEM-CUTOVER rewires extraction onto the new tables and
drops the old ones). Nothing here touches the old path, so the running memory
system is unaffected.

* ``memory_documents``       — global user_profile / learning_strategy docs.
* ``memory_ability_states``  — per-topic mastery state (replaces knowledge_docs).
* ``memory_audit_logs``      — v3 audit trail (typed links + idempotency_key).

All three key on the stable ``users.id``.

Revision ID: 0022_memory_v3_schema
Revises: 0021_mock_runtime_conv_cols
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "0022_memory_v3_schema"
down_revision: Union[str, None] = "0021_mock_runtime_conv_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _has_table(insp, "memory_documents"):
        op.create_table(
            "memory_documents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("doc_type", sa.String(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("one_liner", sa.String(), nullable=False, server_default=""),
            sa.Column("last_discussed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", "doc_type", name="uq_memory_document_user_type"),
        )
        op.create_index("ix_memory_documents_user_id", "memory_documents", ["user_id"])

    if not _has_table(insp, "memory_ability_states"):
        op.create_table(
            "memory_ability_states",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("topic", sa.String(), nullable=False),
            sa.Column("skill_type", sa.String(), nullable=False),
            sa.Column("mastery_level", sa.String(), nullable=False, server_default="improving"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("evidence_refs_json", sa.Text(), nullable=True),
            sa.Column("search_text", sa.Text(), nullable=True),
            sa.Column("last_evidence_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("archived_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_memory_ability_states_user_id", "memory_ability_states", ["user_id"],
        )
        # Active-only uniqueness: archived rows keep the history.
        op.create_index(
            "uq_ability_state_active", "memory_ability_states",
            ["user_id", "topic", "skill_type"], unique=True,
            postgresql_where=sa.text("archived_at IS NULL"),
        )
        op.create_index(
            "ix_ability_state_user_mastery", "memory_ability_states",
            ["user_id", "mastery_level"],
        )

    if not _has_table(insp, "memory_audit_logs"):
        op.create_table(
            "memory_audit_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column(
                "memory_document_id", sa.String(),
                sa.ForeignKey("memory_documents.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column(
                "memory_ability_state_id", sa.String(),
                sa.ForeignKey("memory_ability_states.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("doc_type", sa.String(), nullable=True),
            sa.Column("topic", sa.String(), nullable=True),
            sa.Column("change_type", sa.String(), nullable=False),
            sa.Column("source_conversation_id", sa.String(), nullable=True),
            sa.Column("source_interview_record_id", sa.String(), nullable=True),
            sa.Column("source_message_range_json", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(), nullable=True),
            sa.Column("before_body", sa.Text(), nullable=True),
            sa.Column("after_body", sa.Text(), nullable=True),
            sa.Column("summary", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_memory_audit_logs_user_id", "memory_audit_logs", ["user_id"])
        op.create_index(
            "ix_memory_audit_logs_user_created", "memory_audit_logs",
            ["user_id", "created_at"],
        )
        op.create_index(
            "uq_memory_audit_logs_idem", "memory_audit_logs",
            ["idempotency_key"], unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    # Reverse order — audit references the other two.
    if _has_table(insp, "memory_audit_logs"):
        op.drop_table("memory_audit_logs")
    if _has_table(insp, "memory_ability_states"):
        op.drop_table("memory_ability_states")
    if _has_table(insp, "memory_documents"):
        op.drop_table("memory_documents")
