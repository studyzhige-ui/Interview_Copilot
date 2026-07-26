"""Mock-interview control endpoints (target architecture, RFC §6.4).

Thin router: auth, request/response mapping, and commit/rollback control.
The run lifecycle (create/answer/finish/abandon) lives in
``services.interview.mock_flow``; LLM planning in ``mock_interview_service``;
runtime rows in ``mock_runtime_service``.

  start         -> create record + conversation + runtime + opening message
  answer        -> append user msg, generate next interviewer line (1 LLM call,
                   no Director/retry), append assistant msg, advance runtime
  finish        -> record -> processing_review, dispatch the review task
  retry-review  -> re-dispatch review from the preserved conversation messages
  DELETE        -> abandon an unfinished run, delete its exclusive data
  in-progress   -> resume banner, sourced from the live runtime row
"""

import asyncio
import logging
import os
import tempfile

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.error_messages import humanize_error
from app.core.rate_limit import RATE_DEFAULT, RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.security import get_current_user
from app.db.database import get_db
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
from app.api.file_assets import require_uploaded
from app.services.interview import mock_flow, mock_runtime_service
from app.services.uploads.file_asset_service import (
    get_owned_file_asset,
    mark_file_asset_consumed,
)
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mock"])


def _owned_mock_record_or_404(
    db: Session, record_id: str, username: str
) -> InterviewRecord:
    record = mock_flow.get_owned_mock_record(db, record_id, username)
    if record is None:
        raise HTTPException(status_code=404, detail="Mock interview not found")
    return record


def _verify_start_upload(
    db: Session,
    file_asset_id: str | None,
    purpose: str,
    noun: str,
    username: str,
) -> None:
    """Ownership + confirm-on-consume gate for an optional start-time upload."""
    if not file_asset_id:
        return
    upload = get_owned_file_asset(
        db,
        file_asset_id=file_asset_id,
        user_id=username,
        purpose=purpose,
    )
    if upload is None:
        raise HTTPException(status_code=404, detail=f"{noun}不存在或无权访问")
    require_uploaded(db, upload, noun)


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
    # Confirm-on-consume (UP-1) for the ad-hoc context uploads. Runs BEFORE
    # start_mock dirties the session — require_uploaded/ensure_uploaded commit
    # internally, which would otherwise break start_mock's one-transaction
    # contract by committing partial state.
    _verify_start_upload(
        db, body.resume_file_asset_id, "resume", "简历文件", current_user.username
    )
    _verify_start_upload(
        db, body.jd_file_asset_id, "jd", "JD 文件", current_user.username
    )
    # MOCK-3: one active run per user — a second /start would orphan the
    # first runtime (invisible to the resume banner once superseded).
    existing = mock_runtime_service.get_active_runtime(
        db, user_id=current_user.username
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="已有进行中的模拟面试，请先继续或放弃它",
        )
    try:
        started = mock_flow.start_mock(
            db,
            username=current_user.username,
            resume_id=body.resume_id,
            resume_file_asset_id=body.resume_file_asset_id,
            jd_text=body.jd_text,
            jd_file_asset_id=body.jd_file_asset_id,
            interviewer_style=body.interviewer_style,
            plan_template_key=body.plan_template_key,
            voice_mode=body.voice_mode,
        )
        await asyncio.to_thread(db.commit)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "mock start failed for user=%s: %s", current_user.username, exc
        )
        raise HTTPException(
            status_code=500,
            detail=f"开始模拟面试失败：{humanize_error(exc)}",
        ) from exc

    plan = started.plan
    return MockStartResp(
        interview_record_id=started.record.id,
        conversation_id=started.conversation.id,
        runtime_id=started.runtime.id,
        current_stage_key=plan.first_stage_key,
        current_question=plan.opening_message,
        question_message_id=started.runtime.current_question_message_id,
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
    record = _owned_mock_record_or_404(db, record_id, current_user.username)
    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )
    if runtime is None or runtime.status != mock_runtime_service.ACTIVE_STATUS:
        raise HTTPException(status_code=400, detail="该模拟面试不在进行中")
    if not runtime.conversation_id:
        raise HTTPException(status_code=400, detail="模拟面试会话缺失")

    # Voice clip: ownership + confirm-on-consume (UP-1), and mark it consumed
    # so the orphan sweeper can never reap a clip a message still references.
    # Verified here (before submit_answer dirties the session) because
    # ensure_uploaded commits internally; mark_file_asset_consumed doesn't
    # commit — it rides submit_answer's transaction below.
    clip = None
    if body.answer_audio_file_asset_id:
        clip = get_owned_file_asset(
            db,
            file_asset_id=body.answer_audio_file_asset_id,
            user_id=current_user.username,
            purpose="mock_audio_clip",
        )
        if clip is None:
            raise HTTPException(status_code=404, detail="语音片段不存在或无权访问")
        require_uploaded(db, clip, "语音片段")

    try:
        if clip is not None:
            mark_file_asset_consumed(db, clip)
        turn = await mock_flow.submit_answer(
            db,
            record=record,
            runtime=runtime,
            answer_text=body.answer_text,
            answer_audio_file_asset_id=body.answer_audio_file_asset_id,
            user_id=current_user.username,
            question_message_id=body.question_message_id,
        )
    except mock_flow.StaleQuestionError as exc:
        # Raised before any write — rollback only clears the (uncommitted)
        # clip consumption from above.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="面试已推进到新问题，请刷新后继续",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Phase A commits internally; this rollback covers a phase-B failure
        # (assistant reply / runtime advance uncommitted). The answer itself
        # survives — the FE retry becomes a deduped 催回应.
        db.rollback()
        logger.exception("mock answer failed for %s: %s", record_id, exc)
        raise HTTPException(status_code=500, detail=humanize_error(exc)) from exc

    # submit_answer commits its own two short transactions (MOCK-4).
    return MockAnswerResp(
        interviewer_message=turn.interviewer_message,
        current_stage_key=turn.next_stage_key,
        is_ready_to_finish=turn.is_ready_to_finish,
        question_message_id=turn.question_message_id,
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
    record = _owned_mock_record_or_404(db, record_id, current_user.username)
    # MOCK-3: only an in-progress run can finish — a double-click or a stale
    # tab must not re-dispatch a review that is already running/done.
    if record.status != STATUS_MOCK_IN_PROGRESS:
        raise HTTPException(
            status_code=409,
            detail="该面试不在进行中（复盘可能已在生成或已完成）",
        )
    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )

    # Require at least one answered turn — an interview with no candidate
    # answers has nothing to review (the FE also gates this, defense in depth).
    if runtime is not None and runtime.conversation_id:
        if mock_flow.count_answered_turns(db, runtime.conversation_id) == 0:
            raise HTTPException(status_code=400, detail="至少回答一题才能生成复盘")

    record.status = STATUS_PROCESSING_REVIEW
    if runtime is not None:
        mock_runtime_service.set_status(
            db, runtime, mock_runtime_service.PROCESSING_STATUS, commit=False
        )
    await asyncio.to_thread(db.commit)

    try:
        await asyncio.to_thread(mock_flow.dispatch_review, db, record_id)
    except Exception as exc:  # noqa: BLE001 — dispatch_review already rolled back
        raise HTTPException(
            status_code=503,
            detail="复盘任务派发失败（任务队列暂不可用），面试内容已保留，请稍后再点一次「结束面试」。",
        ) from exc

    return MockFinishResp(status="processing_review", record_id=record_id)


