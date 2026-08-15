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
from app.services.voice.transcript_evidence import TranscriptEvidence

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
                evidence_bundle = interview_record_service.get_transcript_evidence(
                    record_id
                )
                if evidence_bundle is not None:
                    transcript_row, evidence = evidence_bundle
                    transcript_id = transcript_row.id
                    transcript = transcript_row.text or ""
                    logger.info(
                        "stage gate: reusing v2 transcript evidence for %s (%d words)",
                        record_id,
                        len(evidence.words),
                    )
                else:
                    legacy_text = interview_record_service.get_transcript_text(
                        record_id
                    )
                    if legacy_text.strip():
                        raise RuntimeError(
                            "transcript_evidence_required: 旧转写没有词级证据，"
                            "请从原录音重新转写"
                        )
                    transcript_id, evidence, transcript = await self._stage_transcribe(
                        record_id, language=language
                    )

                qa_pairs = self._load_existing_qa_shells(
                    record_id,
                    source_transcript_id=transcript_id,
                    require_provenance=True,
                )
                if qa_pairs:
                    logger.info(
                        "stage gate: reusing %d persisted QA shells for %s",
                        len(qa_pairs),
                        record_id,
                    )
                else:
                    qa_pairs = await self._stage_extract(
                        record_id,
                        transcript_id,
                        evidence,
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

    async def _stage_transcribe(
        self, record_id: str, language: str = "zh"
    ) -> tuple[str, TranscriptEvidence, str]:
        """Download audio and persist immutable word-level evidence.

        ``language`` is forwarded to ``transcribe_media`` which passes it
        to WhisperX. ``"auto"`` becomes ``None`` (let Whisper detect)
        inside the transcription service.
        """
        from app.services.uploads.file_asset_service import file_asset_version_token
        from app.services.voice.audio_transcription_service import (
            transcribe_interview_evidence,
        )

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
            file_asset_id = upload.id
            file_asset_version = file_asset_version_token(upload)
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
            evidence = await transcribe_interview_evidence(
                local_path,
                file_asset_id=file_asset_id,
                file_asset_version=file_asset_version,
                language=language,
            )
            transcript_id = interview_record_service.set_transcript_evidence(
                record_id,
                evidence=evidence,
                provider="local_whisperx",
            )
            transcript = interview_record_service.get_transcript_text(record_id)
            return transcript_id, evidence, transcript
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.unlink(local_path)

    async def _stage_extract(
        self,
        record_id: str,
        transcript_id: str,
        evidence: TranscriptEvidence,
    ) -> list[dict[str, Any]]:
        """Project ID-only structure and reconstruct QA from evidence."""
        from app.services.interview.transcript_structure_service import (
            project_interview_qa,
        )

        interview_record_service.set_status(record_id, STATUS_EXTRACTING)
        projected = await project_interview_qa(evidence)
        interview_record_service.set_transcript_projection(
            transcript_id,
            structure=projected.structure.model_dump(mode="json"),
            quality=projected.quality.model_dump(mode="json"),
        )
        qa_pairs = projected.qa_pairs
        for pair in qa_pairs:
            pair["source_transcript_id"] = transcript_id
        if not qa_pairs:
            raise RuntimeError(
                "未能从转写中恢复出可验证的问答轮次，请检查转写质量后重试"
            )
        self._persist_qa_shells(record_id, qa_pairs)
        if projected.quality.status != "complete":
            raise RuntimeError(
                "qa_coverage_insufficient: 候选人回答覆盖率或词级证据置信度"
                "未达到完整报告门槛，请先复核转写结构"
            )
        return qa_pairs

    def _load_existing_qa_shells(
        self,
        record_id: str,
        *,
        source_transcript_id: str | None = None,
        require_provenance: bool = False,
    ) -> list[dict[str, Any]]:
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
            if require_provenance and any(
                row.source_transcript_id != source_transcript_id
                or not isinstance(row.source_provenance_json, dict)
                for row in rows
            ):
                raise RuntimeError(
                    "transcript_evidence_required: 现有 QA 缺少词级来源，"
                    "请删除旧 QA 并从原录音重新转写"
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
                "generation_status": report.get("generation_status", "complete"),
                "generation_warnings": report.get("generation_warnings", []),
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
                serialized_analysis = json.dumps(
                    top_level, ensure_ascii=False, sort_keys=True
                )
                if rec.analysis_json != serialized_analysis:
                    rec.ability_signal_generation = (
                        int(rec.ability_signal_generation) + 1
                    )
                rec.analysis_json = serialized_analysis
                rec.analysis_schema_version = 3
                rec.analyzed_qa_count = len(per_question)
                generated_tag = str(report.get("tag") or "").strip()
                if not (rec.tag or "").strip() and generated_tag:
                    rec.tag = generated_tag[:8]
                db.add(rec)
                db.flush()
                from app.services.ability_signal_service import (
                    project_interview_ability_signals,
                )

                project_interview_ability_signals(
                    db,
                    user_pk=rec.user_id,
                    interview_record_id=rec.id,
                )
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
