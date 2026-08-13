"""Remove Gmail OAuth token storage from the application database.

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-13

Credential material is intentionally not copied during upgrade: operators
must reconnect Gmail into the independently configured credential broker.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    # Dropping the table is the security boundary. Existing account handles
    # safely fail as unavailable until each user explicitly reconnects.
    op.execute(
        sa.text(
            "UPDATE gmail_integration_accounts "
            "SET status = 'invalid', "
            "last_error_code = 'credential_store_reconnect_required' "
            "WHERE status <> 'revoked'"
        )
    )
    op.drop_table("gmail_oauth_credentials")


def downgrade() -> None:
    # Restore only the historical schema shape. Token rows are not recoverable
    # from the application DB and must never be fabricated during downgrade.
    op.create_table(
        "gmail_oauth_credentials",
        sa.Column("credential_handle", sa.String(length=256), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("google_subject", sa.String(length=255), nullable=False),
        sa.Column("scopes_json", _jsonb(), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=False),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("credential_handle"),
        sa.UniqueConstraint("user_id", name="uq_gmail_oauth_credentials_user"),
    )
