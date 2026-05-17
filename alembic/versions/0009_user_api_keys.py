"""add user_api_keys table for encrypted per-user provider keys

Revision ID: 0009_user_api_keys
Revises: 0008_drop_legacy
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009_user_api_keys"
down_revision: Union[str, None] = "0008_drop_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        # Fernet ciphertext (base64-urlsafe text, ~100-200 chars typical)
        sa.Column("key_ciphertext", sa.Text(), nullable=False),
        # First / last 4 chars of the plaintext for the UI's "sk-****abcd" hint.
        # Not enough to leak the key, just enough for the user to recognize it.
        sa.Column("key_masked", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_api_keys_user_provider"),
    )
    op.create_index("ix_user_api_keys_user_id", "user_api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_api_keys_user_id", table_name="user_api_keys")
    op.drop_table("user_api_keys")
