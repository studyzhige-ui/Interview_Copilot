"""Close the ORM↔Alembic drift surface found in the round-2 audit.

The DB audit ran ``alembic check`` and found 16 ORM-vs-schema
diffs. Three of those have customer-facing impact and are fixed
here. The rest are ORM-side declarations that should mirror the
schema but don't — those are fixed in this same PR by adding
``__table_args__`` to each affected model (no schema migration
needed; just stops ``alembic revision --autogenerate`` from
generating spurious DROP INDEX statements).

What this migration changes in the DB:

1. ``user_api_keys`` — adds ``UniqueConstraint(user_id, provider)``.
   The ORM has declared this since day one, but 0001_baseline
   only created the per-column ``ix_user_api_keys_user_id`` index
   without the unique constraint. ``user_api_key_service`` upsert
   logic depends on the constraint to deduplicate on conflict —
   without it, two parallel saves of the same (user, provider)
   pair would both succeed and leave duplicate rows.

2. ``strategy_docs`` + ``habit_docs`` — promote the per-user
   indexes (``ix_strategy_docs_user_id``, ``ix_habit_docs_user_id``)
   from non-unique to UNIQUE. The ORM declares them unique
   (``Column(... unique=True)``), the service layer assumes one
   row per user (single-doc shape), and the patch dispatchers
   call ``upsert`` semantics — but the DB only had a per-column
   unique constraint (column-level, separate from the index).
   This makes the unique-by-user property visible AT the index
   so query planners can use it, and so a future
   ``autogenerate`` doesn't emit a spurious diff.

3. ``chat_messages`` — adds ``UniqueConstraint(session_id, seq)``.
   ``chat_history_service.append`` reads MAX(seq) then INSERTs
   ``seq + 1``; two parallel turns on the same session can both
   read the same MAX and write identical seqs. The read side
   then orders by seq, so duplicate-seq rows silently shuffle.
   Adding the constraint makes the second writer's INSERT fail
   loud at the DB layer. **Caller behaviour today**: the service
   has no IntegrityError-specific retry, so the second writer's
   exception will bubble up — the API layer surfaces a 500 to
   the user. That's a deliberate, observable failure rather
   than the pre-fix silent shuffle. Hardening ``append_turn``
   with an IntegrityError retry is a follow-up tracked
   separately (it would mask the race but requires careful
   token-budget accounting).

   **Pre-flight check (run BEFORE this migration on a copy of
   prod)** — if any rows already collide, the migration will
   abort. Identify them with::

       SELECT session_id, seq, COUNT(*) AS dup
       FROM chat_messages
       GROUP BY 1, 2
       HAVING COUNT(*) > 1
       ORDER BY dup DESC;

   then either renumber the duplicates or delete the orphans
   before re-running the migration.

4. ``chat_sessions`` — adds composite index ``ix_chat_sessions_
   user_updated (user_id, updated_at)`` to support the session
   list's ``WHERE user_id=? ORDER BY updated_at DESC LIMIT 20``
   query. The existing ``ix_chat_sessions_user_type_arch`` is
   useless for that sort. Heavy users with thousands of
   sessions were paying a sort-the-whole-user-history cost
   per dropdown open.

Revision ID: 0010_orm_alembic_drift_fixup
Revises: 0009_add_record_cascade
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0010_orm_alembic_drift_fixup"
down_revision: Union[str, None] = "0009_add_record_cascade"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. user_api_keys: add (user_id, provider) unique ────────────────
    op.create_unique_constraint(
        "uq_user_api_keys_user_provider",
        "user_api_keys",
        ["user_id", "provider"],
    )

    # ── 2. strategy_docs / habit_docs: collapse redundant uniqueness ────
    # 0002 created BOTH a column-level UNIQUE constraint (via
    # ``Column(user_id, ..., unique=True)`` → Postgres auto-names it
    # ``<table>_user_id_key``) AND a separate non-unique index
    # ``ix_<table>_user_id``. Two index writes per insert for the same
    # column, plus a perpetual ORM-vs-schema diff because the ORM tried
    # to express the same idea in different shapes.
    # Resolution: drop the column-level constraint (auto-named index),
    # promote ``ix_<table>_user_id`` to unique — one B-tree index,
    # ORM and schema both agree on it.
    # Failure mode: if any duplicate-by-user_id rows exist (single-doc
    # shape should make this impossible, but check anyway), unique-
    # index creation aborts. That's the right behaviour — data
    # corruption surfaces at migration time, not at read time.
    op.drop_constraint(
        "strategy_docs_user_id_key", "strategy_docs", type_="unique",
    )
    op.drop_index("ix_strategy_docs_user_id", table_name="strategy_docs")
    op.create_index(
        "ix_strategy_docs_user_id",
        "strategy_docs",
        ["user_id"],
        unique=True,
    )
    op.drop_constraint(
        "habit_docs_user_id_key", "habit_docs", type_="unique",
    )
    op.drop_index("ix_habit_docs_user_id", table_name="habit_docs")
    op.create_index(
        "ix_habit_docs_user_id",
        "habit_docs",
        ["user_id"],
        unique=True,
    )

    # ── 3. chat_messages: add (session_id, seq) unique constraint ───────
    op.create_unique_constraint(
        "uq_chat_messages_session_seq",
        "chat_messages",
        ["session_id", "seq"],
    )

    # ── 4. chat_sessions: add (user_id, updated_at) composite index ─────
    op.create_index(
        "ix_chat_sessions_user_updated",
        "chat_sessions",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_sessions_user_updated", table_name="chat_sessions")
    op.drop_constraint(
        "uq_chat_messages_session_seq",
        "chat_messages",
        type_="unique",
    )
    op.drop_index("ix_habit_docs_user_id", table_name="habit_docs")
    op.create_index("ix_habit_docs_user_id", "habit_docs", ["user_id"])
    op.create_unique_constraint(
        "habit_docs_user_id_key", "habit_docs", ["user_id"],
    )
    op.drop_index("ix_strategy_docs_user_id", table_name="strategy_docs")
    op.create_index("ix_strategy_docs_user_id", "strategy_docs", ["user_id"])
    op.create_unique_constraint(
        "strategy_docs_user_id_key", "strategy_docs", ["user_id"],
    )
    op.drop_constraint(
        "uq_user_api_keys_user_provider",
        "user_api_keys",
        type_="unique",
    )
