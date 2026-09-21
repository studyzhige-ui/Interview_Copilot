"""Durable media generation leases and bounded browser playback receipts."""

from alembic import op
import sqlalchemy as sa

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mock_media_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_session_id", sa.String(36), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pending_request_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "record_id", "client_session_id", name="uq_mock_media_client"
        ),
    )
    op.create_index(
        "ix_mock_media_sessions_record_id", "mock_media_sessions", ["record_id"]
    )
    op.create_table(
        "mock_media_playback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("mock_media_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("question_message_id", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("audio_sha256", sa.String(64), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("generated_samples", sa.Integer(), nullable=False),
        sa.Column("reported_samples", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "generated_samples > 0 AND reported_samples >= 0 AND reported_samples <= generated_samples",
            name="ck_media_sample_bounds",
        ),
    )
    op.create_index(
        "ix_mock_media_playback_session_id", "mock_media_playback", ["session_id"]
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM mock_media_sessions LIMIT 1"))
        .first()
    ):
        raise RuntimeError("media_receipts_require_export_before_downgrade")
    op.drop_table("mock_media_playback")
    op.drop_table("mock_media_sessions")
