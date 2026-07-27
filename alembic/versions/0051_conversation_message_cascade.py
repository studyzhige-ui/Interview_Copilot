"""Cascade conversation deletion to its transcript rows.

Revision ID: 0051_conversation_msg_cascade
Revises: 0050_single_answer_model
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "0051_conversation_msg_cascade"
down_revision: Union[str, None] = "0050_single_answer_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _conversation_fk_name() -> str:
    connection = op.get_bind()
    for foreign_key in inspect(connection).get_foreign_keys("conversation_messages"):
        if (
            foreign_key.get("referred_table") == "conversations"
            and foreign_key.get("constrained_columns") == ["conversation_id"]
            and foreign_key.get("name")
        ):
            return str(foreign_key["name"])
    raise RuntimeError("conversation_messages conversation FK was not found")


def _replace_foreign_key(*, ondelete: str | None) -> None:
    op.drop_constraint(
        _conversation_fk_name(),
        "conversation_messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_conversation_messages_conversation_id",
        "conversation_messages",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _replace_foreign_key(ondelete="CASCADE")


def downgrade() -> None:
    _replace_foreign_key(ondelete=None)
