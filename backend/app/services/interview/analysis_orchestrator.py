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
from datetime import datetime
import json
import logging
import os
import tempfile
from typing import Any

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.core.error_messages import humanize_error
from app.models.chat import Conversation, ConversationMessage
from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.interview_transcript import InterviewTranscript
from app.prompts.interview import DEBRIEF_SUMMARY_PROMPT
from app.services.uploads.file_asset_service import get_file_asset
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

            # Real per-question progress: each completed Stage-2 question
            # bumps ``analyzed_qa_count`` so the SSE stream can interpolate
            # an honest percent instead of a wall-clock guess. Sync DB write
            # per question is fine here — the worker runs --pool=solo and a
            # question costs an LLM call, so the write is noise.
            def _bump_progress(n: int) -> None:
                interview_record_service.increment_analyzed_count(record_id, by=n)

            # Branch on source:
            #   upload: noisy ASR transcript → 3-stage MapReduce pipeline
            #   mock  : pre-structured Q&A   → batched scoring with sliding window
            if source == "upload":
                from app.services.voice.interview_analysis_service import (
                    analyze_interview,
                )

                report = await analyze_interview(
                    transcript,
                    resume_context=resume_text,
                    jd_context=jd_text,
                    on_progress=_bump_progress,
                    user_id=owner_username,
                    # ANA-1: reuse Stage 1's result — re-extracting inside
                    # analyze_interview doubled the LLM cost and its
                    # independently-sampled pairs could mismatch the
                    # persisted shells (order_idx backfill misattribution).
                    qa_pairs=qa_pairs,
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
                    on_progress=_bump_progress,
                    user_id=owner_username,
                )

            self._persist_analysis(record_id, qa_pairs, report)
            # Best-effort: produce the cache-friendly summary that gets
            # injected into every debrief chat's record_context slot.
            # Non-fatal — a missing summary just falls back to the
            # truncated transcript at render time.
            try:
                await self._generate_debrief_summary(record_id, user_id=owner_username)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "debrief_summary generation failed for %s (non-fatal): %s",
                    record_id,
                    exc,
                )
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
                    from app.services.uploads.outbox_service import enqueue_job

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
                                run_after=datetime.utcnow()
                                + _td(hours=RECORD_QUIET_HOURS),
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
            from app.core.storage import download_file_from_s3

            _, ext = os.path.splitext(storage_uri)
            tmp_fd, local_path = tempfile.mkstemp(suffix=ext)
            os.close(tmp_fd)
            download_file_from_s3(storage_uri, local_path)
            is_temp = True

        try:
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
        from app.services.voice.interview_analysis_service import (
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
            rec = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if rec is not None:
                rec.analysis_json = json.dumps(top_level, ensure_ascii=False)
                rec.analyzed_qa_count = len(per_question)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _generate_debrief_summary(
        self,
        record_id: str,
        *,
        user_id: str | None = None,
    ) -> None:
        """LLM-produced 200-400 字 summary of one finished interview.

        The summary is the centrepiece of the ``record_context`` prompt
        slot — every debrief chat under this record sees it as part of
        the LLM's standing context. We also opportunistically fill
        ``record.tag`` when the user didn't pick one at upload time,
        because the tag drives downstream UI filters.

        Compose-once / cache-many: this runs exactly once per record at
        the end of analysis. After that the value is invariant for the
        lifetime of the record, which is why it cache-hits perfectly
        when injected into chat prompts.
        """
        # Pull the snapshot we'll feed to the LLM in one transaction so
        # we don't see a half-applied state.
        db: Session = SessionLocal()
        try:
            rec = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if rec is None:
                return
            existing_summary = (rec.debrief_summary or "").strip()
            if existing_summary:
                # Re-runs (e.g. user re-analyzed) shouldn't blow away a
                # summary that's already cached on the prompt-side; skip.
                return
            title = (rec.title or "").strip()
            tag = (rec.tag or "").strip()
            transcript = ""
            if rec.transcript_id:
                tr = (
                    db.query(InterviewTranscript)
                    .filter(InterviewTranscript.id == rec.transcript_id)
                    .first()
                )
                transcript = (tr.text if tr and tr.text else "").strip()
            analysis_json = rec.analysis_json or ""
            qa_rows = (
                db.query(InterviewQA)
                .filter(InterviewQA.record_id == record_id)
                .order_by(InterviewQA.order_idx)
                .all()
            )
            qa_lines = []
            for qa in qa_rows[:20]:  # cap so the prompt stays bounded
                q = (qa.question or "").strip()[:200]
                if not q:
                    continue
                score = f" (score={qa.score})" if qa.score is not None else ""
                qa_lines.append(f"- Q{qa.order_idx + 1}{score}: {q}")
        finally:
            db.close()

        # Parse the analysis blob defensively — bad JSON shouldn't kill
        # the summary step.
        overall_text = ""
        try:
            if analysis_json:
                blob = json.loads(analysis_json)
                overall = blob.get("overall") if isinstance(blob, dict) else None
                if isinstance(overall, dict):
                    pieces = []
                    if overall.get("score") is not None:
                        pieces.append(f"综合评分: {overall['score']}")
                    if overall.get("summary"):
                        pieces.append(f"综合评语: {overall['summary']}")
                    if overall.get("strengths"):
                        pieces.append(
                            "亮点: "
                            + " / ".join(str(s) for s in overall["strengths"][:5])
                        )
                    if overall.get("weaknesses"):
                        pieces.append(
                            "待提升: "
                            + " / ".join(str(w) for w in overall["weaknesses"][:5])
                        )
                    overall_text = "\n".join(pieces)
        except (json.JSONDecodeError, TypeError):
            overall_text = ""

        # Truncate transcript hard — we just want flavour, not the full
        # text (the chat's RAG layer can pull full transcript on demand).
        transcript_excerpt = transcript[:3000] if transcript else ""

        prompt = DEBRIEF_SUMMARY_PROMPT.format(
            title=title or "（未填）",
            tag=tag or "（未填，请推断）",
            overall_text=overall_text or "（无）",
            qa_lines="\n".join(qa_lines) or "（无 QA）",
            transcript_excerpt=transcript_excerpt or "（无转录）",
        )

        from app.core.llm_client_factory import get_internal_llm
        from app.services.memory._json_payload import _extract_json_payload

        response = await get_internal_llm("worker").acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        payload = _extract_json_payload(str(response.text))
        if not isinstance(payload, dict):
            return
        summary = str(payload.get("summary") or "").strip()
        new_tag = str(payload.get("tag") or "").strip()
        if not summary:
            return

        db = SessionLocal()
        try:
            rec = (
                db.query(InterviewRecord)
                .filter(InterviewRecord.id == record_id)
                .first()
            )
            if rec is None:
                return
            rec.debrief_summary = summary[:1500]  # generous cap; prompt asked for 400
            # Only fill tag when the user hadn't set one — never overwrite
            # a user-chosen tag with an LLM guess.
            if not (rec.tag or "").strip() and new_tag:
                rec.tag = new_tag[:32]
            db.commit()
            logger.info(
                "debrief_summary written for %s (%d chars; tag=%r)",
                record_id,
                len(summary),
                rec.tag,
            )
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


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


analysis_orchestrator = InterviewAnalysisOrchestrator()
