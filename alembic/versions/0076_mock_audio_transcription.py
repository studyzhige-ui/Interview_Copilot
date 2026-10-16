"""Persist mock recording tasks for the shared transcription worker."""

from alembic import op
import sqlalchemy as sa
from app.db.types import UTCDateTime

revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mock_audio_transcriptions",
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("question_message_id", sa.Integer(), nullable=False),
        sa.Column(
            "audio_file_asset_id",
            sa.String(),
            sa.ForeignKey("file_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime()),
        sa.Column("heartbeat_at", UTCDateTime()),
        sa.Column("completed_at", UTCDateTime()),
        sa.CheckConstraint(
            "status IN ('queued','transcribing','completed','failed')",
            name="ck_mock_audio_transcription_status",
        ),
    )


def downgrade():
    op.drop_table("mock_audio_transcriptions")
