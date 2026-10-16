"""Add workspace metadata and document drafts without rewriting history."""

from alembic import op
import sqlalchemy as sa
from app.db.types import JSONValue, UTCDateTime

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "artifact_versions", sa.Column("document_json", JSONValue, nullable=True)
    )
    op.create_table(
        "opportunity_details",
        sa.Column(
            "opportunity_id",
            sa.String(35),
            sa.ForeignKey("job_opportunities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("contacts", JSONValue, nullable=False),
        sa.Column("hidden_at", UTCDateTime(), nullable=True),
    )
    op.create_table(
        "document_drafts",
        sa.Column(
            "artifact_id",
            sa.String(128),
            sa.ForeignKey("artifacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("base_version_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("data", JSONValue, nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("document_drafts")
    op.drop_table("opportunity_details")
    op.drop_column("artifact_versions", "document_json")
