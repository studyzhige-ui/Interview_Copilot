"""Use JSONB for operational structures and timezone-aware UTC timestamps.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NATIVE_JSON_COLUMNS = {
    "agent_tool_calls": ("arguments_json", "result_json"),
    "conversation_capability_states": (
        "discovered_skills_json",
        "permissions_json",
        "tool_history_json",
    ),
    "conversation_turns": (
        "capability_snapshot_json",
        "loaded_schemas_json",
        "budget_json",
    ),
    "interview_qa": ("answer_quality_json",),
    "session_tasks": ("blocked_by_json", "evidence_json"),
    "user_mcp_servers": ("args_json",),
}

_TEXT_JSON_COLUMNS = {
    "memory_ability_states": ("evidence_refs_json",),
    "memory_audit_logs": ("source_message_range_json",),
    "outbox_jobs": ("payload_json",),
}

_TIMESTAMP_COLUMNS = {
    "users": (
        "password_changed_at",
        "last_dreamed_at",
        "created_at",
        "updated_at",
    ),
    "conversations": ("archived_at", "created_at", "updated_at"),
    "file_assets": ("created_at", "updated_at", "deleted_at"),
    "memory_ability_states": (
        "last_evidence_at",
        "created_at",
        "updated_at",
        "archived_at",
    ),
    "memory_documents": ("last_discussed_at", "created_at", "updated_at"),
    "outbox_jobs": ("next_run_at", "locked_at", "created_at", "updated_at"),
    "user_mcp_servers": ("checked_at", "created_at", "updated_at"),
    "user_model_credentials": (
        "last_validated_at",
        "created_at",
        "updated_at",
    ),
    "user_model_provider_settings": ("created_at", "updated_at"),
    "user_model_selections": ("created_at", "updated_at"),
    "user_skills": ("created_at", "updated_at"),
    "agent_checkpoints": ("updated_at",),
    "conversation_capability_states": ("updated_at",),
    "conversation_messages": ("created_at",),
    "conversation_turns": (
        "heartbeat_at",
        "created_at",
        "started_at",
        "completed_at",
    ),
    "knowledge_documents": ("deleted_at", "created_at", "updated_at"),
    "memory_audit_logs": ("created_at",),
    "resumes": ("created_at", "updated_at", "archived_at"),
    "session_tasks": ("created_at", "updated_at"),
    "agent_tool_calls": ("started_at", "completed_at"),
    "document_chunks": ("deleted_at", "created_at", "updated_at"),
    "interview_records": (
        "created_at",
        "updated_at",
        "completed_at",
        "last_dreamed_at",
    ),
    "resume_sections": ("created_at",),
    "interview_qa": ("analyzed_at", "created_at"),
    "interview_transcripts": ("created_at", "updated_at"),
    "mock_interview_runtime": (
        "started_at",
        "ended_at",
        "last_activity_at",
        "updated_at",
        "answer_claimed_at",
    ),
}


def upgrade() -> None:
    for table, columns in _NATIVE_JSON_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.JSON(),
                type_=postgresql.JSONB(),
                postgresql_using=f"{column}::jsonb",
            )
    for table, columns in _TEXT_JSON_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.Text(),
                type_=postgresql.JSONB(),
                postgresql_using=f"NULLIF({column}, '')::jsonb",
            )
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=False),
                type_=sa.DateTime(timezone=True),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )


def downgrade() -> None:
    for table, columns in reversed(tuple(_TIMESTAMP_COLUMNS.items())):
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(timezone=False),
                postgresql_using=f"{column} AT TIME ZONE 'UTC'",
            )
    for table, columns in _TEXT_JSON_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=postgresql.JSONB(),
                type_=sa.Text(),
                postgresql_using=f"{column}::text",
            )
    for table, columns in _NATIVE_JSON_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=postgresql.JSONB(),
                type_=sa.JSON(),
                postgresql_using=f"{column}::json",
            )
