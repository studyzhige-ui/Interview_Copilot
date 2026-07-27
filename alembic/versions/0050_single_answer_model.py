"""Remove obsolete per-user model-role selections.

Users now choose one ``primary`` answer model shared by chat, Agent and mock
interview. Router and worker models are platform-owned configuration.

Revision ID: 0050_single_answer_model
Revises: 0049_turn_ownership
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0050_single_answer_model"
down_revision: Union[str, None] = "0049_turn_ownership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM user_model_selections WHERE role <> 'primary'"))


def downgrade() -> None:
    # Removed preferences cannot be reconstructed; the previous runtime
    # already treated missing role rows as defaults.
    pass
