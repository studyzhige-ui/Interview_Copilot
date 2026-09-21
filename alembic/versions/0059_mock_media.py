"""Separate ephemeral media leases and generated/delivered/client playback facts."""

from alembic import op
import sqlalchemy as sa

revision = "0059"
down_revision = "0058"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "mock_media_leases",
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("client_session_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "mock_media_playback",
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("playback_id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generated_samples", sa.Integer(), nullable=False),
        sa.Column("delivered_samples", sa.Integer(), nullable=False),
        sa.Column("client_reported_samples", sa.Integer(), nullable=False),
        sa.Column("sample_rate", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "0 <= client_reported_samples AND client_reported_samples <= delivered_samples AND delivered_samples <= generated_samples",
            name="ck_media_sample_counts",
        ),
        sa.CheckConstraint(
            "status IN ('completed', 'interrupted', 'failed')",
            name="ck_media_playback_status",
        ),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM mock_media_playback LIMIT 1"))
        .first()
    ):
        raise RuntimeError("export_media_playback_before_downgrade")
    op.drop_table("mock_media_playback")
    op.drop_table("mock_media_leases")
