"""Add closed Canva and Notion OAuth connection state.

Revision ID: 0041
Revises: 0040
Create Date: 2026-08-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "external_plugin_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("account_hint", sa.String(length=320), nullable=False),
        sa.Column(
            "scopes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("credential_handle_ciphertext", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('canva', 'notion')",
            name="ck_external_plugin_accounts_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'invalid', 'revoked')",
            name="ck_external_plugin_accounts_status",
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND credential_handle_ciphertext IS NULL) OR "
            "(status IN ('active', 'invalid') AND credential_handle_ciphertext IS NOT NULL)",
            name="ck_external_plugin_accounts_handle_state",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_external_plugin_accounts_user_provider"
        ),
    )
    op.create_index(
        "ix_external_plugin_accounts_user_id", "external_plugin_accounts", ["user_id"]
    )
    op.create_index(
        "ix_external_plugin_accounts_user_status",
        "external_plugin_accounts",
        ["user_id", "status"],
    )
    op.create_table(
        "external_plugin_oauth_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("state_digest", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_ciphertext", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provider IN ('canva', 'notion')",
            name="ck_external_plugin_oauth_states_provider",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "state_digest", name="uq_external_plugin_oauth_states_digest"
        ),
        sa.UniqueConstraint(
            "user_id", "provider", name="uq_external_plugin_oauth_states_user_provider"
        ),
    )
    op.create_index(
        "ix_external_plugin_oauth_states_user_expires",
        "external_plugin_oauth_states",
        ["user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_external_plugin_oauth_states_user_expires",
        table_name="external_plugin_oauth_states",
    )
    op.drop_table("external_plugin_oauth_states")
    op.drop_index(
        "ix_external_plugin_accounts_user_status", table_name="external_plugin_accounts"
    )
    op.drop_index(
        "ix_external_plugin_accounts_user_id", table_name="external_plugin_accounts"
    )
    op.drop_table("external_plugin_accounts")
