"""chat_messages: store Anthropic-style content blocks alongside text.

In the v3 → conversation-engine refactor (Stage G) we adopt Claude Code's
``Message.content = BetaContentBlock[]`` shape so the L2 agent can persist
its tool_use chain into chat history (and the frontend can render tool
calls as folded cards just like Claude Code / Codex). The L1 chat pipeline
continues to emit a single ``text`` block — only the storage shape
generalises.

Schema choice — additive, not replacing:
  * Keep ``chat_messages.content`` (TEXT). It remains the canonical plain-
    text preview shown in the session list, the value memory extraction
    reads, and a backward-compat read path for old rows.
  * Add ``chat_messages.content_blocks_json`` (TEXT, nullable). When
    present, it's a JSON array of blocks matching the Anthropic
    BetaContentBlock shape::
       [
         {"type": "text", "text": "..."},
         {"type": "tool_use", "id": "...", "name": "Bash", "input": {...}},
         {"type": "tool_result", "tool_use_id": "...", "content": "..."}
       ]
    Old rows have NULL here and frontend falls back to ``content``.

No data backfill — old rows are read-time backfilled by the GET endpoint
(synthesises ``[{type: "text", text: row.content}]`` when
``content_blocks_json`` is NULL).

Revision ID: 0006_chat_message_content_blocks
Revises: 0005_single_doc_one_liner
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0006_chat_message_content_blocks"
down_revision: Union[str, None] = "0005_single_doc_one_liner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("content_blocks_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "content_blocks_json")
