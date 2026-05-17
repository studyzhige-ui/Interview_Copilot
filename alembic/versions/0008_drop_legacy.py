"""migrate legacy Interview/Transcript/AnalysisResult into unified schema and drop them

Migrates surviving rows in the old three-table model
(interviews + transcripts + analysis_results) into the unified
interview_records + interview_qa schema introduced in 0007, then drops the
legacy tables.

In-place rules for legacy upload rows:
  - one (interview, transcript, analysis_result) triple → one interview_records
    row of source='upload' (if a matching row does not already exist) and
    interview_qa rows decoded from analysis_results.improved_answer (it stored
    a JSON-encoded per_question list).
  - status mapping: COMPLETED→completed, FAILED→failed, CANCELLED→failed,
    everything else→completed (legacy rows that reached this migration were
    completed by definition).

For existing interview_records rows whose analysis_json carries the v1
'qa_history' / 'per_question' shape inline, the per-question entries are split
out into interview_qa rows and the inline blobs are pruned to v2
(overall + phase_summary only).

Revision ID: 0008_drop_legacy_interview_tables
Revises: 0007_unified_interview_schema
Create Date: 2026-05-13
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_drop_legacy"
down_revision: Union[str, None] = "0007_unified_interview_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _new_record_id() -> str:
    return f"ir_{uuid.uuid4().hex[:12]}"


def _new_qa_id() -> str:
    return f"qa_{uuid.uuid4().hex[:12]}"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    now = datetime.utcnow()

    # ── 1. Legacy upload triples → InterviewRecord + InterviewQA ───────────
    if {"interviews", "transcripts", "analysis_results"}.issubset(existing_tables):
        legacy_rows = bind.execute(
            sa.text(
                "SELECT i.id, i.user_id, i.status, i.task_id, i.upload_id, "
                "       i.resume_upload_id, i.jd_text, i.created_at, "
                "       t.content AS transcript_text, "
                "       a.score, a.feedback, a.improved_answer "
                "FROM interviews i "
                "LEFT JOIN transcripts t ON t.interview_id = i.id "
                "LEFT JOIN analysis_results a ON a.interview_id = i.id"
            )
        ).mappings().all()

        for row in legacy_rows:
            legacy_id = row["id"]
            user_id = row["user_id"]
            if user_id is None:
                continue

            legacy_marker = f"legacy:interview:{legacy_id}"
            existing = bind.execute(
                sa.text("SELECT id FROM interview_records WHERE error_message = :m"),
                {"m": legacy_marker},
            ).first()
            if existing is not None:
                continue

            try:
                per_question = (
                    json.loads(row["improved_answer"]) if row["improved_answer"] else []
                )
                if not isinstance(per_question, list):
                    per_question = []
            except (TypeError, json.JSONDecodeError):
                per_question = []

            overall = {
                "score": float(row["score"]) if row["score"] is not None else None,
                "feedback": row["feedback"] or "",
                "strengths": [],
                "weaknesses": [],
                "improvement_plan": [],
            }
            analysis_json = json.dumps(
                {"schema_version": 2, "overall": overall, "phase_summary": {}, "meta": {}},
                ensure_ascii=False,
            )

            status_in = (row["status"] or "").upper()
            status_out = "completed" if status_in in {"COMPLETED", ""} else "failed"

            new_id = _new_record_id()
            bind.execute(
                sa.text(
                    "INSERT INTO interview_records "
                    "(id, user_id, source, title, audio_upload_id, resume_upload_id, "
                    " transcript, analysis_json, analysis_schema_version, "
                    " jd_text_snapshot, status, analyzed_qa_count, error_message, "
                    " celery_task_id, created_at, updated_at, completed_at) "
                    "VALUES "
                    "(:id, :user_id, 'upload', :title, :audio_upload_id, :resume_upload_id, "
                    " :transcript, :analysis_json, 2, :jd, :status, :qa_count, "
                    " :marker, :task_id, :created_at, :updated_at, :completed_at)"
                ),
                {
                    "id": new_id,
                    "user_id": user_id,
                    "title": f"面试录音 #{legacy_id}",
                    "audio_upload_id": row["upload_id"],
                    "resume_upload_id": row["resume_upload_id"],
                    "transcript": row["transcript_text"],
                    "analysis_json": analysis_json,
                    "jd": row["jd_text"],
                    "status": status_out,
                    "qa_count": len(per_question),
                    "marker": legacy_marker,
                    "task_id": row["task_id"],
                    "created_at": row["created_at"] or now,
                    "updated_at": now,
                    "completed_at": now if status_out == "completed" else None,
                },
            )

            for idx, pq in enumerate(per_question):
                if not isinstance(pq, dict):
                    continue
                bind.execute(
                    sa.text(
                        "INSERT INTO interview_qa "
                        "(id, record_id, order_idx, phase, question, answer, "
                        " question_summary, is_follow_up, follow_up_depth, "
                        " answer_input_mode, score, critique, improved_answer, "
                        " analyzed_at, created_at) "
                        "VALUES "
                        "(:id, :record_id, :order_idx, :phase, :q, :a, :qs, FALSE, 0, "
                        " 'text', :score, :critique, :improved, :analyzed_at, :created_at)"
                    ),
                    {
                        "id": _new_qa_id(),
                        "record_id": new_id,
                        "order_idx": idx,
                        "phase": str(pq.get("phase") or "technical"),
                        "q": str(pq.get("question") or ""),
                        "a": str(pq.get("answer") or pq.get("answer_summary") or ""),
                        "qs": str(pq.get("question_summary") or "")[:255] or None,
                        "score": int(pq["score"]) if isinstance(pq.get("score"), (int, float)) else None,
                        "critique": pq.get("critique") or pq.get("feedback") or None,
                        "improved": pq.get("improved_answer") or None,
                        "analyzed_at": now,
                        "created_at": now,
                    },
                )

    # ── 2. Migrate inline analysis_json (mock and old-style upload) → InterviewQA ──
    records = bind.execute(
        sa.text(
            "SELECT id, source, analysis_json FROM interview_records "
            "WHERE analysis_json IS NOT NULL AND analysis_json != ''"
        )
    ).mappings().all()

    for r in records:
        rec_id = r["id"]
        already = bind.execute(
            sa.text("SELECT COUNT(*) AS c FROM interview_qa WHERE record_id = :r"),
            {"r": rec_id},
        ).scalar()
        if already and already > 0:
            continue

        try:
            data = json.loads(r["analysis_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        items = data.get("per_question") or data.get("qa_history") or []
        if not isinstance(items, list) or not items:
            continue

        for idx, pq in enumerate(items):
            if not isinstance(pq, dict):
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO interview_qa "
                    "(id, record_id, order_idx, phase, question, answer, "
                    " question_summary, is_follow_up, follow_up_depth, "
                    " answer_input_mode, score, critique, improved_answer, "
                    " analyzed_at, created_at) "
                    "VALUES "
                    "(:id, :record_id, :order_idx, :phase, :q, :a, :qs, FALSE, 0, "
                    " 'text', :score, :critique, :improved, :analyzed_at, :created_at)"
                ),
                {
                    "id": _new_qa_id(),
                    "record_id": rec_id,
                    "order_idx": idx,
                    "phase": str(pq.get("phase") or pq.get("phase_id") or "technical"),
                    "q": str(pq.get("question") or ""),
                    "a": str(pq.get("answer") or pq.get("answer_summary") or ""),
                    "qs": str(pq.get("question_summary") or "")[:255] or None,
                    "score": int(pq["score"]) if isinstance(pq.get("score"), (int, float)) else None,
                    "critique": pq.get("critique") or pq.get("feedback") or None,
                    "improved": pq.get("improved_answer") or None,
                    "analyzed_at": now,
                    "created_at": now,
                },
            )

        pruned = {
            "schema_version": 2,
            "overall": data.get("overall")
            or {
                "score": data.get("overall_score"),
                "feedback": data.get("overall_feedback", ""),
                "strengths": data.get("strengths", []),
                "weaknesses": data.get("weaknesses", []),
                "improvement_plan": data.get("improvement_suggestions", []),
            },
            "phase_summary": data.get("phase_summary", {}),
            "meta": data.get("meta", {}),
        }
        bind.execute(
            sa.text(
                "UPDATE interview_records SET analysis_json = :a, analyzed_qa_count = :n "
                "WHERE id = :r"
            ),
            {
                "a": json.dumps(pruned, ensure_ascii=False),
                "n": len(items),
                "r": rec_id,
            },
        )

    # ── 3. Drop legacy tables ──────────────────────────────────────────────
    if "analysis_results" in existing_tables:
        op.drop_table("analysis_results")
    if "transcripts" in existing_tables:
        op.drop_table("transcripts")
    if "interviews" in existing_tables:
        op.drop_table("interviews")


def downgrade() -> None:
    # Data migration is lossy; recreate empty legacy tables only.
    op.create_table(
        "interviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("upload_id", sa.String(), nullable=True),
        sa.Column("resume_upload_id", sa.String(), nullable=True),
        sa.Column("jd_text", sa.Text(), nullable=True),
        sa.Column("file_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "transcripts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
    )
    op.create_table(
        "analysis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("interview_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("improved_answer", sa.Text(), nullable=True),
    )
