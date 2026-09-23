"""Align persisted types and indexes; retire unused legacy memory cursors.

Take a backup and stop writers before upgrading. Downgrade recreates retired
operational cursor columns empty; their values are not domain history.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

JSON_COLUMNS = (
    ("agent_tool_calls", "timeline_json"),
    ("agent_tool_calls", "receipt_refs_json"),
    ("agent_tool_calls", "resource_identities_json"),
    ("context_checkpoints", "state"),
    ("conversation_deletion_receipts", "resource_identities_json"),
    ("gmail_observation_review_cards", "new_opportunity_json"),
    ("long_term_agent_memories", "evidence_json"),
    ("memory_extractions", "candidates_json"),
    ("memory_workspaces", "index_json"),
)


def upgrade():
    for table, column in JSON_COLUMNS:
        op.alter_column(
            table, column, type_=postgresql.JSONB(), postgresql_using=f"{column}::jsonb"
        )
    op.alter_column(
        "token_revocations",
        "expires_at",
        type_=sa.DateTime(timezone=True),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )
    for column in ("conversation_id", "turn_id"):
        op.create_index(
            f"ix_application_operations_{column}", "application_operations", [column]
        )
    op.drop_constraint(
        "artifact_resume_states_artifact_id_key",
        "artifact_resume_states",
        type_="unique",
    )
    op.drop_index(
        "ix_artifact_resume_states_artifact_id", table_name="artifact_resume_states"
    )
    op.create_index(
        "ix_artifact_resume_states_artifact_id",
        "artifact_resume_states",
        ["artifact_id"],
        unique=True,
    )
    op.drop_column("conversations", "memory_extraction_cursor")
    op.drop_index(
        "ix_interview_records_user_last_dreamed", table_name="interview_records"
    )
    op.drop_column("interview_records", "last_dreamed_at")
    op.drop_column("users", "last_dreamed_at")


def downgrade():
    op.add_column("users", sa.Column("last_dreamed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "interview_records", sa.Column("last_dreamed_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_interview_records_user_last_dreamed",
        "interview_records",
        ["user_id", "last_dreamed_at"],
    )
    op.add_column("conversations", sa.Column("memory_extraction_cursor", sa.Integer()))
    op.drop_index(
        "ix_artifact_resume_states_artifact_id", table_name="artifact_resume_states"
    )
    op.create_unique_constraint(
        "artifact_resume_states_artifact_id_key",
        "artifact_resume_states",
        ["artifact_id"],
    )
    op.create_index(
        "ix_artifact_resume_states_artifact_id",
        "artifact_resume_states",
        ["artifact_id"],
    )
    for column in ("conversation_id", "turn_id"):
        op.drop_index(
            f"ix_application_operations_{column}", table_name="application_operations"
        )
    op.alter_column(
        "token_revocations",
        "expires_at",
        type_=sa.DateTime(),
        postgresql_using="expires_at AT TIME ZONE 'UTC'",
    )
    for table, column in JSON_COLUMNS:
        op.alter_column(
            table, column, type_=sa.JSON(), postgresql_using=f"{column}::json"
        )
