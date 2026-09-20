"""Review generation fencing and immutable answer correction receipts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "interview_records",
        sa.Column(
            "review_generation", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "interview_qa",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    value = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "interview_qa_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("qa_id", sa.String(), nullable=False),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("previous_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("before_json", value, nullable=False),
        sa.Column("after_json", value, nullable=False),
        sa.Column("invalidated_review_json", value, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_interview_qa_revisions_record_created",
        "interview_qa_revisions",
        ["record_id", "created_at"],
    )


def downgrade():
    connection = op.get_bind()
    if (
        connection.scalar(sa.text("SELECT count(*) FROM interview_qa_revisions"))
        or connection.scalar(
            sa.text(
                "SELECT count(*) FROM interview_records WHERE review_generation <> 0"
            )
        )
        or connection.scalar(
            sa.text("SELECT count(*) FROM interview_qa WHERE version <> 1")
        )
    ):
        raise RuntimeError("review_history_requires_export_before_rollback")
    op.drop_index(
        "ix_interview_qa_revisions_record_created", table_name="interview_qa_revisions"
    )
    op.drop_table("interview_qa_revisions")
    op.drop_column("interview_qa", "version")
    op.drop_column("interview_records", "review_generation")
