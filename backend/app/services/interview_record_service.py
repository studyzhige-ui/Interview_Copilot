"""CRUD and business logic for InterviewRecord.

An InterviewRecord is created when:
  1. A user uploads an audio file and analysis completes (source="upload")
  2. A mock interview finishes and results are persisted (source="mock")

The record unifies transcript + analysis_json so that a debrief ChatSession
can reference it via ChatSession.interview_id.
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.interview_record import InterviewRecord, _generate_record_id

logger = logging.getLogger(__name__)


class InterviewRecordService:
    # ── Create ────────────────────────────────────────────────────────

    def create_from_upload(
        self,
        *,
        user_id: str,
        title: str = "",
        audio_upload_id: str | None = None,
        resume_upload_id: str | None = None,
        transcript: str = "",
        analysis_json: str = "",
        db: Session | None = None,
    ) -> InterviewRecord:
        """Create an InterviewRecord from an uploaded recording."""
        return self._create(
            user_id=user_id,
            source="upload",
            title=title or "面试录音复盘",
            audio_upload_id=audio_upload_id,
            resume_upload_id=resume_upload_id,
            transcript=transcript,
            analysis_json=analysis_json,
            status="ready" if analysis_json else "processing",
            db=db,
        )

    def create_from_mock(
        self,
        *,
        user_id: str,
        title: str = "",
        resume_upload_id: str | None = None,
        jd_upload_id: str | None = None,
        interview_plan: str = "",
        db: Session | None = None,
    ) -> InterviewRecord:
        """Create an InterviewRecord shell for an ongoing mock interview."""
        return self._create(
            user_id=user_id,
            source="mock",
            title=title or "模拟面试",
            resume_upload_id=resume_upload_id,
            jd_upload_id=jd_upload_id,
            interview_plan=interview_plan,
            status="processing",
            db=db,
        )

    # ── Read ──────────────────────────────────────────────────────────

    def get(self, record_id: str, user_id: str | None = None) -> InterviewRecord | None:
        db: Session = SessionLocal()
        try:
            query = db.query(InterviewRecord).filter(InterviewRecord.id == record_id)
            if user_id:
                query = query.filter(InterviewRecord.user_id == user_id)
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
                .filter(InterviewRecord.user_id == user_id)
                .order_by(InterviewRecord.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
        finally:
            db.close()

    # ── Update ────────────────────────────────────────────────────────

    def update_after_analysis(
        self,
        record_id: str,
        *,
        transcript: str,
        analysis_json: str,
        db: Session | None = None,
    ) -> InterviewRecord | None:
        """Called after Celery analysis task completes."""
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            row = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if row is None:
                return None
            row.transcript = transcript
            row.analysis_json = analysis_json
            row.status = "ready"
            row.updated_at = datetime.utcnow()
            if own_db:
                db.commit()
            else:
                db.flush()
            return row
        except Exception:
            if own_db:
                db.rollback()
            raise
        finally:
            if own_db:
                db.close()

    def finish_mock_interview(
        self,
        record_id: str,
        *,
        transcript: str,
        analysis_json: str,
        db: Session | None = None,
    ) -> InterviewRecord | None:
        """Called when a mock interview ends and results are generated."""
        return self.update_after_analysis(
            record_id,
            transcript=transcript,
            analysis_json=analysis_json,
            db=db,
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def get_analysis_summary(self, record_id: str, user_id: str) -> str:
        """Return a short reference summary for slot 2 of context assembly."""
        record = self.get(record_id, user_id)
        if record is None or not record.analysis_json:
            return ""
        try:
            report = json.loads(record.analysis_json)
        except json.JSONDecodeError:
            return ""

        overall = report.get("overall", {})
        per_question = report.get("per_question", [])
        lines = [
            f"综合评分: {overall.get('score', 'N/A')}/10",
            f"等级: {overall.get('grade', 'N/A')}",
            f"总体评价: {overall.get('feedback', '')}",
            "",
            "题目列表:",
        ]
        for i, pq in enumerate(per_question, 1):
            q = str(pq.get("question", ""))[:60]
            score = pq.get("score", "?")
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
        jd_upload_id: str | None = None,
        transcript: str = "",
        analysis_json: str = "",
        interview_plan: str = "",
        status: str = "processing",
        db: Session | None = None,
    ) -> InterviewRecord:
        own_db = db is None
        if own_db:
            db = SessionLocal()
        try:
            record = InterviewRecord(
                id=_generate_record_id(),
                user_id=user_id,
                source=source,
                title=title,
                audio_upload_id=audio_upload_id,
                resume_upload_id=resume_upload_id,
                jd_upload_id=jd_upload_id,
                transcript=transcript or None,
                analysis_json=analysis_json or None,
                interview_plan=interview_plan or None,
                status=status,
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
