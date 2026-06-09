"""Mock-interview control endpoints (target architecture, RFC §6.4).

The mock-start endpoint OWNS the creation of the whole run — it atomically
creates the ``interview_records`` (status=mock_in_progress), the
``conversations`` (type=mock_interview, bound to the record via
subject_type/subject_id) and the ``mock_interview_runtime`` (status=in_progress)
in one transaction. Subsequent calls address the run by ``record_id``:

  start         -> create record + conversation + runtime + opening message
  answer        -> append user msg, generate next interviewer line (1 LLM call,
                   no Director/retry), append assistant msg, advance runtime
  finish        -> record -> processing_review, dispatch the review task
  retry-review  -> re-dispatch review from the preserved conversation messages
  DELETE        -> abandon an unfinished run, delete its exclusive data
  in-progress   -> resume banner, sourced from the live runtime row

The process transcript lives in ``conversation_messages``; the structured QA +
scoring is frozen into ``interview_qa`` by the unified analysis orchestrator
(shared with the upload-audio debrief path).
"""

import asyncio
import json
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.error_messages import humanize_error
from app.core.rate_limit import RATE_DEFAULT, RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import Conversation, ConversationMessage, generate_uuid
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.schemas.chat import (
    MockAbandonResp,
    MockAnswerRequest,
    MockAnswerResp,
    MockFinishResp,
    MockInProgressResp,
    MockParseJdResp,
    MockRetryReviewResp,
    MockStage,
    MockStartRequest,
    MockStartResp,
    MockTranscribeResp,
    TTSRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mock"])


# ── Message helpers ──────────────────────────────────────────────────────


def _append_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    *,
    content_blocks_json: str | None = None,
) -> ConversationMessage:
    """Append one message to a conversation (monotonic seq). Flushes so the
    autoincrement id is available to the caller (the runtime records the
    awaiting-answer message id)."""
    max_seq = (
        db.query(func.max(ConversationMessage.seq))
        .filter(ConversationMessage.conversation_id == conversation_id)
        .scalar()
    )
    msg = ConversationMessage(
        conversation_id=conversation_id,
        seq=(max_seq or 0) + 1,
        role=role,
        content=content,
        content_blocks_json=content_blocks_json,
    )
    db.add(msg)
    db.flush()
    return msg


def _recent_messages(db: Session, conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    rows = (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.seq.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content or ""} for r in rows]


# ── Resume / JD context resolution ───────────────────────────────────────


def _resolve_resume_context(
    db: Session, body: MockStartRequest, username: str,
) -> tuple[str, str | None]:
    """Return (resume_text, resume_source) from a personal resume entity or an
    uploaded resume file asset. Empty string when neither is provided."""
    if body.resume_id:
        try:
            from app.services.resume import resume_entity_service
            from app.services.resume.resume_service import resume_service

            resume = resume_entity_service.get_owned_resume(
                db, resume_id=body.resume_id, user_id=username,
            )
            if resume is not None:
                sections = resume_service.get_sections_by_resume(resume.id)
                if sections:
                    return resume_service.format_for_context(sections), "personal_resume"
                if (resume.raw_text_snapshot or "").strip():
                    return resume.raw_text_snapshot.strip(), "personal_resume"
        except Exception as exc:  # noqa: BLE001
            logger.warning("mock resume context load failed: %s", exc)
        return "", None
    if body.resume_file_asset_id:
        text = _extract_file_asset_text(db, body.resume_file_asset_id, username)
        return text, ("context_upload" if text else None)
    return "", None


def _resolve_jd_context(db: Session, body: MockStartRequest, username: str) -> str:
    if (body.jd_text or "").strip():
        return body.jd_text.strip()
    if body.jd_file_asset_id:
        return _extract_file_asset_text(db, body.jd_file_asset_id, username)
    return ""


