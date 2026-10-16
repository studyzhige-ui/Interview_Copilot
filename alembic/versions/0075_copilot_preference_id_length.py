"""Fit the existing pref_ + UUID identifier without changing its identity."""

from alembic import op
import sqlalchemy as sa

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "copilot_preferences", "id", existing_type=sa.String(35), type_=sa.String(37)
    )


def downgrade():
    # PostgreSQL rejects narrowing populated 37-character IDs rather than
    # truncating identities. Existing preference rows must be preserved.
    op.alter_column(
        "copilot_preferences", "id", existing_type=sa.String(37), type_=sa.String(35)
    )
