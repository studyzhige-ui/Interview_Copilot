"""Align JSONB and indexes without deleting historical user metadata.

Revision ID: 0047
Revises: 0046
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None

# These columns were introduced after migration 0004 and used portable JSON
# while the ORM's PostgreSQL variant is JSONB. Conversion preserves values.
_JSON_COLUMNS = (
    ("agent_tool_calls", "timeline_json", False),
    ("agent_tool_calls", "receipt_refs_json", False),
    ("agent_tool_calls", "resource_identities_json", False),
    ("context_checkpoints", "state", False),
    ("conversation_deletion_receipts", "resource_identities_json", False),
    ("gmail_observation_review_cards", "new_opportunity_json", True),
    ("long_term_agent_memories", "evidence_json", False),
    ("memory_extractions", "candidates_json", False),
    ("memory_workspaces", "index_json", False),
)


def upgrade():
    for table, column, nullable in _JSON_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.JSON(),
            type_=postgresql.JSONB(),
            existing_nullable=nullable,
            postgresql_using=f'"{column}"::jsonb',
        )
    op.create_index(
        "ix_application_operations_conversation_id",
        "application_operations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_application_operations_turn_id", "application_operations", ["turn_id"]
    )
    # Keep the old UNIQUE constraint until the new unique index exists.
    op.drop_index(
        "ix_artifact_resume_states_artifact_id", table_name="artifact_resume_states"
    )
    op.create_index(
        "ix_artifact_resume_states_artifact_id",
        "artifact_resume_states",
        ["artifact_id"],
        unique=True,
    )
    op.drop_constraint(
        "artifact_resume_states_artifact_id_key",
        "artifact_resume_states",
        type_="unique",
    )


def downgrade():
    op.create_unique_constraint(
        "artifact_resume_states_artifact_id_key",
        "artifact_resume_states",
        ["artifact_id"],
    )
    op.drop_index(
        "ix_artifact_resume_states_artifact_id", table_name="artifact_resume_states"
    )
    op.create_index(
        "ix_artifact_resume_states_artifact_id",
        "artifact_resume_states",
        ["artifact_id"],
        unique=False,
    )
    op.drop_index(
        "ix_application_operations_turn_id", table_name="application_operations"
    )
    op.drop_index(
        "ix_application_operations_conversation_id", table_name="application_operations"
    )
    for table, column, nullable in reversed(_JSON_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=postgresql.JSONB(),
            type_=sa.JSON(),
            existing_nullable=nullable,
            postgresql_using=f'"{column}"::json',
        )
