"""unified interview schema

Adds the InterviewQA and MockInterviewSession tables, extends interview_records
with snapshot/orchestration/grounding columns, and adds chat_sessions.archived_at
for soft-deletion of finished mock conversations.

This is the schema-only side of the unified mock+upload pipeline refactor; the
data migration that copies old interviews/transcripts/analysis_results into the
unified tables and drops them lives in 0008.

Revision ID: 0007_unified_interview_schema
Revises: 0006_chat_memory_cursor
Create Date: 2026-05-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007_unified_interview_schema"
down_revision: Union[str, None] = "0006_chat_memory_cursor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── interview_records: snapshots + orchestration + grounding ───────────
    with op.batch_alter_table("interview_records") as batch:
        batch.add_column(sa.Column("resume_doc_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("resume_text_snapshot", sa.Text(), nullable=True))
        batch.add_column(sa.Column("jd_text_snapshot", sa.Text(), nullable=True))
        batch.add_column(sa.Column("resume_structured_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("jd_structured_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("transcript_segments_json", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "analysis_schema_version",
                sa.Integer(),
                nullable=False,
                server_default="2",
            )
        )
        batch.add_column(
            sa.Column(
                "analyzed_qa_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(sa.Column("celery_task_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))

    # ── chat_sessions: soft-delete for finished/abandoned sessions ─────────
    op.add_column(
        "chat_sessions",
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )

    # ── interview_qa: first-class per-question rows ────────────────────────
    op.create_table(
        "interview_qa",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("order_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("phase", sa.String(), nullable=False, server_default="technical"),
        sa.Column("phase_label", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_summary", sa.String(), nullable=True),
        sa.Column("is_follow_up", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parent_qa_id", sa.String(), nullable=True),
        sa.Column("grounding_refs_json", sa.Text(), nullable=True),
        sa.Column("follow_up_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_segment_start", sa.Float(), nullable=True),
        sa.Column("source_segment_end", sa.Float(), nullable=True),
        sa.Column("question_audio_url", sa.String(), nullable=True),
        sa.Column("answer_audio_url", sa.String(), nullable=True),
        sa.Column("answer_input_mode", sa.String(), nullable=False, server_default="text"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("critique", sa.Text(), nullable=True),
        sa.Column("improved_answer", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"], ["interview_records.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["parent_qa_id"], ["interview_qa.id"]),
    )
    op.create_index("ix_interview_qa_record_id", "interview_qa", ["record_id"])
    op.create_index(
        "ix_interview_qa_record_order", "interview_qa", ["record_id", "order_idx"]
    )

    # ── mock_interview_sessions: transient in-progress state ───────────────
    op.create_table(
        "mock_interview_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("interview_record_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="in_progress"),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("current_question_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_buffer_json", sa.Text(), nullable=True),
        sa.Column("plan_snapshot_json", sa.Text(), nullable=True),
        sa.Column("interviewer_style", sa.String(), nullable=False, server_default="professional"),
        sa.Column("voice_mode", sa.String(), nullable=False, server_default="hybrid"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["interview_record_id"], ["interview_records.id"], ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_mock_interview_sessions_user_id", "mock_interview_sessions", ["user_id"]
    )
    op.create_index(
        "ix_mock_interview_sessions_status", "mock_interview_sessions", ["status"]
    )
    op.create_index(
        "ix_mock_interview_sessions_record_id",
        "mock_interview_sessions",
        ["interview_record_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_mock_interview_sessions_record_id", table_name="mock_interview_sessions")
    op.drop_index("ix_mock_interview_sessions_status", table_name="mock_interview_sessions")
    op.drop_index("ix_mock_interview_sessions_user_id", table_name="mock_interview_sessions")
    op.drop_table("mock_interview_sessions")

    op.drop_index("ix_interview_qa_record_order", table_name="interview_qa")
    op.drop_index("ix_interview_qa_record_id", table_name="interview_qa")
    op.drop_table("interview_qa")

    op.drop_column("chat_sessions", "archived_at")

    with op.batch_alter_table("interview_records") as batch:
        batch.drop_column("completed_at")
        batch.drop_column("error_message")
        batch.drop_column("celery_task_id")
        batch.drop_column("analyzed_qa_count")
        batch.drop_column("analysis_schema_version")
        batch.drop_column("transcript_segments_json")
        batch.drop_column("jd_structured_json")
        batch.drop_column("resume_structured_json")
        batch.drop_column("jd_text_snapshot")
        batch.drop_column("resume_text_snapshot")
        batch.drop_column("resume_doc_id")