def _extract_file_asset_text(db: Session, asset_id: str, username: str) -> str:
    """Best-effort: download an owned file asset and extract its plain text."""
    try:
        from app.services.uploads.file_asset_service import get_file_asset
        from app.services.voice.file_parser import extract_resume_text

        asset = get_file_asset(db, asset_id)
        if asset is None or asset.user_id != resolve_user_pk(db, username):
            return ""
        storage_uri = asset.storage_uri
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
            return (extract_resume_text(local_path) or "").strip()
        finally:
            if is_temp and local_path and os.path.exists(local_path):
                os.unlink(local_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock file-asset text extraction failed for %s: %s", asset_id, exc)
        return ""


def _owned_mock_record(db: Session, record_id: str, username: str) -> InterviewRecord:
    record = (
        db.query(InterviewRecord)
        .filter(
            InterviewRecord.id == record_id,
            InterviewRecord.user_id == resolve_user_pk(db, username),
            InterviewRecord.source == "mock",
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Mock interview not found")
    return record


# ── /start ───────────────────────────────────────────────────────────────


@router.post("/mock-interviews/start", response_model=MockStartResp)
@limiter.limit(RATE_EXPENSIVE)
async def start_mock_interview(
    request: Request,
    response: Response,
    body: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atomically create the record + conversation + runtime and return the
    opening interviewer line. No pre-created chat session — start owns it."""
    from app.services.interview.interview_record_service import (
        STATUS_MOCK_IN_PROGRESS,
        interview_record_service,
    )
    from app.services.interview.mock_interview_service import generate_plan
    from app.services.interview import mock_runtime_service

    resume_context, resume_source = _resolve_resume_context(db, body, current_user.username)
    jd_context = _resolve_jd_context(db, body, current_user.username)

    plan = generate_plan(
        resume_context=resume_context,
        jd_context=jd_context,
        interviewer_style=body.interviewer_style,
        plan_template_key=body.plan_template_key,
    )

    try:
        # 1) record (mock_in_progress) — freezes the resume/JD snapshots + plan.
        record = interview_record_service.create_for_mock(
            user_id=current_user.username,
            title="模拟面试",
            resume_id=body.resume_id,
            resume_file_asset_id=body.resume_file_asset_id,
            resume_source=resume_source,
            jd_file_asset_id=body.jd_file_asset_id,
            resume_text_snapshot=resume_context,
            jd_text_snapshot=jd_context,
            interview_plan=plan.plan_json,
            status=STATUS_MOCK_IN_PROGRESS,
            db=db,
        )

        # 2) conversation (bound to the record via subject_type/subject_id).
        conversation = Conversation(
            id=generate_uuid(),
            user_id=resolve_user_pk(db, current_user.username),
            title="模拟面试",
            type="mock_interview",
            mode="chat",
            subject_type="interview_record",
            subject_id=record.id,
        )
        db.add(conversation)
        db.flush()

        # 3) opening interviewer message.
        opening = _append_message(
            db, conversation.id, "assistant", plan.opening_message,
        )

        # 4) runtime (in_progress), pointed at the opening question.
        runtime = mock_runtime_service.create_runtime(
            db,
            user_id=current_user.username,
            interview_record_id=record.id,
            conversation_id=conversation.id,
            plan=plan.stages,
            plan_template_key=plan.template_key,
            interviewer_style=body.interviewer_style,
            voice_mode=body.voice_mode,
            current_stage_key=plan.first_stage_key,
            commit=False,
        )
        runtime.current_question_text = plan.opening_message
        runtime.current_question_message_id = opening.id

        await asyncio.to_thread(db.commit)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("mock start failed for user=%s: %s", current_user.username, exc)
        raise HTTPException(
            status_code=500, detail=f"开始模拟面试失败：{humanize_error(exc)}",
        ) from exc

    return MockStartResp(
        interview_record_id=record.id,
        conversation_id=conversation.id,
        runtime_id=runtime.id,
        current_stage_key=plan.first_stage_key,
        current_question=plan.opening_message,
        plan_phases=[MockStage(key=s["key"], title=s["title"]) for s in plan.stages],
    )


# ── /answer ────────────────────────────────────────────────────────────────


@router.post("/mock-interviews/{record_id}/answer", response_model=MockAnswerResp)
@limiter.limit(RATE_EXPENSIVE)
async def submit_mock_answer(
    request: Request,
    response: Response,
    record_id: str,
    body: MockAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One turn: persist the candidate's answer, generate the next interviewer
    line from the plan + stage + recent messages, persist it, advance runtime."""
    from app.services.interview.mock_interview_service import (
        build_prefix,
        generate_next_turn,
        stages_from_plan_json,
    )
    from app.services.interview import mock_runtime_service

    record = _owned_mock_record(db, record_id, current_user.username)
    runtime = mock_runtime_service.get_runtime_for_record(db, interview_record_id=record_id)
    if runtime is None or runtime.status != mock_runtime_service.ACTIVE_STATUS:
        raise HTTPException(status_code=400, detail="该模拟面试不在进行中")
    if not runtime.conversation_id:
        raise HTTPException(status_code=400, detail="模拟面试会话缺失")

    conversation_id = runtime.conversation_id

    stages = stages_from_plan_json(runtime.plan_json)
    prefix = build_prefix(
        record.resume_text_snapshot or "",
        record.jd_text_snapshot or "",
        runtime.interviewer_style,
    )
    # Prior dialog (everything BEFORE this answer) for context. The new answer
    # is passed separately as ``user_answer`` so it isn't double-counted in the
    # prompt — read recent first, then persist the answer.
    recent = _recent_messages(db, conversation_id, limit=8)

    # Persist the candidate's answer. A voice clip (if any) rides along as an
    # audio content block referencing the file asset.
    user_blocks = None
    if body.answer_audio_file_asset_id:
        user_blocks = json.dumps(
            [
                {"type": "text", "text": body.answer_text},
                {"type": "audio", "file_asset_id": body.answer_audio_file_asset_id},
            ],
            ensure_ascii=False,
        )
    _append_message(db, conversation_id, "user", body.answer_text, content_blocks_json=user_blocks)

    try:
        turn = await generate_next_turn(
            prefix=prefix,
            stages=stages,
            current_stage_key=runtime.current_stage_key or stages[0]["key"],
            recent_messages=recent,
            user_answer=body.answer_text,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("mock answer failed for %s: %s", record_id, exc)
        raise HTTPException(status_code=500, detail=humanize_error(exc)) from exc

    assistant_msg = _append_message(db, conversation_id, "assistant", turn.interviewer_message)

    stage_index = next(
        (i for i, s in enumerate(stages) if s["key"] == turn.next_stage_key), runtime.stage_index,
    )
    mock_runtime_service.advance_runtime(
        db,
        runtime,
        current_stage_key=turn.next_stage_key,
        stage_index=stage_index,
        current_question_text=turn.interviewer_message,
        current_question_message_id=assistant_msg.id,
        commit=False,
    )
    await asyncio.to_thread(db.commit)

    return MockAnswerResp(
        interviewer_message=turn.interviewer_message,
        current_stage_key=turn.next_stage_key,
        is_ready_to_finish=turn.is_ready_to_finish,
    )


# ── /finish + /retry-review ────────────────────────────────────────────────


@router.post("/mock-interviews/{record_id}/finish", response_model=MockFinishResp)
@limiter.limit(RATE_EXPENSIVE)
async def finish_mock_interview(
    request: Request,
    response: Response,
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move the record into processing_review and dispatch the review task,
    which parses structured QA from the conversation messages and scores it."""
    from app.services.interview.interview_record_service import (
        STATUS_PROCESSING_REVIEW,
        interview_record_service,
    )
    from app.services.interview import mock_runtime_service
    from app.worker.tasks import process_interview_analysis

    record = _owned_mock_record(db, record_id, current_user.username)
    runtime = mock_runtime_service.get_runtime_for_record(db, interview_record_id=record_id)

    # Require at least one answered turn — an interview with no candidate
    # answers has nothing to review (the FE also gates this, defense in depth).
    if runtime is not None and runtime.conversation_id:
        answered = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.conversation_id == runtime.conversation_id,
                ConversationMessage.role == "user",
            )
            .count()
        )
        if answered == 0:
            raise HTTPException(status_code=400, detail="至少回答一题才能生成复盘")

    record.status = STATUS_PROCESSING_REVIEW
    if runtime is not None:
        mock_runtime_service.set_status(db, runtime, "processing_review", commit=False)
    await asyncio.to_thread(db.commit)

    task = process_interview_analysis.delay(record_id)
    interview_record_service.set_status(
        record_id, STATUS_PROCESSING_REVIEW, celery_task_id=task.id, db=db,
    )
    await asyncio.to_thread(db.commit)

    return MockFinishResp(status="processing_review", record_id=record_id)


@router.post("/mock-interviews/{record_id}/retry-review", response_model=MockRetryReviewResp)
@limiter.limit(RATE_EXPENSIVE)
async def retry_mock_review(
    request: Request,
    response: Response,
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-run review generation from the preserved conversation messages after
    a review_failed (or stuck processing_review)."""
    from app.services.interview.interview_record_service import (
        STATUS_PROCESSING_REVIEW,
        interview_record_service,
    )
    from app.services.interview import mock_runtime_service
    from app.worker.tasks import process_interview_analysis

    record = _owned_mock_record(db, record_id, current_user.username)
    if record.status not in ("review_failed", "processing_review"):
        raise HTTPException(status_code=400, detail="当前状态不可重试复盘")

    runtime = mock_runtime_service.get_runtime_for_record(db, interview_record_id=record_id)
    record.status = STATUS_PROCESSING_REVIEW
    if runtime is not None:
        mock_runtime_service.set_status(db, runtime, "processing_review", commit=False)
    await asyncio.to_thread(db.commit)

    task = process_interview_analysis.delay(record_id)
    interview_record_service.set_status(
        record_id, STATUS_PROCESSING_REVIEW, celery_task_id=task.id, db=db,
    )
    await asyncio.to_thread(db.commit)

    return MockRetryReviewResp(status="processing_review", record_id=record_id)


# ── DELETE (abandon) ───────────────────────────────────────────────────────


@router.delete("/mock-interviews/{record_id}", response_model=MockAbandonResp)
@limiter.limit(RATE_DEFAULT)
async def abandon_mock_interview(
    request: Request,
    response: Response,
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Actively abandon an unfinished mock: delete its conversation + messages,
    runtime, mock audio assets and the draft record (abandon = this never
    happened)."""
    from app.services.interview import mock_runtime_service

    record = _owned_mock_record(db, record_id, current_user.username)
    if record.status != "mock_in_progress":
        raise HTTPException(status_code=400, detail="只能放弃进行中的模拟面试")

    runtime = mock_runtime_service.get_runtime_for_record(db, interview_record_id=record_id)
    conversation_id = runtime.conversation_id if runtime else None
    if conversation_id is None:
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.subject_id == record_id,
                Conversation.type == "mock_interview",
            )
            .first()
        )
        conversation_id = conv.id if conv else None

    try:
        if conversation_id:
            _delete_mock_audio_assets(db, conversation_id, record.user_id)
            db.query(ConversationMessage).filter(
                ConversationMessage.conversation_id == conversation_id
            ).delete(synchronize_session=False)
            db.query(Conversation).filter(
                Conversation.id == conversation_id
            ).delete(synchronize_session=False)
        if runtime is not None:
            db.delete(runtime)
        # interview_qa + any runtime left auto-cascade on the record delete.
        db.delete(record)
        await asyncio.to_thread(db.commit)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("abandon mock failed for %s: %s", record_id, exc)
        raise HTTPException(
            status_code=500, detail=f"放弃失败: {type(exc).__name__}: {exc}",
        ) from exc

    return MockAbandonResp(status="deleted", record_id=record_id)


def _delete_mock_audio_assets(db: Session, conversation_id: str, user_pk: int) -> None:
    """Best-effort: delete file assets referenced by this conversation's
    messages (the mock voice clips). Non-fatal."""
    try:
        from app.models.file_asset import FileAsset

        rows = (
            db.query(ConversationMessage.content_blocks_json)
            .filter(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.content_blocks_json.isnot(None),
            )
            .all()
        )
        asset_ids: set[str] = set()
        for (blocks_json,) in rows:
            try:
                blocks = json.loads(blocks_json) or []
            except (json.JSONDecodeError, TypeError):
                continue
            for b in blocks if isinstance(blocks, list) else []:
                if isinstance(b, dict) and b.get("file_asset_id"):
                    asset_ids.add(str(b["file_asset_id"]))
        if asset_ids:
            db.query(FileAsset).filter(
                FileAsset.id.in_(asset_ids),
                FileAsset.user_id == user_pk,
            ).delete(synchronize_session=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock audio asset cleanup skipped for %s: %s", conversation_id, exc)


# ── /in-progress ───────────────────────────────────────────────────────────


@router.get("/mock-interviews/in-progress", response_model=MockInProgressResp)
@limiter.limit(RATE_DEFAULT)
async def get_in_progress_mock(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resume banner: the user's most recent in-progress mock, from the runtime."""
    from app.services.interview import mock_runtime_service

    runtime = mock_runtime_service.get_active_runtime(db, user_id=current_user.username)
    if runtime is None:
        return MockInProgressResp(has_in_progress=False)

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == runtime.interview_record_id)
        .first()
    )
    title = record.title if record else "模拟面试"
    return MockInProgressResp(
        has_in_progress=True,
        record_id=runtime.interview_record_id,
        conversation_id=runtime.conversation_id,
        runtime_id=runtime.id,
        title=title,
        current_stage_key=runtime.current_stage_key,
        current_question=runtime.current_question_text,
        last_activity_at=(
            runtime.last_activity_at.isoformat() if runtime.last_activity_at else None
        ),
    )


# ── Stateless JD parsing ───────────────────────────────────────────────────


@router.post("/mock-interviews/parse-jd", response_model=MockParseJdResp)
@limiter.limit(RATE_UPLOAD)
async def parse_jd_for_mock(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    _current_user: User = Depends(get_current_user),
):
    """Parse a JD file inline and return its plain text. Does NOT persist."""
    from app.services.uploads.file_validation import validate_upload
    from app.services.voice.file_parser import extract_resume_text

    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="JD 文件过大（限制 10MB）")

    declared_ext = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    contents = await validate_upload(file, purpose="jd", declared_ext=declared_ext)

    with tempfile.NamedTemporaryFile(suffix=declared_ext, delete=False) as tf:
        local_path = tf.name
        tf.write(contents)

    try:
        text = extract_resume_text(local_path) or ""
        return {"text": text, "filename": file.filename, "chars": len(text)}
    except Exception as exc:  # noqa: BLE001
        logger.error("parse_jd_for_mock failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"JD 解析失败: {exc}") from exc
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


# ── Short-clip transcription (MediaRecorder → text) ────────────────────────


@router.post("/mock-interviews/transcribe", response_model=MockTranscribeResp)
@limiter.limit(RATE_EXPENSIVE)
async def transcribe_short_clip(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    language: str = Query("zh", description="Force decode language; 'auto' to detect"),
    current_user: User = Depends(get_current_user),
):
    """Transcribe a short audio clip (webm/opus/mp3/wav) to text."""
    from app.services.uploads.file_validation import validate_upload

    if file.size is not None and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（限制 25MB）")

    contents = await validate_upload(file, purpose="audio_clip")

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
        tf.write(contents)

    try:
        from app.services.voice import audio_transcription_service as ats

        if ats.whisper_model is None:
            try:
                ats.init_whisper_model()
            except Exception as exc:  # noqa: BLE001
                logger.error("WhisperX init failed in transcribe endpoint: %s", exc)
                raise HTTPException(
                    status_code=503, detail="转写模型未就绪，请稍后重试",
                ) from exc

        import whisperx  # type: ignore

        audio = await asyncio.to_thread(whisperx.load_audio, local_path)
        kwargs: dict = {"batch_size": 8}
        if language and language.lower() != "auto":
            kwargs["language"] = language
        result = await asyncio.to_thread(ats.whisper_model.transcribe, audio, **kwargs)
        segments = result.get("segments", []) if isinstance(result, dict) else []
        text = " ".join((seg.get("text", "") or "").strip() for seg in segments).strip()
        detected = result.get("language", "") if isinstance(result, dict) else ""
        duration_sec = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
        logger.info(
            "transcribe ok: user=%s lang=%s duration=%.1fs text_chars=%d",
            current_user.username, detected, duration_sec, len(text),
        )
        return {"text": text, "language": detected, "duration_sec": duration_sec}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Short-clip transcription failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"转写失败: {exc}") from exc
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


# ── TTS ────────────────────────────────────────────────────────────────────


@router.post("/mock-interviews/tts")
@limiter.limit(RATE_EXPENSIVE)
async def synthesize_speech(
    request: Request,
    response: Response,
    body: TTSRequest,
    _current_user: User = Depends(get_current_user),
):
    """Convert text to speech using edge-tts. Returns an mp3 audio stream."""
    from app.services.voice.tts_service import tts_service

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    audio_bytes = await tts_service.synthesize(text=body.text, voice=body.voice)
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio_bytes))},
    )
