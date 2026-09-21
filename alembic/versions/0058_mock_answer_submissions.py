"""Persist model-turn request receipts independently of the live runtime."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mock_answer_submissions",
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("question_message_id", sa.Integer(), nullable=False),
        sa.Column("command_sha256", sa.String(64), nullable=False),
        sa.Column("claim_generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'unknown')",
            name="ck_mock_answer_submission_status",
        ),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM mock_answer_submissions LIMIT 1"))
        .first()
    ):
        raise RuntimeError("mock_answer_receipts_require_export_before_downgrade")
    op.drop_table("mock_answer_submissions")
