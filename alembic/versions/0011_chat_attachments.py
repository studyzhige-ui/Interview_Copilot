"""Persist conversation-scoped file attachments on durable turns.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("conversation_id", sa.String(), nullable=True),
    )
    op.create_index(
        op.f("ix_knowledge_documents_conversation_id"),
        "knowledge_documents",
        ["conversation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_knowledge_documents_conversation_id_conversations",
        "knowledge_documents",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "conversation_turns",
        sa.Column(
            "attachments_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("conversation_turns", "attachments_json", server_default=None)


def downgrade() -> None:
    op.drop_column("conversation_turns", "attachments_json")
    op.drop_constraint(
        "fk_knowledge_documents_conversation_id_conversations",
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_knowledge_documents_conversation_id"),
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "conversation_id")
