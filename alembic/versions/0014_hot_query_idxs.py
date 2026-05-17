"""hot-query composite indexes that match the actual filter+order shape

Audited the ORM call sites for ``WHERE ... ORDER BY ... LIMIT ...`` patterns
and added composites where the existing single-column indexes can't satisfy
the planner in one B-tree scan:

  * chat_sessions (user_id, session_type, archived_at)
      get_in_progress_mock + sessions list both filter on this exact triple.
  * knowledge_documents (user_id, category)
      LibraryPage filter (left sidebar) + RAG retrieval scoping.
  * memory_items (user_id, type, normalized_key)
      Upsert-by-normalized-key lookup is on the hot read path.
  * user_uploads (user_id, purpose)
      list-by-purpose endpoints (resume picker, JD picker).
  * interview_qa (record_id, order_idx)
      QAPanel renders qa list ordered by order_idx for one record.

Revision ID: 0014_hot_query_idxs
Revises: 0013_iv_rec_user_ct_idx
Create Date: 2026-05-14

(revision id kept ≤ 32 chars; alembic_version is VARCHAR(32).)
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "0014_hot_query_idxs"
down_revision: Union[str, None] = "0013_iv_rec_user_ct_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("ix_chat_sessions_user_type_arch", "chat_sessions",
        ["user_id", "session_type", "archived_at"]),
    ("ix_knowledge_docs_user_category", "knowledge_documents",
        ["user_id", "category"]),
    ("ix_memory_items_user_type_key", "memory_items",
        ["user_id", "type", "normalized_key"]),
    ("ix_user_uploads_user_purpose", "user_uploads",
        ["user_id", "purpose"]),
    ("ix_interview_qa_record_order", "interview_qa",
        ["record_id", "order_idx"]),
]


def _existing_indexes(table: str) -> set[str]:
    """Return the set of index names already on ``table``.

    Used to make ``upgrade()`` idempotent — if a previous half-failed run
    (or a hand-rolled CREATE INDEX) already laid one of these down, we
    skip it instead of crashing with DuplicateTable.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    try:
        return {ix["name"] for ix in inspector.get_indexes(table)}
    except Exception:
        # Table doesn't exist yet (shouldn't happen at this revision, but
        # be defensive — treat as "no indexes present").
        return set()


def upgrade() -> None:
    # Group by table so we only inspect each table once.
    by_table: dict[str, list[tuple[str, list[str]]]] = {}
    for name, table, cols in _INDEXES:
        by_table.setdefault(table, []).append((name, cols))

    for table, entries in by_table.items():
        present = _existing_indexes(table)
        for name, cols in entries:
            if name in present:
                # Already created by a prior run; nothing to do.
                continue
            op.create_index(name, table, cols, unique=False)


def downgrade() -> None:
    # Mirror upgrade()'s defensive style — skip if the index isn't there.
    by_table: dict[str, list[tuple[str, list[str]]]] = {}
    for name, table, cols in _INDEXES:
        by_table.setdefault(table, []).append((name, cols))

    for table, entries in by_table.items():
        present = _existing_indexes(table)
        for name, _cols in reversed(entries):
            if name not in present:
                continue
            op.drop_index(name, table_name=table)
