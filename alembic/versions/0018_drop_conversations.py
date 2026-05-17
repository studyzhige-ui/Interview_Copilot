"""revert the conversation-id experiment (0015 + 0017)

Earlier rounds split chat into ``chat_session → conversation → messages``
to let one session host multiple isolated threads. After a usability
review the model is going back to the simpler shape:

    interview_record (1) ── (N) chat_sessions ── (N) chat_messages

i.e. each session IS the conversation thread. Multi-thread brainstorming
now lives as multiple sibling sessions under the same interview record,
not as sub-conversations inside one session. So the migration:

  * drops ``chat_conversations`` (added in 0017)
  * drops ``chat_messages.conversation_id`` + its composite index (0015)
  * drops ``chat_sessions.current_conversation_id`` (0015)
  * TRUNCATEs ``chat_sessions`` + ``chat_messages`` — pre-existing test
    data already references the removed columns and the user explicitly
    asked for a clean slate. Cleaner than a hand-rolled backfill.

Also wipes the (now-orphan) ``memory_items`` rows whose source_session_id
points at the truncated sessions, so the memory layer doesn't keep
references to evidence that doesn't exist anymore.

Revision ID: 0018_drop_convs
Revises: 0017_chat_conv_table
Create Date: 2026-05-17

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "0018_drop_convs"
down_revision: Union[str, None] = "0017_chat_conv_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspect(op.get_bind()).get_columns(table))
    except Exception:
        return False


def _has_index(table: str, name: str) -> bool:
    try:
        return any(ix["name"] == name for ix in inspect(op.get_bind()).get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    # 1. Clean-slate user data — CASCADE handles chat_messages, the
    # chat_conversations rows fall away with their parent sessions if
    # the FK CASCADE we declared in 0017 is honoured; we belt-and-brace
    # by TRUNCATEing chat_conversations explicitly too.
    if _has_table("chat_conversations"):
        op.execute("TRUNCATE chat_conversations CASCADE")
    op.execute("TRUNCATE chat_sessions, chat_messages CASCADE")

    # Also drop any memory_items that were ingested from the truncated
    # sessions so the retrieval layer doesn't return stale facts whose
    # source has just been wiped. We leave user_profile rows alone for
    # now — migration 0019 will migrate them into the new doc column.
    op.execute(
        "DELETE FROM memory_items "
        "WHERE source_session_id IS NOT NULL "
        "AND type = 'interview_fact'"
    )

    # 2. Drop the chat_conversations table outright.
    if _has_table("chat_conversations"):
        if _has_index("chat_conversations", "ix_chat_conversations_session_created"):
            op.drop_index(
                "ix_chat_conversations_session_created",
                table_name="chat_conversations",
            )
        op.drop_table("chat_conversations")

    # 3. Drop chat_messages.conversation_id + its composite index.
    if _has_index("chat_messages", "ix_chat_msgs_session_conv_seq"):
        op.drop_index("ix_chat_msgs_session_conv_seq", table_name="chat_messages")
    if _has_column("chat_messages", "conversation_id"):
        op.drop_column("chat_messages", "conversation_id")

    # 4. Drop chat_sessions.current_conversation_id.
    if _has_column("chat_sessions", "current_conversation_id"):
        op.drop_column("chat_sessions", "current_conversation_id")


def downgrade() -> None:
    # Intentionally non-reversible. Restoring the conversation hierarchy
    # would require replaying 0015 + 0017 against the new (now flatter)
    # message table, and we explicitly TRUNCATEd to drop test data.
    # The chain only ever moves forward from here.
    raise NotImplementedError(
        "0018_drop_convs is one-way. Re-introducing per-session "
        "conversations would require a new forward migration."
    )
