"""Add ON DELETE CASCADE to interview_records child FKs.

Two child tables of ``interview_records`` declared
``ondelete="CASCADE"`` on their FK in the ORM since day one — see
``app/models/interview_qa.py:35`` and
``app/models/mock_interview_session.py:32``. But the 0001 baseline
created the FKs without the cascade clause:

    sa.ForeignKey("interview_records.id")  # ← no ondelete

Postgres only honours the schema, not the ORM declaration. So the
delete endpoint at ``app/api/interview.py:625-634`` — whose comment
on line 632 says **"interview_qa + mock_interview_sessions auto-
cleaned by their ON DELETE CASCADE on interview_records"** —
silently relied on a cascade that didn't exist in the DB. The
endpoint ran for a long time without tripping because most users
never delete interview records, but the first time someone did,
``db.delete(record)`` would have raised IntegrityError or left
orphan child rows.

This migration drops the FKs by their auto-generated name and
recreates them with ``ondelete="CASCADE"`` so the schema matches the
ORM contract and the delete endpoint's documented behaviour.

Postgres only. Constraint names follow Postgres's default of
``<tablename>_<columnname>_fkey``. SQLite isn't an alembic target
here (the model-side fixtures use ``Base.metadata.create_all`` which
picks up the cascade directly from the ORM, sidestepping this whole
class of drift).

Revision ID: 0009_add_record_cascade
Revises: 0008_drop_agent_trace
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0009_add_record_cascade"
down_revision: Union[str, None] = "0008_drop_agent_trace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── interview_qa.record_id → interview_records.id ───────────────────
    op.drop_constraint(
        "interview_qa_record_id_fkey",
        "interview_qa",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "interview_qa_record_id_fkey",
        source_table="interview_qa",
        referent_table="interview_records",
        local_cols=["record_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )

    # ── mock_interview_sessions.interview_record_id → interview_records.id
    op.drop_constraint(
        "mock_interview_sessions_interview_record_id_fkey",
        "mock_interview_sessions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "mock_interview_sessions_interview_record_id_fkey",
        source_table="mock_interview_sessions",
        referent_table="interview_records",
        local_cols=["interview_record_id"],
        remote_cols=["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Restore the no-cascade shape that 0001 produced. Note that this
    # reintroduces the silent IntegrityError landmine — only run this
    # if you also revert app/api/interview.py:625-634's reliance on
    # the cascade.
    op.drop_constraint(
        "mock_interview_sessions_interview_record_id_fkey",
        "mock_interview_sessions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "mock_interview_sessions_interview_record_id_fkey",
        source_table="mock_interview_sessions",
        referent_table="interview_records",
        local_cols=["interview_record_id"],
        remote_cols=["id"],
    )

    op.drop_constraint(
        "interview_qa_record_id_fkey",
        "interview_qa",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "interview_qa_record_id_fkey",
        source_table="interview_qa",
        referent_table="interview_records",
        local_cols=["record_id"],
        remote_cols=["id"],
    )
