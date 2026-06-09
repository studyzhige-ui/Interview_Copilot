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
from app.models.interview_transcript import InterviewTranscript, _generate_transcript_id

logger = logging.getLogger(__name__)


# Canonical status values for InterviewRecord.status.
# Upload pipeline: pending → transcribing → extracting → analyzing → completed
#                  (or failed).
# Mock pipeline:   mock_in_progress → processing_review → review_ready
#                  (or review_failed). A mock only enters the review list once
#                  it reaches review_ready.
STATUS_PENDING = "pending"
STATUS_TRANSCRIBING = "transcribing"
STATUS_EXTRACTING = "extracting"
STATUS_ANALYZING = "analyzing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_MOCK_IN_PROGRESS = "mock_in_progress"
STATUS_PROCESSING_REVIEW = "processing_review"
STATUS_REVIEW_READY = "review_ready"
STATUS_REVIEW_FAILED = "review_failed"

# Mock states that must NOT appear in the review list (not yet viewable).
MOCK_HIDDEN_STATUSES = (STATUS_MOCK_IN_PROGRESS, STATUS_PROCESSING_REVIEW)


class InterviewRecordService:
    # ── Create ────────────────────────────────────────────────────────

    def create_for_upload(
        self,
        *,
        user_id: str,
        title: str = "",
        audio_file_asset_id: str | None = None,
        resume_id: str | None = None,
        resume_file_asset_id: str | None = None,
        resume_source: str | None = None,
        resume_title_snapshot: str | None = None,
        jd_file_asset_id: str | None = None,
        resume_text_snapshot: str = "",
        jd_text_snapshot: str = "",
        db: Session | None = None,
    ) -> InterviewRecord:
        return self._create(
            user_id=user_id,
            source="upload",
            title=title or "面试录音复盘",
            audio_file_asset_id=audio_file_asset_id,
            resume_id=resume_id,
            resume_file_asset_id=resume_file_asset_id,
            resume_source=resume_source,
            resume_title_snapshot=resume_title_snapshot,
            jd_file_asset_id=jd_file_asset_id,
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
        resume_id: str | None = None,
        resume_file_asset_id: str | None = None,
        resume_source: str | None = None,
        resume_title_snapshot: str | None = None,
        jd_file_asset_id: str | None = None,
        resume_text_snapshot: str = "",
        jd_text_snapshot: str = "",
        interview_plan: str = "",
        status: str = STATUS_PENDING,
        db: Session | None = None,
    ) -> InterviewRecord:
        return self._create(
            user_id=user_id,
            source="mock",
            title=title or "模拟面试",
            resume_id=resume_id,
            resume_file_asset_id=resume_file_asset_id,
            resume_source=resume_source,
            resume_title_snapshot=resume_title_snapshot,
            jd_file_asset_id=jd_file_asset_id,
            resume_text_snapshot=resume_text_snapshot,
            jd_text_snapshot=jd_text_snapshot,
            interview_plan=interview_plan,
            status=status,
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
        """Records for the review list. Mock interviews that haven't reached
        review_ready (i.e. mock_in_progress / processing_review) are hidden —
        an unfinished or still-reviewing mock never appears in the list (a
        review_failed mock DOES appear so the user can retry)."""
        db: Session = SessionLocal()
        try:
            return (
                db.query(InterviewRecord)
                .filter(
                    InterviewRecord.user_id == resolve_user_pk(db, user_id),
                    ~InterviewRecord.status.in_(MOCK_HIDDEN_STATUSES),
                )
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
            if status in (STATUS_COMPLETED, STATUS_REVIEW_READY):
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
        provider: str | None = None,
        language: str | None = None,
        db: Session | None = None,
    ) -> None:
        """Upsert the record's transcript into ``interview_transcripts`` and point
        ``interview_records.transcript_id`` at it (one transcript per record, v1)."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return
            tr = None
            if row.transcript_id:
                tr = (
                    db.query(InterviewTranscript)
                    .filter(InterviewTranscript.id == row.transcript_id)
                    .first()
                )
            if tr is None:
                tr = InterviewTranscript(
                    id=_generate_transcript_id(),
                    record_id=record_id,
                    user_id=row.user_id,
                )
                db.add(tr)
            tr.text = transcript
            if segments_json is not None:
                tr.segments_json = segments_json
            if provider is not None:
                tr.provider = provider
            if language is not None:
                tr.language = language
            tr.status = "ready"
            tr.updated_at = datetime.utcnow()
            db.flush()  # persist the transcript row before pointing the record at it
            row.transcript_id = tr.id
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
        finally:
            if own_db:
                db.close()

    def get_transcript_text(self, record_id: str, db: Session | None = None) -> str:
        """Return the record's current transcript full text ("" if none)."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None or not row.transcript_id:
                return ""
            tr = (
                db.query(InterviewTranscript)
                .filter(InterviewTranscript.id == row.transcript_id)
                .first()
            )
            return tr.text if tr and tr.text else ""
        finally:
            if own_db:
                db.close()

    def get_transcript_payload(self, record_id: str) -> dict[str, Any]:
        """Return ``{text, segments_json}`` for the record's current transcript
        (both ``None`` when there is no transcript)."""
        db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None or not row.transcript_id:
                return {"text": None, "segments_json": None}
            tr = (
                db.query(InterviewTranscript)
                .filter(InterviewTranscript.id == row.transcript_id)
                .first()
            )
            if tr is None:
                return {"text": None, "segments_json": None}
            return {"text": tr.text, "segments_json": tr.segments_json}
        finally:
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
        action, topic, answer_quality (optional per-QA classification metadata).
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
                    # Optional per-QA classification metadata (usually null).
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
        audio_file_asset_id: str | None = None,
        resume_id: str | None = None,
        resume_file_asset_id: str | None = None,
        resume_source: str | None = None,
        resume_title_snapshot: str | None = None,
        jd_file_asset_id: str | None = None,
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
                audio_file_asset_id=audio_file_asset_id,
                resume_id=resume_id,
                resume_file_asset_id=resume_file_asset_id,
                resume_source=resume_source or ("none" if source == "upload" else None),
                resume_title_snapshot=resume_title_snapshot,
                jd_file_asset_id=jd_file_asset_id,
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
