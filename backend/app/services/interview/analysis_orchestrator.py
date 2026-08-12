"""Unified interview analysis pipeline.

Drives an InterviewRecord from `pending` to `completed`. Same orchestrator for
both sources:
  - source='upload': WhisperX ASR → LLM Q&A extraction → shared batch analysis → synthesis
  - source='mock'  : skip ASR/extraction (Q&A is already structured), reuse the
                     rest of the pipeline against the buffered Q&A so the user
                     ends up with the same review experience as upload.

Side-effects:
  - InterviewRecord.status flips through transcribing / extracting / analyzing
    / completed (or failed) — SSE consumers pick this up.
  - InterviewRecord.analyzed_qa_count increments after each analyzed batch,
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
from typing import Any

from sqlalchemy.orm import Session

from app.core.error_messages import humanize_error
from app.core.runtime_files import create_runtime_temp_file
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.chat import Conversation, ConversationMessage
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.services.interview.interview_record_service import (
    STATUS_ANALYZING,
    STATUS_COMPLETED,
    STATUS_EXTRACTING,
    STATUS_FAILED,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
    STATUS_REVIEW_READY,
    STATUS_TRANSCRIBING,
    interview_record_service,
)
from app.services.uploads.file_asset_service import get_file_asset

logger = logging.getLogger(__name__)


class InterviewAnalysisOrchestrator:
    """Pipeline orchestration; safe to call from a Celery worker."""

    # ── Public synchronous entry point (called by Celery task) ────────

    def run(self, record_id: str, language: str = "zh") -> dict[str, Any]:
        loop = _get_loop()
        return loop.run_until_complete(self._run_async(record_id, language=language))

    # ── Async core ────────────────────────────────────────────────────

    async def _run_async(self, record_id: str, language: str = "zh") -> dict[str, Any]:
        db = SessionLocal()
        try:
            record = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if record is None:
                return {"status": "missing", "record_id": record_id}
            source = record.source
            resume_text = record.resume_text_snapshot or ""
            jd_text = record.jd_text_snapshot or ""
            # Owner identity for LLM resolution (MDL-1): background analysis
            # runs with the record owner's model selection + keys. The
            # credential chain is username-keyed; record.user_id is the pk.
            from app.models.user import User

            owner_username = (
                db.query(User.username).filter(User.id == record.user_id).scalar()
            )
        finally:
            db.close()

        # Status vocabulary differs by source: a mock moves through the
        # review states (processing_review → review_ready / review_failed),
        # an upload through the analysis states (analyzing → completed /
        # failed). Everything else in the pipeline is shared.
        is_mock = source == "mock"
        in_flight_status = STATUS_PROCESSING_REVIEW if is_mock else STATUS_ANALYZING
        done_status = STATUS_REVIEW_READY if is_mock else STATUS_COMPLETED
        fail_status = STATUS_REVIEW_FAILED if is_mock else STATUS_FAILED

        try:
            if source == "upload":
                # ── Stage gates (ANA-3) ──────────────────────────────
                # The pipeline is artifact-driven: transcript and QA
                # shells are durable checkpoints. A retry / redelivery
                # resumes from whatever already exists instead of paying
                # for ASR (+minutes) and extraction (+LLM) again.
                transcript = interview_record_service.get_transcript_text(record_id)
                if transcript.strip():
                    logger.info(
                        "stage gate: reusing persisted transcript for %s (%d chars)",
                        record_id,
                        len(transcript),
                    )
                else:
                    transcript = await self._stage_transcribe(
                        record_id, language=language
                    )

                qa_pairs = self._load_existing_qa_shells(record_id)
                if qa_pairs:
                    logger.info(
                        "stage gate: reusing %d persisted QA shells for %s",
                        len(qa_pairs),
                        record_id,
                    )
                else:
                    qa_pairs = await self._stage_extract(
                        record_id,
                        transcript,
                        resume_text,
                        user_id=owner_username,
                    )
            else:  # mock
                qa_pairs = self._load_mock_qa(record_id)
                transcript = self._compose_transcript_from_qa(qa_pairs)
                interview_record_service.set_transcript(
                    record_id,
                    transcript=transcript,
                    provider="mock_composed",
                )

            # Persist QA shells (so SSE can show "X of Y analyzed" early on)
            self._persist_qa_shells(record_id, qa_pairs)

            # Zero the per-question counter BEFORE flipping status: the SSE
            # stream interpolates percent from the counter whenever status is
            # in-flight, so the opposite order lets one poll window see the
            # previous attempt's (possibly complete) count and jump to 95%
            # before snapping back.
            interview_record_service.reset_analyzed_count(record_id)
            interview_record_service.set_status(record_id, in_flight_status)

            # Real question progress: each completed batch bumps
            # ``analyzed_qa_count`` by its size so SSE can interpolate
            # an honest percent instead of a wall-clock guess. Sync DB write
            # per question is fine here — the worker runs --pool=solo and a
            # question costs an LLM call, so the write is noise.
            def _bump_progress(n: int) -> None:
                interview_record_service.increment_analyzed_count(record_id, by=n)

            # Extraction differs by source; once structured Q&A exists, both
            # sources use the same scoring and synthesis implementation.
            from app.services.interview.analysis.service import analyze_qa_batched

            report = await analyze_qa_batched(
                qa_pairs,
                resume_context=resume_text,
                jd_context=jd_text,
                on_progress=_bump_progress,
                user_id=owner_username,
            )

            self._persist_analysis(record_id, report)
            interview_record_service.set_status(record_id, done_status)
            # Event-driven dreaming (MEM-9): a finished analysis is exactly
            # the "new growth evidence exists" moment. The quiet-window wait
            # rides the OUTBOX (run_after) — a 6h Celery countdown would sit
            # unacked past the broker's visibility_timeout (3700s) and be
            # redelivered ~hourly. Idempotency-keyed per (user, record) so a
            # reanalyze doesn't stack checks. Best-effort — the nightly scan
            # remains the backstop.
            if owner_username:
                try:
                    from datetime import timedelta as _td

                    from app.services.memory.dreaming_worker import RECORD_QUIET_HOURS
                    from app.services.outbox import enqueue_job

                    with SessionLocal() as odb:
                        rec_row = (
                            odb.query(InterviewRecord)
                            .filter(InterviewRecord.id == record_id)
                            .first()
                        )
                        if rec_row is not None:
                            enqueue_job(
                                odb,
                                user_pk=rec_row.user_id,
                                job_type="dream_check_user",
                                aggregate_type="interview_record",
                                aggregate_id=record_id,
                                payload={"username": owner_username},
                                idempotency_key=f"dream_check:{record_id}",
                                run_after=utc_now() + _td(hours=RECORD_QUIET_HOURS),
                            )
                            odb.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "event-driven dream scheduling failed for %s: %s",
                        record_id,
                        exc,
                    )
            return {"status": done_status, "record_id": record_id}

        except Exception as exc:
            logger.exception("Orchestrator failed for %s: %s", record_id, exc)
            interview_record_service.set_status(
                record_id,
                fail_status,
                error_message=f"分析失败：{humanize_error(exc)}"[:500],
            )
            raise

    # ── Stages ────────────────────────────────────────────────────────

    async def _stage_transcribe(self, record_id: str, language: str = "zh") -> str:
        """Download audio + run WhisperX. Returns diarized transcript.

        ``language`` is forwarded to ``transcribe_media`` which passes it
        to WhisperX. ``"auto"`` becomes ``None`` (let Whisper detect)
        inside the transcription service.
        """
        from app.services.voice.audio_transcription_service import transcribe_media

        interview_record_service.set_status(record_id, STATUS_TRANSCRIBING)

        db = SessionLocal()
        try:
            record = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if record is None:
                raise RuntimeError(f"Record {record_id} disappeared mid-pipeline")
            if not record.audio_file_asset_id:
                raise RuntimeError(
                    f"Upload record {record_id} has no audio_file_asset_id"
                )

            # record.user_id is the stable users.id (CLEANUP #2), as is the
            # FileAsset's — fetch by id (trusted worker context) + compare pks.
            upload = get_file_asset(db, record.audio_file_asset_id)
            if upload is None or upload.user_id != record.user_id:
                raise RuntimeError(
                    f"Audio upload {record.audio_file_asset_id} missing or not owned"
                )

            storage_uri = upload.storage_uri
        finally:
            db.close()

        local_path = storage_uri
        is_temp = False
        if storage_uri and storage_uri.startswith("s3://"):
            _, ext = os.path.splitext(storage_uri)
            local_path = create_runtime_temp_file(suffix=ext)
            is_temp = True

        try:
            if is_temp:
                from app.core.storage import download_file_from_s3

                download_file_from_s3(storage_uri, local_path)
            transcript = await transcribe_media(local_path, language=language)
            interview_record_service.set_transcript(
                record_id,
                transcript=transcript,
                provider="local_whisperx",
                language=language,
            )
            return transcript
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.unlink(local_path)

    async def _stage_extract(
        self,
        record_id: str,
        transcript: str,
        resume_text: str,
        *,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """LLM extracts structured Q&A pairs from the diarized transcript."""
        from app.services.interview.analysis.service import (
            extract_qa_pairs_with_llm,
        )

        interview_record_service.set_status(record_id, STATUS_EXTRACTING)
        qa_pairs = await extract_qa_pairs_with_llm(
            transcript,
            resume_text,
            user_id=user_id,
        )
        return qa_pairs or []

    def _load_existing_qa_shells(self, record_id: str) -> list[dict[str, Any]]:
        """Stage gate (ANA-3): QA shells persisted by an earlier attempt.

        Returns [] when none exist (fresh run). Rows are returned in
        order_idx order and renumbered 1-based to match extractor output.
        """
        db = SessionLocal()
        try:
            rows = (
                db.query(InterviewQA)
                .filter(InterviewQA.record_id == record_id)
                .order_by(InterviewQA.order_idx)
                .all()
            )
            return [
                {
                    "index": i,
                    "question": row.question or "",
                    "answer": row.answer or "",
                    "question_summary": "",
                    "phase": row.phase or "general",
                    "is_follow_up": False,
                    "parent_index": None,
                }
                for i, row in enumerate(rows, start=1)
                if (row.question or "").strip()
            ]
        finally:
            db.close()

    # ── Mock-specific helpers ─────────────────────────────────────────

    def _load_mock_qa(self, record_id: str) -> list[dict[str, Any]]:
        """Parse structured Q&A pairs out of the mock conversation's messages.

        The mock interview's process lives in ``conversation_messages`` (the
        target architecture — no qa_buffer blob). Each interviewer
        (``assistant``) line is a question; the next candidate (``user``) line
        is its answer. The trailing unanswered question (if any) is dropped.
        These bare pairs feed the same scoring back-half as the upload path.
        """
        db = SessionLocal()
        try:
            conv = (
                db.query(Conversation)
                .filter(
                    Conversation.subject_id == record_id,
                    Conversation.type == "mock_interview",
                )
                .order_by(Conversation.created_at.asc())
                .first()
            )
            if conv is None:
                return []
            rows = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conv.id)
                .order_by(ConversationMessage.seq.asc())
                .all()
            )
        finally:
            db.close()

        def _blocks(r) -> list[dict[str, Any]]:
            if not r.content_blocks_json:
                return []
            try:
                blocks = json.loads(r.content_blocks_json)
                return blocks if isinstance(blocks, list) else []
            except (json.JSONDecodeError, TypeError):
                return []

        # Stage keys are frozen onto assistant messages as content blocks at
        # append time (MOCK-8) — the shared STAGE_TO_PHASE map (defined next
        # to the plan templates) attributes questions to their real stage
        # instead of blanket "technical".
        from app.services.interview.mock_interview_service import STAGE_TO_PHASE

        stage_to_phase = STAGE_TO_PHASE

        qa_pairs: list[dict[str, Any]] = []
        pending_q: str | None = None
        pending_phase: str = "general"
        for r in rows:
            role = (r.role or "").lower()
            content = (r.content or "").strip()
            if role.startswith(("assistant", "agent")):
                # New interviewer line. If a prior question is still
                # unanswered (two interviewer lines in a row), the latest wins.
                pending_q = content or pending_q
                stage_key = next(
                    (
                        str(b.get("stage_key") or "")
                        for b in _blocks(r)
                        if isinstance(b, dict) and b.get("type") == "stage"
                    ),
                    "",
                )
                pending_phase = (
                    stage_to_phase.get(stage_key, "general")
                    if stage_key
                    else pending_phase
                )
            elif role.startswith(("user", "candidate")):
                audio_asset = next(
                    (
                        str(b.get("file_asset_id") or "")
                        for b in _blocks(r)
                        if isinstance(b, dict) and b.get("type") == "audio"
                    ),
                    None,
                )
                if pending_q:
                    qa_pairs.append(
                        {
                            "question": pending_q,
                            "answer": content,
                            "phase": pending_phase,
                            "is_follow_up": False,
                            "topic": None,
                            "action": None,
                            "answer_quality": None,
                            "answer_audio_file_asset_id": audio_asset or None,
                            "answer_input_mode": "voice" if audio_asset else "text",
                        }
                    )
                    pending_q = None
                elif qa_pairs and content:
                    # Consecutive candidate messages (a two-phase-transaction
                    # retry appended a second answer before the interviewer
                    # replied) — merge into the previous answer instead of
                    # dropping it on the floor.
                    merged = qa_pairs[-1]["answer"] + "\n" + content
                    qa_pairs[-1]["answer"] = merged.strip()
            # system / tool roles are ignored
        return qa_pairs

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
            interview_record_service.bulk_insert_qa(
                record_id, qa_pairs[existing:], db=db
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _persist_analysis(
        self,
        record_id: str,
        report: dict[str, Any],
    ) -> None:
        """Persist per-question results and the compact top-level report."""
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
                        [
                            {
                                "question": pq.get("question", ""),
                                "answer": pq.get("answer", ""),
                            }
                        ],
                        db=db,
                    )
                    row = (
                        db.query(InterviewQA)
                        .filter(
                            InterviewQA.record_id == record_id,
                            InterviewQA.order_idx == idx,
                        )
                        .first()
                    )
                    if row is None:
                        continue

                row.score = _safe_score(pq.get("score"))
                row.critique = pq.get("critique") or pq.get("feedback")
                row.improved_answer = pq.get("improved_answer")
                kp = pq.get("tags")
                if isinstance(kp, list):
                    row.key_points_json = json.dumps(kp, ensure_ascii=False)
                if pq.get("question") and not row.question:
                    row.question = pq["question"]
                if pq.get("answer") and not row.answer:
                    row.answer = pq["answer"]
                if pq.get("phase"):
                    row.phase = pq["phase"]
                row.analyzed_at = utc_now()

            top_level = {
                "schema_version": 3,
                "overall": report.get("overall", {}),
                "phase_summary": report.get("phase_summary", []),
                "skill_radar": report.get("skill_radar", {}),
            }
            rec = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if rec is not None:
                rec.analysis_json = json.dumps(top_level, ensure_ascii=False)
                rec.analysis_schema_version = 3
                rec.analyzed_qa_count = len(per_question)
                generated_tag = str(report.get("tag") or "").strip()
                if not (rec.tag or "").strip() and generated_tag:
                    rec.tag = generated_tag[:8]
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


# ── Helpers ──────────────────────────────────────────────────────────────

import threading  # noqa: E402

_loop_local = threading.local()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Reuse a per-thread event loop so we don't create/tear down on each task."""
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop


def _safe_score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(max(0.0, min(10.0, float(value))), 1)
    return None


analysis_orchestrator = InterviewAnalysisOrchestrator()
