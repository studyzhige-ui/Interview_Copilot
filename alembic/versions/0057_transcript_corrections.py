"""Append-only transcript correction receipts, without rewriting historical evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "transcript_corrections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("previous_transcript_id", sa.String(), nullable=False),
        sa.Column("transcript_id", sa.String(), nullable=False),
        sa.Column("command_sha256", sa.String(64), nullable=False),
        sa.Column("command_json", postgresql.JSONB(), nullable=False),
        sa.Column("confirmed_roles_json", postgresql.JSONB(), nullable=False),
        sa.Column("invalidated_review_json", postgresql.JSONB(), nullable=False),
        sa.Column("review_generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "record_id", "request_id", name="uq_transcript_correction_request"
        ),
    )
    op.create_index(
        "ix_transcript_correction_history",
        "transcript_corrections",
        ["record_id", "created_at", "request_id"],
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM transcript_corrections LIMIT 1"))
        .first()
    ):
        raise RuntimeError("transcript_history_requires_export_before_downgrade")
    op.drop_index(
        "ix_transcript_correction_history", table_name="transcript_corrections"
    )
    op.drop_table("transcript_corrections")
