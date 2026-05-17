"""create chat_conversations table + wipe legacy general sessions

Two coupled changes that have to land together:

1. **chat_conversations table** — until now, a "conversation" was just a
   string id stamped on each ``chat_messages`` row (introduced in 0015).
   That worked for storage but left no place for a *title*, ``created_at``
   timestamp, or any other per-conversation metadata. So a session's UI
   had to label tabs by "last message timestamp" which is both ugly
   and useless before the first message lands. Promote conversations
   to a real first-class row so we can: rename them, sort them by
   creation time, render meaningful titles ("对话 1") in the dropdown.

2. **Wipe legacy ``session_type='general'`` rows.** General chat is
   moving out of the review page into its own dedicated ``/general-chat``
   route. The existing general session data was test-only — clean slate
   is simpler than migrating to the new page's data model.

Backfill strategy for chat_conversations:
  * Distinct ``(session_id, conversation_id)`` pairs become rows.
  * Title defaults to ``"对话 N"`` where N is the ordinal within that
    session (ordered by earliest-message ``created_at`` so the oldest
    conversation gets "对话 1"). Sessions with one conversation just
    get "对话 1" — non-distracting default; user can rename via the
    new PATCH endpoint.

Revision ID: 0017_chat_conv_table
Revises: 0016_user_mem_recall
Create Date: 2026-05-17

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0017_chat_conv_table"
down_revision: Union[str, None] = "0016_user_mem_recall"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    return inspect(bind).has_table(table)


def upgrade() -> None:
    # ── 1. Create chat_conversations ───────────────────────────────
    if not _has_table("chat_conversations"):
        op.create_table(
            "chat_conversations",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column(
                "session_id",
                sa.String(),
                sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("title", sa.String(), nullable=False, server_default="对话"),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_chat_conversations_session_created",
            "chat_conversations",
            ["session_id", "created_at"],
        )

    # ── 2. Wipe legacy general sessions FIRST so the backfill below
    # doesn't also create chat_conversations rows for soon-to-be-deleted
    # sessions. Cascade via the existing FK from chat_messages.session_id
    # to chat_sessions.id (declared ON DELETE CASCADE in 0001? check).
    # If not cascading at the FK level, delete messages explicitly.
    op.execute(
        "DELETE FROM chat_messages WHERE session_id IN ("
        "  SELECT id FROM chat_sessions WHERE session_type = 'general'"
        ")"
    )
    op.execute("DELETE FROM chat_sessions WHERE session_type = 'general'")

    # ── 3. Backfill chat_conversations from existing messages.
    # PostgreSQL-flavoured SQL — uses ROW_NUMBER() OVER PARTITION BY to
    # compute per-session ordinals based on first-message time.
    op.execute("""
        INSERT INTO chat_conversations (id, session_id, title, created_at, updated_at)
        SELECT
            cm.conversation_id AS id,
            cm.session_id      AS session_id,
            '对话 ' || ROW_NUMBER() OVER (
                PARTITION BY cm.session_id
                ORDER BY MIN(cm.created_at)
            ) AS title,
            MIN(cm.created_at) AS created_at,
            MAX(cm.created_at) AS updated_at
        FROM chat_messages cm
        WHERE cm.conversation_id IS NOT NULL
        GROUP BY cm.session_id, cm.conversation_id
        ON CONFLICT (id) DO NOTHING
    """)

    # ── 4. Ensure every chat_session has at least one chat_conversations
    # row pointing at its ``current_conversation_id`` (a brand-new
    # session has no messages yet, so step 3 doesn't catch it). This
    # keeps the UI invariant "every session has ≥1 conversation in the
    # dropdown" true after the migration.
    op.execute("""
        INSERT INTO chat_conversations (id, session_id, title, created_at, updated_at)
        SELECT cs.current_conversation_id, cs.id, '对话 1', cs.created_at, cs.updated_at
        FROM chat_sessions cs
        WHERE cs.current_conversation_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM chat_conversations cc WHERE cc.id = cs.current_conversation_id
          )
    """)


def downgrade() -> None:
    if _has_table("chat_conversations"):
        op.drop_index("ix_chat_conversations_session_created", table_name="chat_conversations")
        op.drop_table("chat_conversations")
    # We don't try to restore the wiped general sessions — that data was
    # test-only and shipping a restore path adds complexity for no gain.
