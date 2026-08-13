"""Add durable model dispatch and three-layer Skill runtime state.

Revision ID: 0032
Revises: 0031
Create Date: 2026-08-13
"""

import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "agent_model_dispatches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("call_id", sa.String(length=128), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dispatch_generation", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=16), server_default="running", nullable=False
        ),
        sa.Column("partial_text", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "usage_json",
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled','unknown')",
            name="ck_agent_model_dispatches_status",
        ),
        sa.ForeignKeyConstraint(
            ["turn_id"], ["conversation_turns.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "turn_id", "call_id", name="uq_agent_model_dispatches_turn_call"
        ),
    )
    op.create_index(
        "ix_agent_model_dispatches_turn_id", "agent_model_dispatches", ["turn_id"]
    )
    op.create_index(
        "ix_agent_model_dispatches_user_id", "agent_model_dispatches", ["user_id"]
    )

    op.add_column(
        "user_skills",
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "user_skills", sa.Column("content_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "user_skills",
        sa.Column(
            "source", sa.String(length=32), server_default="user", nullable=False
        ),
    )
    op.add_column(
        "user_skills",
        sa.Column(
            "applicable_profiles_json",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_skills",
        sa.Column(
            "required_tools_json",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "user_skills",
        sa.Column(
            "allowed_tools_json",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, content FROM user_skills")).mappings()
    for row in rows:
        digest = hashlib.sha256(str(row["content"]).encode("utf-8")).hexdigest()
        bind.execute(
            sa.text("UPDATE user_skills SET content_hash = :digest WHERE id = :id"),
            {"digest": digest, "id": row["id"]},
        )
    op.alter_column("user_skills", "content_hash", nullable=False)

    op.create_table(
        "user_skill_resources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["user_skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "path", name="uq_user_skill_resources_path"),
    )
    op.create_index(
        "ix_user_skill_resources_skill_id", "user_skill_resources", ["skill_id"]
    )

    op.create_table(
        "agent_task_skill_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_task_id", sa.String(length=35), nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("skill_name", sa.String(length=64), nullable=False),
        sa.Column("skill_source", sa.String(length=32), nullable=False),
        sa.Column("skill_revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_task_id"], ["agent_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["user_skills.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_task_id", "skill_name", name="uq_agent_task_skill_bindings_task_name"
        ),
    )
    op.create_index(
        "ix_agent_task_skill_bindings_agent_task_id",
        "agent_task_skill_bindings",
        ["agent_task_id"],
    )
    op.create_index(
        "ix_agent_task_skill_bindings_skill_id",
        "agent_task_skill_bindings",
        ["skill_id"],
    )

    op.add_column(
        "persistent_tasks",
        sa.Column(
            "skill_refs_json",
            _jsonb(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("persistent_tasks", "skill_refs_json")
    op.drop_index(
        "ix_agent_task_skill_bindings_skill_id", table_name="agent_task_skill_bindings"
    )
    op.drop_index(
        "ix_agent_task_skill_bindings_agent_task_id",
        table_name="agent_task_skill_bindings",
    )
    op.drop_table("agent_task_skill_bindings")
    op.drop_index("ix_user_skill_resources_skill_id", table_name="user_skill_resources")
    op.drop_table("user_skill_resources")
    op.drop_column("user_skills", "allowed_tools_json")
    op.drop_column("user_skills", "required_tools_json")
    op.drop_column("user_skills", "applicable_profiles_json")
    op.drop_column("user_skills", "source")
    op.drop_column("user_skills", "content_hash")
    op.drop_column("user_skills", "revision")
    op.drop_index(
        "ix_agent_model_dispatches_user_id", table_name="agent_model_dispatches"
    )
    op.drop_index(
        "ix_agent_model_dispatches_turn_id", table_name="agent_model_dispatches"
    )
    op.drop_table("agent_model_dispatches")
