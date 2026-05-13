"""Unified interview analysis pipeline.

Drives an InterviewRecord from `pending` to `completed`. Same orchestrator for
both sources:
  - source='upload': WhisperX ASR → LLM Q&A extraction → per-question analysis → synthesis
  - source='mock'  : skip ASR/extraction (Q&A is already structured), reuse the
                     rest of the pipeline against the buffered Q&A so the user
                     ends up with the same review experience as upload.

Side-effects:
  - InterviewRecord.status flips through transcribing / extracting / analyzing
    / completed (or failed) — SSE consumers pick this up.
  - InterviewRecord.analyzed_qa_count increments after each per-question call,
    enabling fine-grained progress in the SSE stream.
  - Per-question rows live in InterviewQA, addressed by record_id + order_idx.

State writes use short transactions so the SSE poller observes intermediate
states. Long LLM calls happen outside any open transaction.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.mock_interview_session import MockInterviewSession
from app.models.upload import UserUpload
from app.services.interview_record_service import (
    STATUS_ANALYZING,
    STATUS_COMPLETED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_TRANSCRIBING,
    interview_record_service,
)

logger = logging.getLogger(__name__)


class InterviewAnalysisOrchestrator:
    """Pipeline orchestration; safe to call from a Celery worker."""

    # ── Public synchronous entry point (called by Celery task) ────────

    def run(self, record_id: str) -> dict[str, Any]:
        loop = _get_loop()
        return loop.run_until_complete(self._run_async(record_id))

    # ── Async core ────────────────────────────────────────────────────

    async def _run_async(self, record_id: str) -> dict[str, Any]:
        db = SessionLocal()
        try:
            record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if record is None:
                return {"status": "missing", "record_id": record_id}
            user_id = record.user_id
            source = record.source
            resume_text = record.resume_text_snapshot or ""
            jd_text = record.jd_text_snapshot or ""
        finally:
            db.close()

        try:
            if source == "upload":
                transcript = await self._stage_transcribe(record_id)
                qa_pairs = await self._stage_extract(record_id, transcript, resume_text)
            else:  # mock
                qa_pairs = self._load_mock_qa(record_id)
                transcript = self._compose_transcript_from_qa(qa_pairs)
                interview_record_service.set_transcript(record_id, transcript=transcript)

            # Persist QA shells (so SSE can show "X of Y analyzed" early on)
            self._persist_qa_shells(record_id, qa_pairs)

            interview_record_service.set_status(record_id, STATUS_ANALYZING)

            # Branch on source:
            #   upload: noisy ASR transcript → 3-stage MapReduce pipeline
            #   mock  : pre-structured Q&A   → batched scoring with sliding window
            if source == "upload":
                from app.services.voice.interview_analysis_service import analyze_interview

                report = await analyze_interview(
                    transcript,
                    resume_context=resume_text,
                    jd_context=jd_text,
                )
            else:
                from app.services.voice.interview_analysis_service import (
                    analyze_mock_qa_batched,
                )

                report = await analyze_mock_qa_batched(
                    qa_pairs,
                    resume_context=resume_text,
                    jd_context=jd_text,
                    batch_size=2,
                    ctx_prev=3,
                    ctx_next=2,
                )

            self._persist_analysis(record_id, qa_pairs, report)
            interview_record_service.set_status(record_id, STATUS_COMPLETED)
            return {"status": "completed", "record_id": record_id}

        except Exception as exc:
            logger.exception("Orchestrator failed for %s: %s", record_id, exc)
            interview_record_service.set_status(
                record_id, STATUS_FAILED, error_message=str(exc)
            )
            raise

    # ── Stages ────────────────────────────────────────────────────────

    async def _stage_transcribe(self, record_id: str) -> str:
        """Download audio + run WhisperX. Returns diarized transcript."""
        from app.services.voice.audio_transcription_service import transcribe_media

        interview_record_service.set_status(record_id, STATUS_TRANSCRIBING)

        db = SessionLocal()
        try:
            record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if record is None:
                raise RuntimeError(f"Record {record_id} disappeared mid-pipeline")
            if not record.audio_upload_id:
                raise RuntimeError(f"Upload record {record_id} has no audio_upload_id")

            upload = (
                db.query(UserUpload)
                .filter(UserUpload.id == record.audio_upload_id)
                .first()
            )
            if upload is None:
                raise RuntimeError(f"Audio upload {record.audio_upload_id} missing")
            if upload.user_id != record.user_id:
                raise RuntimeError("Audio upload owner mismatch")

            storage_uri = upload.storage_uri
        finally:
            db.close()

        local_path = storage_uri
        is_temp = False
        if storage_uri and storage_uri.startswith("s3://"):
            from app.services.storage_service import download_file_from_s3

            _, ext = os.path.splitext(storage_uri)
            tmp_fd, local_path = tempfile.mkstemp(suffix=ext)
            os.close(tmp_fd)
            download_file_from_s3(storage_uri, local_path)
            is_temp = True

        try:
            transcript = await transcribe_media(local_path)
            interview_record_service.set_transcript(record_id, transcript=transcript)
            return transcript
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.unlink(local_path)

    async def _stage_extract(
        self, record_id: str, transcript: str, resume_text: str
    ) -> list[dict[str, Any]]:
        """LLM extracts structured Q&A pairs from the diarized transcript."""
        from app.services.voice.interview_analysis_service import (
            extract_qa_pairs_with_llm,
        )

        interview_record_service.set_status(record_id, STATUS_EXTRACTING)
        qa_pairs = await extract_qa_pairs_with_llm(transcript, resume_text)
        return qa_pairs or []

    # ── Mock-specific helpers ─────────────────────────────────────────

    def _load_mock_qa(self, record_id: str) -> list[dict[str, Any]]:
        """Read the mock interview's qa_buffer and normalize entries for the
        downstream pipeline. Carries the Runtime Director metadata
        (action / topic / answer_quality) forward so QA rows are richer than
        the upload path's bare Q/A pairs and so the finish-time analyzer can
        use answer_quality as a scoring prior."""
        db = SessionLocal()
        try:
            mis = (
                db.query(MockInterviewSession)
                .filter(MockInterviewSession.interview_record_id == record_id)
                .first()
            )
            if mis is None or not mis.qa_buffer_json:
                return []
            try:
                buf = json.loads(mis.qa_buffer_json)
            except json.JSONDecodeError:
                return []
            if not isinstance(buf, list):
                return []
            normalized: list[dict[str, Any]] = []
            for entry in buf:
                if not isinstance(entry, dict):
                    continue
                aq = entry.get("answer_quality")
                normalized.append({
                    "question": str(entry.get("question") or ""),
                    "answer": str(entry.get("answer") or ""),
                    "phase": str(entry.get("phase_id") or entry.get("phase") or "technical"),
                    "is_follow_up": bool(entry.get("is_follow_up") or entry.get("action") == "follow_up"),
                    "topic": str(entry.get("topic") or "") or None,
                    "action": str(entry.get("action") or "") or None,
                    "answer_quality": aq if isinstance(aq, dict) else None,
                    # Legacy grounding_refs left for back-compat (always empty for v6 mock)
                    "grounding_refs": list(entry.get("grounding_refs") or []),
                })
            return normalized
        finally:
            db.close()

    @staticmethod
    def _compose_transcript_from_qa(qa_pairs: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for entry in qa_pairs:
            q = (entry.get("question") or "").strip()
            a = (entry.get("answer") or "").strip()
            if q:
                lines.append(f"面试官: {q}")
            if a:
                lines.append(f"候选人: {a}")
        return "\n\n".join(lines)

    # ── Persistence ───────────────────────────────────────────────────

    def _persist_qa_shells(
        self, record_id: str, qa_pairs: list[dict[str, Any]]
    ) -> None:
        """Write empty (score=null) per-question rows so the UI can show structure
        even mid-pipeline. Skipped when rows already exist (re-run scenario)."""
        db: Session = SessionLocal()
        try:
            existing = (
                db.query(InterviewQA.id)
                .filter(InterviewQA.record_id == record_id)
                .count()
            )
            if existing >= len(qa_pairs):
                return
            interview_record_service.bulk_insert_qa(record_id, qa_pairs[existing:], db=db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _persist_analysis(
        self,
        record_id: str,
        qa_pairs: list[dict[str, Any]],
        report: dict[str, Any],
    ) -> None:
        """Fan out report.per_question into InterviewQA rows; write the
        top-level (overall + phase_summary + meta) onto InterviewRecord."""
        per_question = report.get("per_question") or []
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(InterviewQA)
                .filter(InterviewQA.record_id == record_id)
                .order_by(InterviewQA.order_idx)
                .all()
            )
            row_by_idx = {r.order_idx: r for r in rows}

            for idx, pq in enumerate(per_question):
                if not isinstance(pq, dict):
                    continue
                row = row_by_idx.get(idx)
                if row is None:
                    # Shell missing — orchestrator inserted N pairs but extractor
                    # returned more questions. Create the missing row.
                    interview_record_service.bulk_insert_qa(
                        record_id,
                        [{"question": pq.get("question", ""), "answer": pq.get("answer", "")}],
                        db=db,
                    )
                    row = (
                        db.query(InterviewQA)
                        .filter(InterviewQA.record_id == record_id, InterviewQA.order_idx == idx)
                        .first()
                    )
                    if row is None:
                        continue

                row.score = _safe_int(pq.get("score"))
                row.critique = pq.get("critique") or pq.get("feedback")
                row.improved_answer = pq.get("improved_answer")
                kp = pq.get("key_points")
                if isinstance(kp, list):
                    row.key_points_json = json.dumps(kp, ensure_ascii=False)
                if pq.get("question") and not row.question:
                    row.question = pq["question"]
                if pq.get("answer") and not row.answer:
                    row.answer = pq["answer"]
                if pq.get("phase"):
                    row.phase = pq["phase"]
                from datetime import datetime as _dt
                row.analyzed_at = _dt.utcnow()

            top_level = {
                "schema_version": 2,
                "overall": report.get("overall", {}),
                "phase_summary": report.get("phase_summary", {}),
                "meta": report.get("meta") or report.get("interview_metadata") or {},
            }
            rec = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if rec is not None:
                rec.analysis_json = json.dumps(top_level, ensure_ascii=False)
                rec.analyzed_qa_count = len(per_question)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


# ── Helpers ──────────────────────────────────────────────────────────────

import threading


_loop_local = threading.local()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Reuse a per-thread event loop so we don't create/tear down on each task."""
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


analysis_orchestrator = InterviewAnalysisOrchestrator()
