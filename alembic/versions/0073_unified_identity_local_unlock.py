"""Add cloud-to-local identity binding without changing existing owner IDs."""

from alembic import op
import sqlalchemy as sa

revision = "0073"
down_revision = "0072"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "external_identities",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(36), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issuer", "subject", name="uq_external_identity_subject"),
    )
    op.create_index("ix_external_identities_email", "external_identities", ["email"])
    op.create_table(
        "local_unlock_credentials",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "credential_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM external_identities)"))
        .scalar()
    ):
        raise RuntimeError(
            "Existing identity mappings must be backed up and explicitly migrated before downgrade"
        )
    op.drop_table("local_unlock_credentials")
    op.drop_table("external_identities")
