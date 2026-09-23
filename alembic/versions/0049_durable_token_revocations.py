"""Persist token consumption and retire the Redis revocation authority.

Stop API/workers during migration. Existing sessions must sign in again.
"""

from alembic import op
import sqlalchemy as sa

revision = "0049"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "token_revocations",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_token_revocations_expires_at", "token_revocations", ["expires_at"]
    )
    # Redis may already contain revoked tokens. Invalidate every previously
    # issued token so switching authorities cannot resurrect any of them.
    op.execute("UPDATE users SET token_version = token_version + 1")


def downgrade():
    # Do not decrement token_version: revocation is irreversible.
    op.drop_index("ix_token_revocations_expires_at", table_name="token_revocations")
    op.drop_table("token_revocations")
