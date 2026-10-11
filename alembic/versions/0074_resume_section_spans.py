"""Version-bound semantic offsets for canonical resume parsing."""

from alembic import op
import sqlalchemy as sa

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "artifact_resume_states",
        sa.Column("section_spans_json", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("artifact_resume_states", "section_spans_json")
