"""CRUD and business logic for InterviewRecord + InterviewQA.

An InterviewRecord is the unified data home for a finished interview, whether
it came from a real audio upload (source='upload') or an AI mock interview
(source='mock'). Per-question rows live in InterviewQA, addressed by the
record's id.

The analysis orchestrator (see services/interview/analysis_orchestrator.py)
drives state transitions; this module is just persistence helpers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.interview_qa import InterviewQA, _generate_qa_id
from app.models.interview_record import InterviewRecord, _generate_record_id

logger = logging.getLogger(__name__)


# Canonical status values for InterviewRecord.status
STATUS_PENDING = "pending"
STATUS_TRANSCRIBING = "transcribing"
STATUS_EXTRACTING = "extracting"
STATUS_ANALYZING = "analyzing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


class InterviewRecordService:
    # ── Create ────────────────────────────────────────────────────────

    def create_for_upload(
        self,
        *,
        user_id: str,
        title: str = "",
        audio_upload_id: str | None = None,
        resume_upload_id: str | None = None,
        resume_doc_id: str | None = None,
        jd_upload_id: str | None = None,
        resume_text_snapshot: str = "",
        jd_text_snapshot: str = "",
        db: Session | None = None,
    ) -> InterviewRecord:
        return self._create(
            user_id=user_id,
            source="upload",
            title=title or "面试录音复盘",
            audio_upload_id=audio_upload_id,
            resume_upload_id=resume_upload_id,
            resume_doc_id=resume_doc_id,
            jd_upload_id=jd_upload_id,
            resume_text_snapshot=resume_text_snapshot,
            jd_text_snapshot=jd_text_snapshot,
            status=STATUS_PENDING,
            db=db,
        )

    def create_for_mock(
        self,
        *,
        user_id: str,
        title: str = "",
        resume_upload_id: str | None = None,
        resume_doc_id: str | None = None,
        jd_upload_id: str | None = None,
        resume_text_snapshot: str = "",
        jd_text_snapshot: str = "",
        interview_plan: str = "",
        db: Session | None = None,
    ) -> InterviewRecord:
        return self._create(
            user_id=user_id,
            source="mock",
            title=title or "模拟面试",
            resume_upload_id=resume_upload_id,
            resume_doc_id=resume_doc_id,
            jd_upload_id=jd_upload_id,
            resume_text_snapshot=resume_text_snapshot,
            jd_text_snapshot=jd_text_snapshot,
            interview_plan=interview_plan,
            status=STATUS_PENDING,
            db=db,
        )

    # ── Read ──────────────────────────────────────────────────────────

    def get(self, record_id: str, user_id: str | None = None) -> InterviewRecord | None:
        db: Session = SessionLocal()
        try:
            query = db.query(InterviewRecord).filter(InterviewRecord.id == record_id)
            if user_id:
                query = query.filter(InterviewRecord.user_id == resolve_user_pk(db, user_id))
            return query.first()
        finally:
            db.close()

    def list_by_user(
        self,
        user_id: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[InterviewRecord]:
        db: Session = SessionLocal()
        try:
            return (
                db.query(InterviewRecord)
                .filter(InterviewRecord.user_id == resolve_user_pk(db, user_id))
                .order_by(InterviewRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        finally:
            db.close()

    def list_qa(self, record_id: str, db: Session | None = None) -> list[InterviewQA]:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            return (
                db.query(InterviewQA)
                .filter(InterviewQA.record_id == record_id)
                .order_by(InterviewQA.order_idx)
                .all()
            )
        finally:
            if own_db:
                db.close()

    # ── Update / state transitions ────────────────────────────────────

    def set_status(
        self,
        record_id: str,
        status: str,
        *,
        error_message: str | None = None,
        celery_task_id: str | None = None,
        db: Session | None = None,
    ) -> None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return
            row.status = status
            if error_message is not None:
                row.error_message = error_message
            if celery_task_id is not None:
                row.celery_task_id = celery_task_id
            if status == STATUS_COMPLETED:
                row.completed_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    def set_transcript(
        self,
        record_id: str,
        *,
        transcript: str,
        segments_json: str | None = None,
        db: Session | None = None,
    ) -> None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return
            row.transcript = transcript
            if segments_json is not None:
                row.transcript_segments_json = segments_json
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    def set_analysis(
        self,
        record_id: str,
        analysis: dict[str, Any] | str,
        *,
        db: Session | None = None,
    ) -> None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return
            row.analysis_json = (
                analysis if isinstance(analysis, str) else json.dumps(analysis, ensure_ascii=False)
            )
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    # ── InterviewQA writes ────────────────────────────────────────────

    def bulk_insert_qa(
        self,
        record_id: str,
        qa_inputs: Iterable[dict[str, Any]],
        *,
        db: Session | None = None,
    ) -> list[InterviewQA]:
        """Insert per-question rows for a record. Each input dict supports:
        question, answer, phase, phase_label, question_summary,
        is_follow_up, parent_qa_id, grounding_refs, follow_up_depth,
        source_segment_start, source_segment_end, answer_input_mode,
        action, topic, answer_quality (Runtime Director metadata).
        """
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            inserted: list[InterviewQA] = []
            existing_count = (
                db.query(InterviewQA)
                .filter(InterviewQA.record_id == record_id)
                .count()
            )
            for offset, payload in enumerate(qa_inputs):
                refs = payload.get("grounding_refs")
                aq = payload.get("answer_quality")
                row = InterviewQA(
                    id=_generate_qa_id(),
                    record_id=record_id,
                    order_idx=existing_count + offset,
                    phase=str(payload.get("phase") or "technical"),
                    phase_label=payload.get("phase_label"),
                    question=str(payload.get("question") or ""),
                    answer=str(payload.get("answer") or ""),
                    question_summary=payload.get("question_summary"),
                    is_follow_up=bool(payload.get("is_follow_up", False)),
                    parent_qa_id=payload.get("parent_qa_id"),
                    grounding_refs_json=(
                        json.dumps(refs, ensure_ascii=False) if refs else None
                    ),
                    follow_up_depth=int(payload.get("follow_up_depth") or 0),
                    source_segment_start=payload.get("source_segment_start"),
                    source_segment_end=payload.get("source_segment_end"),
                    answer_input_mode=str(payload.get("answer_input_mode") or "text"),
                    # Runtime Director metadata (mock-source only; upload leaves null)
                    action=payload.get("action"),
                    topic=payload.get("topic"),
                    answer_quality_json=aq if isinstance(aq, dict) else None,
                )
                db.add(row)
                inserted.append(row)
            if own_db:
                db.commit()
                for row in inserted:
                    db.refresh(row)
            else:
                db.flush()
            return inserted
        finally:
            if own_db:
                db.close()

    def update_qa_analysis(
        self,
        qa_id: str,
        *,
        score: int | None,
        critique: str | None,
        improved_answer: str | None,
        key_points: list[str] | None = None,
        db: Session | None = None,
    ) -> None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewQA).filter(InterviewQA.id == qa_id).first()
            if row is None:
                return
            if score is not None:
                row.score = score
            if critique is not None:
                row.critique = critique
            if improved_answer is not None:
                row.improved_answer = improved_answer
            if key_points is not None:
                row.key_points_json = json.dumps(key_points, ensure_ascii=False)
            row.analyzed_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    def increment_analyzed_count(self, record_id: str, by: int = 1, *, db: Session | None = None) -> None:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return
            row.analyzed_qa_count = (row.analyzed_qa_count or 0) + by
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    # ── Reference helper for debrief context assembly ─────────────────

    def get_analysis_summary(self, record_id: str, user_id: str) -> str:
        """Short reference for slot 2 of context assembly."""
        record = self.get(record_id, user_id)
        if record is None:
            return ""

        overall: dict[str, Any] = {}
        if record.analysis_json:
            try:
                report = json.loads(record.analysis_json)
                overall = report.get("overall") or {}
            except json.JSONDecodeError:
                pass

        qa_rows = self.list_qa(record_id)
        lines = [
            f"综合评分: {overall.get('score', 'N/A')}",
            f"总体评价: {overall.get('summary') or overall.get('feedback') or ''}",
            "",
            "题目列表:",
        ]
        for i, qa in enumerate(qa_rows, 1):
            q = (qa.question or "")[:60]
            score = qa.score if qa.score is not None else "?"
            lines.append(f"  Q{i}: {q}... (评分:{score})")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────

    def _create(
        self,
        *,
        user_id: str,
        source: str,
        title: str,
        audio_upload_id: str | None = None,
        resume_upload_id: str | None = None,
        resume_doc_id: str | None = None,
        jd_upload_id: str | None = None,
        resume_text_snapshot: str = "",
        jd_text_snapshot: str = "",
        interview_plan: str = "",
        status: str = STATUS_PENDING,
        db: Session | None = None,
    ) -> InterviewRecord:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            record = InterviewRecord(
                id=_generate_record_id(),
                user_id=resolve_user_pk(db, user_id),
                source=source,
                title=title,
                audio_upload_id=audio_upload_id,
                resume_upload_id=resume_upload_id,
                resume_doc_id=resume_doc_id,
                jd_upload_id=jd_upload_id,
                resume_text_snapshot=resume_text_snapshot or None,
                jd_text_snapshot=jd_text_snapshot or None,
                interview_plan=interview_plan or None,
                status=status,
                analyzed_qa_count=0,
                analysis_schema_version=2,
            )
            db.add(record)
            if own_db:
                db.commit()
                db.refresh(record)
            else:
                db.flush()
            return record
        except Exception:
            if own_db:
                db.rollback()
            raise
        finally:
            if own_db:
                db.close()


interview_record_service = InterviewRecordService()