@router.post(
    "/mock-interviews/{record_id}/retry-review", response_model=MockRetryReviewResp
)
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
    record = _owned_mock_record_or_404(db, record_id, current_user.username)
    if record.status not in (STATUS_REVIEW_FAILED, STATUS_PROCESSING_REVIEW):
        raise HTTPException(status_code=400, detail="当前状态不可重试复盘")

    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )
    record.status = STATUS_PROCESSING_REVIEW
    if runtime is not None:
        mock_runtime_service.set_status(
            db, runtime, mock_runtime_service.PROCESSING_STATUS, commit=False
        )
    await asyncio.to_thread(db.commit)

    try:
        await asyncio.to_thread(
            mock_flow.dispatch_review,
            db,
            record_id,
            rollback_status=STATUS_REVIEW_FAILED,
        )
    except Exception as exc:  # noqa: BLE001 — dispatch_review already rolled back
        raise HTTPException(
            status_code=503,
            detail="复盘任务派发失败（任务队列暂不可用），请稍后重试。",
        ) from exc

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
    record = _owned_mock_record_or_404(db, record_id, current_user.username)
    if record.status != STATUS_MOCK_IN_PROGRESS:
        raise HTTPException(status_code=400, detail="只能放弃进行中的模拟面试")

    runtime = mock_runtime_service.get_runtime_for_record(
        db, interview_record_id=record_id
    )

    try:
        mock_flow.abandon_mock(db, record, runtime)
        await asyncio.to_thread(db.commit)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("abandon mock failed for %s: %s", record_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"放弃失败: {type(exc).__name__}: {exc}",
        ) from exc

    return MockAbandonResp(status="deleted", record_id=record_id)


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
    runtime = mock_runtime_service.get_active_runtime(db, user_id=current_user.username)
    if runtime is None:
        return MockInProgressResp(has_in_progress=False)

    record = (
        db.query(InterviewRecord)
        .filter(InterviewRecord.id == runtime.interview_record_id)
        .first()
    )
    title = record.title if record else "模拟面试"
    # The FE seeds its answeredCount from this — without it, a resumed
    # interview looked like "0 answered" and the finish button stayed
    # disabled until the user answered one more question.
    answered = (
        mock_flow.count_answered_turns(db, runtime.conversation_id)
        if runtime.conversation_id
        else 0
    )
    return MockInProgressResp(
        has_in_progress=True,
        record_id=runtime.interview_record_id,
        conversation_id=runtime.conversation_id,
        runtime_id=runtime.id,
        title=title,
        current_stage_key=runtime.current_stage_key,
        current_question=runtime.current_question_text,
        answered_count=answered,
        question_message_id=runtime.current_question_message_id,
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
    from app.services.uploads.file_validation import read_validated_upload
    from app.services.voice.file_parser import extract_resume_text

    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="JD 文件过大（限制 10MB）")

    declared_ext = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    contents = await read_validated_upload(
        file, purpose="jd", declared_ext=declared_ext
    )

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

