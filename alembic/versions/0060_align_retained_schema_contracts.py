"""Retain inert legacy metadata columns after the published main baseline.

Main 0052 retired these columns. Reintroduce nullable, unused columns to keep
PR2 historical metadata compatible without rewriting published history. Values
already retired by main cannot be reconstructed; PR2 adoption preserves them.
"""

from alembic import op
import sqlalchemy as sa

revision = "0060"
down_revision = "0052"
branch_labels = depends_on = None


def upgrade():
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


def downgrade():
    # These fields are inert metadata. Refuse to discard retained values.
    for table, column in (
        ("users", "last_dreamed_at"),
        ("interview_records", "last_dreamed_at"),
        ("conversations", "memory_extraction_cursor"),
    ):
        if (
            op.get_bind()
            .execute(
                sa.text(
                    f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {column} IS NOT NULL)"
                )
            )
            .scalar()
        ):
            raise RuntimeError("Back up retained legacy metadata before downgrade")
    op.drop_column("conversations", "memory_extraction_cursor")
    op.drop_index(
        "ix_interview_records_user_last_dreamed", table_name="interview_records"
    )
    op.drop_column("interview_records", "last_dreamed_at")
    op.drop_column("users", "last_dreamed_at")
