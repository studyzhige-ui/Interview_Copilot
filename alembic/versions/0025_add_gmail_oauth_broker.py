"""Add provider-specific encrypted Gmail OAuth broker storage.

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
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

    op.create_table(
        "gmail_oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_gmail_oauth_states_user"),
        sa.UniqueConstraint("state_digest", name="uq_gmail_oauth_states_digest"),
    )
    op.create_index(
        "ix_gmail_oauth_states_user_expires",
        "gmail_oauth_states",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("gmail_oauth_states")
    op.drop_table("gmail_oauth_credentials")