# WhisperX's FasterWhisperPipeline.transcribe is NOT thread-safe: it mutates
# self.tokenizer (rebuilt per language, reset to None when no preset) and
# self.options mid-call. Two users answering by voice concurrently would
# race on the shared module-level instance — crash or cross-language
# garbage. Serialise all transcribe calls in this API process. (The celery
# transcription worker runs --pool=solo, so it is naturally serial.)
_whisper_lock = asyncio.Lock()


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
    from app.services.uploads.file_validation import read_validated_upload

    if file.size is not None and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（限制 25MB）")

    contents = await read_validated_upload(file, purpose="audio_clip")

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
        tf.write(contents)

    try:
        # ANA-5: remote-first. When TRANSCRIPTION_PROVIDER resolves to a
        # cloud provider the API process never loads WhisperX (1.5GB model
        # + lock serialization stay out of the request path); the local
        # path below only runs for the local_whisperx provider.
        from app.services.voice import transcription_registry

        try:
            text = await transcription_registry.transcribe_plain(
                local_path,
                language=language,
            )
            logger.info(
                "transcribe ok: provider=remote user=%s lang=%s duration=0.0 text_chars=%d",
                current_user.username,
                language,
                len(text),
            )
            return {"text": text, "language": language or "", "duration_sec": 0.0}
        except transcription_registry.LocalProviderOnly:
            pass  # fall through to the local WhisperX path below
        except RuntimeError as exc:
            # Missing provider env key etc — configuration, not a crash;
            # never leak the raw env-var message to the client.
            logger.error("Short-clip remote transcription unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="转写服务未配置或暂不可用，请稍后重试",
            ) from exc

        from app.services.voice import audio_transcription_service as ats

        if ats.whisper_model is None:
            async with _whisper_lock:
                # Re-check inside the lock — two concurrent first requests
                # must not both load the ~1.5GB model.
                if ats.whisper_model is None:
                    try:
                        await asyncio.to_thread(ats.init_whisper_model)
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "WhisperX init failed in transcribe endpoint: %s", exc
                        )
                        raise HTTPException(
                            status_code=503,
                            detail="转写模型未就绪，请稍后重试",
                        ) from exc

        import whisperx  # type: ignore

        audio = await asyncio.to_thread(whisperx.load_audio, local_path)
        kwargs: dict = {"batch_size": 8}
        if language and language.lower() != "auto":
            kwargs["language"] = language
        async with _whisper_lock:
            result = await asyncio.to_thread(
                ats.whisper_model.transcribe, audio, **kwargs
            )
        segments = result.get("segments", []) if isinstance(result, dict) else []
        text = " ".join((seg.get("text", "") or "").strip() for seg in segments).strip()
        detected = result.get("language", "") if isinstance(result, dict) else ""
        duration_sec = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
        logger.info(
            "transcribe ok: provider=local user=%s lang=%s duration=%.1f text_chars=%d",
            current_user.username,
            detected,
            duration_sec,
            len(text),
        )
        return {"text": text, "language": detected, "duration_sec": duration_sec}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Short-clip transcription failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"转写失败：{humanize_error(exc)}",
        ) from exc
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
