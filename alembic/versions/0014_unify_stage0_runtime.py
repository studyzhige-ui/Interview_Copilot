"""Unify Stage 0 ingress and remove retired runtime layers.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_submissions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column(
            "question_indexes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "attachments_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("source_client_id", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "position",
            name="uq_pending_submissions_conversation_position",
        ),
    )
    op.create_index(
        op.f("ix_pending_submissions_conversation_id"),
        "pending_submissions",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pending_submissions_user_id"),
        "pending_submissions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_pending_submissions_conversation_status_position",
        "pending_submissions",
        ["conversation_id", "status", "position"],
        unique=False,
    )

    op.create_table(
        "conversation_attachment_drafts",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("file_asset_id", sa.String(), nullable=False),
        sa.Column("source_document_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["file_asset_id"], ["file_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["knowledge_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_document_id", name="uq_conversation_attachment_drafts_source_document_id"
        ),
    )
    for name, columns in (
        ("ix_conversation_attachment_drafts_user_id", ["user_id"]),
        ("ix_conversation_attachment_drafts_conversation_id", ["conversation_id"]),
        ("ix_conversation_attachment_drafts_file_asset_id", ["file_asset_id"]),
        (
            "ix_attachment_drafts_conversation_removed",
            ["conversation_id", "removed_at"],
        ),
    ):
        op.create_index(name, "conversation_attachment_drafts", columns, unique=False)

    op.add_column(
        "conversation_turns",
        sa.Column("submission_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "dispatch_generation", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("waiting_reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("interrupt_submission_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "conversation_turns",
        sa.Column("interrupt_submission_version", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_conv_turn_interrupt_submission",
        "conversation_turns",
        "pending_submissions",
        ["interrupt_submission_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_conversation_turns_submission_id",
        "conversation_turns",
        ["submission_id"],
    )
    op.create_foreign_key(
        "fk_conversation_turns_submission_id_pending_submissions",
        "conversation_turns",
        "pending_submissions",
        ["submission_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "conversation_attachment_refs",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("draft_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("submission_id", sa.String(length=128), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("file_asset_id", sa.String(), nullable=False),
        sa.Column("source_document_id", sa.String(), nullable=False),
        sa.Column("file_asset_version", sa.String(length=96), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["file_asset_id"], ["file_assets.id"]),
        sa.ForeignKeyConstraint(["source_document_id"], ["knowledge_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", name="uq_attachment_refs_draft"),
        sa.UniqueConstraint(
            "conversation_id",
            "submission_id",
            "position",
            name="uq_attachment_refs_submission_position",
        ),
        sa.UniqueConstraint(
            "turn_id", "position", name="uq_attachment_refs_turn_position"
        ),
    )
    for name, columns in (
        ("ix_conversation_attachment_refs_user_id", ["user_id"]),
        ("ix_conversation_attachment_refs_conversation_id", ["conversation_id"]),
        ("ix_conversation_attachment_refs_turn_id", ["turn_id"]),
        ("ix_conversation_attachment_refs_submission_id", ["submission_id"]),
        ("ix_conversation_attachment_refs_file_asset_id", ["file_asset_id"]),
        ("ix_conversation_attachment_refs_source_document_id", ["source_document_id"]),
        (
            "ix_attachment_refs_conversation_turn",
            ["conversation_id", "turn_id"],
        ),
    ):
        op.create_index(name, "conversation_attachment_refs", columns, unique=False)
    op.alter_column(
        "conversation_turns",
        "capability_snapshot_json",
        new_column_name="tool_snapshot_json",
    )
    op.alter_column(
        "conversation_turns",
        "loaded_schemas_json",
        new_column_name="loaded_tool_schemas_json",
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "effect", sa.String(length=32), server_default="unknown", nullable=False
        ),
    )

    op.create_table(
        "agent_interactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column(
            "request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "resolution_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('clarification', 'connection', 'approval', 'client_readiness')",
            name="ck_agent_interactions_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'rejected', 'cancelled')",
            name="ck_agent_interactions_status",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_interactions_turn_id"),
        "agent_interactions",
        ["turn_id"],
        unique=False,
    )
    op.create_index(
        "uq_agent_interactions_pending_turn",
        "agent_interactions",
        ["turn_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "dispatch_generation", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "policy_decision",
            sa.String(length=16),
            server_default="ask",
            nullable=False,
        ),
    )
    op.add_column(
        "agent_tool_calls",
        sa.Column(
            "policy_reason",
            sa.String(length=128),
            server_default="unknown_effect",
            nullable=False,
        ),
    )

    op.drop_index(
        op.f("ix_conversation_capability_states_user_id"),
        table_name="conversation_capability_states",
    )
    op.drop_table("conversation_capability_states")
    op.drop_table("agent_checkpoints")
    op.drop_index("ix_session_tasks_session_status", table_name="session_tasks")
    op.drop_index(op.f("ix_session_tasks_session_id"), table_name="session_tasks")
    op.drop_table("session_tasks")
    op.drop_column("conversations", "global_memory_enabled")
    op.drop_column("users", "global_memory_enabled")


def downgrade() -> None:
    op.drop_index(
        "uq_agent_interactions_pending_turn", table_name="agent_interactions"
    )
    op.drop_index(
        op.f("ix_agent_interactions_turn_id"), table_name="agent_interactions"
    )
    op.drop_table("agent_interactions")
    op.drop_constraint(
        "fk_conv_turn_interrupt_submission",
        "conversation_turns",
        type_="foreignkey",
    )
    op.drop_column("conversation_turns", "interrupt_submission_version")
    op.drop_column("conversation_turns", "interrupt_submission_id")

    for name in (
        "ix_attachment_refs_conversation_turn",
        "ix_conversation_attachment_refs_file_asset_id",
        "ix_conversation_attachment_refs_source_document_id",
        "ix_conversation_attachment_refs_submission_id",
        "ix_conversation_attachment_refs_turn_id",
        "ix_conversation_attachment_refs_conversation_id",
        "ix_conversation_attachment_refs_user_id",
    ):
        op.drop_index(name, table_name="conversation_attachment_refs")
    op.drop_table("conversation_attachment_refs")

    for name in (
        "ix_attachment_drafts_conversation_removed",
        "ix_conversation_attachment_drafts_file_asset_id",
        "ix_conversation_attachment_drafts_conversation_id",
        "ix_conversation_attachment_drafts_user_id",
    ):
        op.drop_index(name, table_name="conversation_attachment_drafts")
    op.drop_table("conversation_attachment_drafts")

    op.add_column(
        "users",
        sa.Column(
            "global_memory_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("global_memory_enabled", sa.Boolean(), nullable=True),
    )
    op.create_table(
        "agent_checkpoints",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("current_task_id", sa.Integer(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "conversation_capability_states",
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("discovered_skills_json", postgresql.JSONB(), nullable=False),
        sa.Column("permissions_json", postgresql.JSONB(), nullable=False),
        sa.Column("tool_history_json", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        op.f("ix_conversation_capability_states_user_id"),
        "conversation_capability_states",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "session_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parent_task_id", sa.Integer(), nullable=True),
        sa.Column("owner", sa.String(length=64), nullable=True),
        sa.Column("blocked_by_json", postgresql.JSONB(), nullable=False),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column("verification_status", sa.String(length=16), nullable=False),
        sa.Column("verification_notes", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "task_id", name="uq_session_tasks_session_task"
        ),
    )
    op.create_index(
        op.f("ix_session_tasks_session_id"),
        "session_tasks",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_session_tasks_session_status",
        "session_tasks",
        ["session_id", "status"],
        unique=False,
    )

    op.drop_column("agent_tool_calls", "policy_reason")
    op.drop_column("agent_tool_calls", "policy_decision")
    op.drop_column("agent_tool_calls", "effect")
    op.drop_column("agent_tool_calls", "dispatch_generation")

    op.alter_column(
        "conversation_turns",
        "loaded_tool_schemas_json",
        new_column_name="loaded_schemas_json",
    )
    op.alter_column(
        "conversation_turns",
        "tool_snapshot_json",
        new_column_name="capability_snapshot_json",
    )
    op.drop_constraint(
        "fk_conversation_turns_submission_id_pending_submissions",
        "conversation_turns",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_conversation_turns_submission_id",
        "conversation_turns",
        type_="unique",
    )
    op.drop_column("conversation_turns", "submission_id")
    op.drop_column("conversation_turns", "dispatch_generation")
    op.drop_column("conversation_turns", "waiting_reason")
    op.drop_index(
        "ix_pending_submissions_conversation_status_position",
        table_name="pending_submissions",
    )
    op.drop_index(
        op.f("ix_pending_submissions_user_id"), table_name="pending_submissions"
    )
    op.drop_index(
        op.f("ix_pending_submissions_conversation_id"),
        table_name="pending_submissions",
    )
    op.drop_table("pending_submissions")
