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
from app.services.uploads.file_asset_service import get_file_asset
from app.services.interview.interview_record_service import (
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

    def run(self, record_id: str, language: str = "zh") -> dict[str, Any]:
        loop = _get_loop()
        return loop.run_until_complete(self._run_async(record_id, language=language))

    # ── Async core ────────────────────────────────────────────────────

    async def _run_async(self, record_id: str, language: str = "zh") -> dict[str, Any]:
        db = SessionLocal()
        try:
            record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if record is None:
                return {"status": "missing", "record_id": record_id}
            source = record.source
            resume_text = record.resume_text_snapshot or ""
            jd_text = record.jd_text_snapshot or ""
        finally:
            db.close()

        try:
            if source == "upload":
                transcript = await self._stage_transcribe(record_id, language=language)
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
            # Best-effort: produce the cache-friendly summary that gets
            # injected into every debrief chat's record_context slot.
            # Non-fatal — a missing summary just falls back to the
            # truncated transcript at render time.
            try:
                await self._generate_debrief_summary(record_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "debrief_summary generation failed for %s (non-fatal): %s",
                    record_id, exc,
                )
            interview_record_service.set_status(record_id, STATUS_COMPLETED)
            return {"status": "completed", "record_id": record_id}

        except Exception as exc:
            logger.exception("Orchestrator failed for %s: %s", record_id, exc)
            interview_record_service.set_status(
                record_id, STATUS_FAILED, error_message=str(exc)
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
            record = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if record is None:
                raise RuntimeError(f"Record {record_id} disappeared mid-pipeline")
            if not record.audio_upload_id:
                raise RuntimeError(f"Upload record {record_id} has no audio_upload_id")

            # record.user_id is the stable users.id (CLEANUP #2), as is the
            # FileAsset's — fetch by id (trusted worker context) + compare pks.
            upload = get_file_asset(db, record.audio_upload_id)
            if upload is None or upload.user_id != record.user_id:
                raise RuntimeError(
                    f"Audio upload {record.audio_upload_id} missing or not owned"
                )

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
            transcript = await transcribe_media(local_path, language=language)
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


    async def _generate_debrief_summary(self, record_id: str) -> None:
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
            rec = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
            if rec is None:
                return
            existing_summary = (rec.debrief_summary or "").strip()
            if existing_summary:
                # Re-runs (e.g. user re-analyzed) shouldn't blow away a
                # summary that's already cached on the prompt-side; skip.
                return
            title = (rec.title or "").strip()
            tag = (rec.tag or "").strip()
            transcript = (rec.transcript or "").strip()
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
                        pieces.append("亮点: " + " / ".join(str(s) for s in overall["strengths"][:5]))
                    if overall.get("weaknesses"):
                        pieces.append("待提升: " + " / ".join(str(w) for w in overall["weaknesses"][:5]))
                    overall_text = "\n".join(pieces)
        except (json.JSONDecodeError, TypeError):
            overall_text = ""

        # Truncate transcript hard — we just want flavour, not the full
        # text (the chat's RAG layer can pull full transcript on demand).
        transcript_excerpt = transcript[:3000] if transcript else ""

        prompt = (
            "你正在为一份面试记录写一段浓缩的复盘摘要，这段摘要会作为后续所有对话的"
            "**恒定前导上下文**（命中 prompt cache），所以要密度高、信息全、200-400 字之间。\n\n"
            "请同时推断一个合适的标签（中文，不超过 8 字），用于该面试的分类。如果用户已设"
            "标签则尊重原值不动。\n\n"
            f"## 面试标题\n{title or '（未填）'}\n\n"
            f"## 用户已选标签\n{tag or '（未填，请推断）'}\n\n"
            f"## 分析概览\n{overall_text or '（无）'}\n\n"
            f"## 题目清单\n{chr(10).join(qa_lines) or '（无 QA）'}\n\n"
            f"## 转录片段（前 3000 字符，仅参考）\n{transcript_excerpt or '（无转录）'}\n\n"
            "**输出格式（严格 JSON，不要任何额外文字）**：\n"
            '{"tag": "<推断或保留的标签>", "summary": "<200-400 字浓缩摘要，覆盖：'
            '岗位方向 / 主要话题 / 候选人表现亮点 / 待改进点 / 整体评价。不要罗列原题，'
            '描述要凝练成段落。>"}\n'
        )

        from app.rag.embeddings import agent_fast_llm
        from app.services.memory._json_payload import _extract_json_payload

        response = await agent_fast_llm.acomplete(prompt)
        payload = _extract_json_payload(str(response.text))
        if not isinstance(payload, dict):
            return
        summary = str(payload.get("summary") or "").strip()
        new_tag = str(payload.get("tag") or "").strip()
        if not summary:
            return

        db = SessionLocal()
        try:
            rec = db.query(InterviewRecord).filter(InterviewRecord.id == record_id).first()
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
                record_id, len(summary), rec.tag,
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
