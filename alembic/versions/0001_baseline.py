"""baseline schema — squash of historical migrations 0001 through 0019

After 19 incremental migrations (several of which experimented with shapes
that were later reverted — chat_conversations, conversation_id, etc.),
this file replaces the entire chain with a single CREATE TABLE pass that
matches the final SQLAlchemy models. Anyone setting up a fresh DB now
runs exactly one migration to reach head.

The original 0001–0019 history is in git if you need to read it. This
migration is not reversible — ``downgrade`` drops every table, which is
fine for a one-way baseline but doesn't restore prior intermediate
states. If you ever need an "undo" path, create a follow-up migration
that targets specific schema changes rather than trying to walk this
one backwards.

Revision ID: 0001_baseline
Revises: None
Create Date: 2026-05-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ─────────────────────────────────────────────────────────
    # Auth + profile + per-user preferences. ``user_profile_doc`` is the
    # single-document storage for LLM-curated user facts (replaces the
    # legacy multi-row user_profile rows in memory_items — see model
    # docstring for the rationale).
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("nickname", sa.String(length=64), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("memory_recall_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_profile_doc", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── interview_records ─────────────────────────────────────────────
    # The "folder" that everything else hangs off. One row per uploaded
    # audio (source='upload') or AI-driven session (source='mock').
    # ``debrief_summary`` is the cache-friendly LLM-generated paragraph
    # injected into every debrief chat's record_context prompt slot.
    op.create_table(
        "interview_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True, server_default="未命名面试"),
        sa.Column("tag", sa.String(length=32), nullable=True),
        sa.Column("audio_upload_id", sa.String(), nullable=True),
        sa.Column("resume_upload_id", sa.String(), nullable=True),
        sa.Column("resume_doc_id", sa.String(), nullable=True),
        sa.Column("jd_upload_id", sa.String(), nullable=True),
        sa.Column("resume_text_snapshot", sa.Text(), nullable=True),
        sa.Column("jd_text_snapshot", sa.Text(), nullable=True),
        sa.Column("resume_structured_json", sa.Text(), nullable=True),
        sa.Column("jd_structured_json", sa.Text(), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_segments_json", sa.Text(), nullable=True),
        sa.Column("interview_plan", sa.Text(), nullable=True),
        sa.Column("analysis_json", sa.Text(), nullable=True),
        sa.Column("analysis_schema_version", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("debrief_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("analyzed_qa_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_task_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_interview_records_id", "interview_records", ["id"])
    op.create_index("ix_interview_records_user_id", "interview_records", ["user_id"])
    op.create_index("ix_interview_records_status", "interview_records", ["status"])
    # Composite — matches the list-by-user-by-recency ORDER BY pattern.
    op.create_index(
        "ix_interview_records_user_created",
        "interview_records",
        ["user_id", "created_at"],
    )

    # ── user_uploads ──────────────────────────────────────────────────
    # The single canonical table for ALL user-uploaded blobs (audio,
    # resumes, JDs, attachments). object_key is unique so two users
    # can't accidentally collide on S3.
    op.create_table(
        "user_uploads",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending_upload"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_uploads_id", "user_uploads", ["id"])
    op.create_index("ix_user_uploads_user_id", "user_uploads", ["user_id"])
    op.create_index("ix_user_uploads_object_key", "user_uploads", ["object_key"], unique=True)
    op.create_index("ix_user_uploads_purpose", "user_uploads", ["purpose"])
    op.create_index("ix_user_uploads_status", "user_uploads", ["status"])
    # Composite — list-by-user filtered by purpose (resume picker / JD picker).
    op.create_index(
        "ix_user_uploads_user_purpose",
        "user_uploads",
        ["user_id", "purpose"],
    )

    # ── mock_interview_sessions ───────────────────────────────────────
    # Drives the AI-led mock interview. interview_record_id binds it
    # to the parent record (source='mock') so QA + analysis live in
    # the unified interview_records / interview_qa tables.
    op.create_table(
        "mock_interview_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "interview_record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="in_progress"),
        sa.Column("current_phase", sa.String(), nullable=True),
        sa.Column("current_question_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_buffer_json", sa.Text(), nullable=True),
        sa.Column("plan_snapshot_json", sa.Text(), nullable=True),
        sa.Column("interviewer_style", sa.String(), nullable=False, server_default="professional"),
        sa.Column("voice_mode", sa.String(), nullable=False, server_default="hybrid"),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mock_interview_sessions_user_id", "mock_interview_sessions", ["user_id"])
    op.create_index("ix_mock_interview_sessions_status", "mock_interview_sessions", ["status"])
    op.create_index(
        "ix_mock_interview_sessions_interview_record_id",
        "mock_interview_sessions",
        ["interview_record_id"],
    )

    # ── chat_sessions ─────────────────────────────────────────────────
    # One chat thread (debrief / general / mock_interview). interview_id
    # is the link to its parent record (NULL for general chats). Each
    # session has its own session_state JSON (compaction summary +
    # mode-specific fields) and per-session counters for the post-turn
    # maintenance pipeline.
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True, server_default="新的面试对话"),
        sa.Column("summary", sa.Text(), nullable=True, server_default=""),
        sa.Column("session_type", sa.String(), nullable=False, server_default="general"),
        sa.Column(
            "interview_id",
            sa.String(),
            sa.ForeignKey("interview_records.id"),
            nullable=True,
        ),
        sa.Column("session_state", sa.Text(), nullable=True),
        sa.Column("compaction_cursor", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("memory_extraction_cursor", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("turn_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_sessions_id", "chat_sessions", ["id"])
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_session_type", "chat_sessions", ["session_type"])
    op.create_index("ix_chat_sessions_interview_id", "chat_sessions", ["interview_id"])
    # Composite — list-by-user-by-type filter on the sessions panel.
    op.create_index(
        "ix_chat_sessions_user_type_arch",
        "chat_sessions",
        ["user_id", "session_type", "archived_at"],
    )

    # ── chat_messages ─────────────────────────────────────────────────
    # Per-message rows. ``seq`` is monotonic per session so /chat/history
    # paginates cheaply by descending seq. (session_id, seq) is the hot
    # composite for the SSE-stream tail query.
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(),
            sa.ForeignKey("chat_sessions.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_chat_messages_id", "chat_messages", ["id"])
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_seq", "chat_messages", ["seq"])
    op.create_index(
        "ix_chat_messages_session_seq",
        "chat_messages",
        ["session_id", "seq"],
    )

    # ── interview_qa ──────────────────────────────────────────────────
    # Per-question record. ``parent_qa_id`` is a self-FK so follow-up
    # questions can link to the originating Q. ``answer_quality_json``
    # is structured per-question analysis output.
    op.create_table(
        "interview_qa",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "record_id",
            sa.String(),
            sa.ForeignKey("interview_records.id"),
            nullable=False,
        ),
        sa.Column("order_idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("phase", sa.String(), nullable=False, server_default="technical"),
        sa.Column("phase_label", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("question_summary", sa.String(), nullable=True),
        sa.Column("is_follow_up", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "parent_qa_id",
            sa.String(),
            sa.ForeignKey("interview_qa.id"),
            nullable=True,
        ),
        sa.Column("grounding_refs_json", sa.Text(), nullable=True),
        sa.Column("follow_up_depth", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_segment_start", sa.Float(), nullable=True),
        sa.Column("source_segment_end", sa.Float(), nullable=True),
        sa.Column("question_audio_url", sa.String(), nullable=True),
        sa.Column("answer_audio_url", sa.String(), nullable=True),
        sa.Column("answer_input_mode", sa.String(), nullable=False, server_default="text"),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("topic", sa.String(length=80), nullable=True),
        sa.Column("answer_quality_json", sa.JSON(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("critique", sa.Text(), nullable=True),
        sa.Column("improved_answer", sa.Text(), nullable=True),
        sa.Column("key_points_json", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_interview_qa_record_id", "interview_qa", ["record_id"])
    # Composite — QAPanel renders qa list ordered by order_idx for one record.
    op.create_index(
        "ix_interview_qa_record_order",
        "interview_qa",
        ["record_id", "order_idx"],
    )

    # ── knowledge_documents ───────────────────────────────────────────
    # User-uploaded reference material that goes through RAG ingestion.
    # node_ids / ref_doc_ids are JSON-encoded arrays of Milvus / docstore
    # pointers, used for cascade delete from the vector store.
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column(
            "upload_id",
            sa.String(),
            sa.ForeignKey("user_uploads.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False, server_default="默认"),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="processing"),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("ref_doc_ids", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_documents_id", "knowledge_documents", ["id"])
    op.create_index("ix_knowledge_documents_user_id", "knowledge_documents", ["user_id"])
    op.create_index("ix_knowledge_documents_upload_id", "knowledge_documents", ["upload_id"])
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"])
    op.create_index("ix_knowledge_documents_object_key", "knowledge_documents", ["object_key"])
    op.create_index("ix_knowledge_documents_source_type", "knowledge_documents", ["source_type"])
    op.create_index("ix_knowledge_documents_category", "knowledge_documents", ["category"])
    op.create_index(
        "ix_knowledge_docs_user_category",
        "knowledge_documents",
        ["user_id", "category"],
    )

    # ── memory_items ──────────────────────────────────────────────────
    # interview_fact rows (the multi-row branch). user_profile rows are
    # gone — that data now lives in ``users.user_profile_doc``.
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False, server_default="user"),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("normalized_key", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True, server_default="0.0"),
        sa.Column("importance", sa.Float(), nullable=True, server_default="0.5"),
        sa.Column("source_session_id", sa.String(), nullable=True),
        sa.Column("last_evidence_seq", sa.Integer(), nullable=True),
        sa.Column("recall_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("embedding_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
    )
    op.create_index("ix_memory_items_id", "memory_items", ["id"])
    op.create_index("ix_memory_items_user_id", "memory_items", ["user_id"])
    op.create_index("ix_memory_items_type", "memory_items", ["type"])
    op.create_index("ix_memory_items_scope", "memory_items", ["scope"])
    op.create_index("ix_memory_items_normalized_key", "memory_items", ["normalized_key"])
    # Composite — upsert-by-(user, type, normalized_key) is the hot read.
    op.create_index(
        "ix_memory_items_user_type_key",
        "memory_items",
        ["user_id", "type", "normalized_key"],
    )

    # ── resume_sections ───────────────────────────────────────────────
    # Structured chunks parsed out of a resume upload. embedding_status
    # tracks Milvus sync.
    op.create_table(
        "resume_sections",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("upload_id", sa.String(), nullable=False),
        sa.Column("section_type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("embedding_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_resume_sections_id", "resume_sections", ["id"])
    op.create_index("ix_resume_sections_user_id", "resume_sections", ["user_id"])
    op.create_index("ix_resume_sections_upload_id", "resume_sections", ["upload_id"])
    op.create_index("ix_resume_sections_section_type", "resume_sections", ["section_type"])

    # ── user_api_keys ─────────────────────────────────────────────────
    # Per-(user, provider) encrypted API key. key_ciphertext is Fernet
    # output; key_masked is a sanitized display string (last 4 chars).
    op.create_table(
        "user_api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("key_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_masked", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_user_api_keys_user_id", "user_api_keys", ["user_id"])

    # ── agent_runs ────────────────────────────────────────────────────
    # One row per L2 agent invocation (the agentic chain). Status +
    # token usage roll up here; per-step detail in agent_steps.
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="function_calling"),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("budget_stop_reason", sa.String(), nullable=True),
        sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.create_index("ix_agent_runs_id", "agent_runs", ["id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])

    # ── agent_steps ───────────────────────────────────────────────────
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("agent_runs.id"),
            nullable=False,
        ),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("tool_name", sa.String(), nullable=True),
        sa.Column("tool_call_id", sa.String(), nullable=True),
        sa.Column("tool_args_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("observation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("assistant_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_steps_id", "agent_steps", ["id"])
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])


def downgrade() -> None:
    # Order matters: drop tables with FK dependencies BEFORE the tables
    # they reference. (DROP TABLE in Postgres complains if any FK still
    # points at it from another live table.)
    op.drop_table("agent_steps")
    op.drop_table("agent_runs")
    op.drop_table("user_api_keys")
    op.drop_table("resume_sections")
    op.drop_table("memory_items")
    op.drop_table("knowledge_documents")
    op.drop_table("interview_qa")
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("mock_interview_sessions")
    op.drop_table("user_uploads")
    op.drop_table("interview_records")
    op.drop_table("users")
