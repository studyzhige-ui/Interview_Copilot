"""Add PersistentTask intake and the first Gmail connection slice.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "persistent_tasks",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trigger_kind", sa.String(length=16), nullable=False),
        sa.Column("trigger_spec_json", _jsonb(), nullable=False),
        sa.Column("read_scope_json", _jsonb(), nullable=False),
        sa.Column("action_scope_json", _jsonb(), nullable=False),
        sa.Column("allowed_tool_names_json", _jsonb(), nullable=False),
        sa.Column("user_request_identity", sa.String(length=256), nullable=False),
        sa.Column("user_request_version", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("creation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "compensation_blocked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('active', 'paused')",
            name="ck_persistent_tasks_state",
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('scheduled', 'event')",
            name="ck_persistent_tasks_trigger_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_persistent_tasks_user_idempotency",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            name="uq_persistent_tasks_conversation",
        ),
    )
    op.create_index(
        "ix_persistent_tasks_user_id",
        "persistent_tasks",
        ["user_id"],
    )
    op.create_index(
        "ix_persistent_tasks_user_state_updated",
        "persistent_tasks",
        ["user_id", "state", "updated_at"],
    )

    op.create_table(
        "persistent_task_triggers",
        sa.Column("id", sa.String(length=35), nullable=False),
        sa.Column("persistent_task_id", sa.String(length=35), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_identity", sa.String(length=256), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("cursor_after", sa.String(length=1024), nullable=True),
        sa.Column("occurrence_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("admitted_turn_id", sa.String(), nullable=True),
        sa.Column("admitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('scheduled', 'event', 'manual')",
            name="ck_persistent_task_triggers_kind",
        ),
        sa.CheckConstraint(
            "admitted_at IS NOT NULL OR admitted_turn_id IS NULL",
            name="ck_persistent_task_triggers_admission_shape",
        ),
        sa.ForeignKeyConstraint(
            ["persistent_task_id"],
            ["persistent_tasks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["admitted_turn_id"],
            ["conversation_turns.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "persistent_task_id",
            "idempotency_key",
            name="uq_persistent_task_triggers_task_idempotency",
        ),
    )
    op.create_index(
        "ix_persistent_task_triggers_persistent_task_id",
        "persistent_task_triggers",
        ["persistent_task_id"],
    )
    op.create_index(
        "ix_persistent_task_triggers_pending",
        "persistent_task_triggers",
        ["persistent_task_id", "admitted_at", "observed_at"],
    )
    op.create_index(
        "ix_persistent_task_triggers_turn",
        "persistent_task_triggers",
        ["admitted_turn_id"],
    )

    op.create_table(
        "gmail_integration_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("google_subject", sa.String(length=255), nullable=False),
        sa.Column("account_hint", sa.String(length=320), nullable=False),
        sa.Column("scopes_json", _jsonb(), nullable=False),
        sa.Column("credential_handle_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'invalid', 'revoked')",
            name="ck_gmail_integration_accounts_status",
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND credential_handle_ciphertext IS NULL) OR "
            "(status IN ('active', 'invalid') AND "
            "credential_handle_ciphertext IS NOT NULL)",
            name="ck_gmail_integration_accounts_handle_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            name="uq_gmail_integration_accounts_user",
        ),
    )
    op.create_index(
        "ix_gmail_integration_accounts_user_id",
        "gmail_integration_accounts",
        ["user_id"],
    )
    op.create_index(
        "ix_gmail_integration_accounts_user_status",
        "gmail_integration_accounts",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("gmail_integration_accounts")
    op.drop_table("persistent_task_triggers")
    op.drop_table("persistent_tasks")
