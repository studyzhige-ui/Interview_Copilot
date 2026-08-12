"""Make every live mock runtime a complete, typed cursor.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-11
"""

import json
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT interview_record_id, conversation_id, plan_json, "
                "current_stage_key, current_question_message_id "
                "FROM mock_interview_runtime"
            )
        )
        .mappings()
        .all()
    )

    invalid_record_ids: list[str] = []
    for row in rows:
        try:
            plan = json.loads(row["plan_json"])
        except (json.JSONDecodeError, TypeError):
            invalid_record_ids.append(row["interview_record_id"])
            continue

        # Convert the one retired wrapper shape during migration; application
        # code reads and writes only the stage list after this revision.
        if isinstance(plan, dict):
            plan = plan.get("stages")
        if not isinstance(plan, list) or not plan:
            invalid_record_ids.append(row["interview_record_id"])
            continue
        stage_keys = [
            str(stage["key"])
            for stage in plan
            if isinstance(stage, dict) and stage.get("key")
        ]
        if len(stage_keys) != len(plan):
            invalid_record_ids.append(row["interview_record_id"])
            continue

        current_stage_key = row["current_stage_key"]
        if current_stage_key not in stage_keys:
            current_stage_key = stage_keys[0]

        question_message_id = row["current_question_message_id"]
        if question_message_id is None:
            question_message_id = bind.execute(
                sa.text(
                    "SELECT id FROM conversation_messages "
                    "WHERE conversation_id = :conversation_id "
                    "AND role = 'assistant' ORDER BY seq DESC, id DESC LIMIT 1"
                ),
                {"conversation_id": row["conversation_id"]},
            ).scalar()
        if question_message_id is None:
            invalid_record_ids.append(row["interview_record_id"])
            continue

        bind.execute(
            sa.text(
                "UPDATE mock_interview_runtime SET plan_json = :plan_json, "
                "current_stage_key = :current_stage_key, "
                "current_question_message_id = :current_question_message_id "
                "WHERE interview_record_id = :interview_record_id"
            ),
            {
                "plan_json": json.dumps(plan, ensure_ascii=False),
                "current_stage_key": current_stage_key,
                "current_question_message_id": question_message_id,
                "interview_record_id": row["interview_record_id"],
            },
        )

    for record_id in invalid_record_ids:
        bind.execute(
            sa.text(
                "DELETE FROM mock_interview_runtime "
                "WHERE interview_record_id = :interview_record_id"
            ),
            {"interview_record_id": record_id},
        )

    op.alter_column(
        "mock_interview_runtime",
        "plan_json",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
        postgresql_using="plan_json::jsonb",
    )
    op.alter_column("mock_interview_runtime", "current_stage_key", nullable=False)
    op.alter_column(
        "mock_interview_runtime",
        "current_question_message_id",
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mock_interview_runtime",
        "current_question_message_id",
        nullable=True,
    )
    op.alter_column("mock_interview_runtime", "current_stage_key", nullable=True)
    op.alter_column(
        "mock_interview_runtime",
        "plan_json",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        nullable=True,
        postgresql_using="plan_json::text",
    )
