"""Mock-interview lifecycle, speech, and context endpoints.

Thin router: auth, request/response mapping, and commit/rollback control.
The run lifecycle (create/answer/finish/abandon) lives in
``services.interview.mock_flow``; LLM planning in ``mock_interview_service``;
runtime rows in ``mock_runtime_service``.

  start         -> create record + conversation + runtime + opening message
  answer        -> append user msg, generate next interviewer line, append it,
                   advance runtime
  finish        -> record -> processing_review, dispatch the review task
  retry-review  -> re-dispatch review from the preserved conversation messages
  DELETE        -> abandon an unfinished run, delete its exclusive data
  in-progress   -> resume banner, sourced from the live runtime row
  live-state    -> authoritative user-facing transcript for resume/recovery
"""

import asyncio
import io
import logging
import os

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.file_assets import require_uploaded
from app.core.error_messages import humanize_error
from app.core.rate_limit import RATE_DEFAULT, RATE_EXPENSIVE, RATE_UPLOAD, limiter
from app.core.runtime_files import create_runtime_temp_file, remove_session_results
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.interview_record import InterviewRecord
from app.models.user import User
from app.schemas.chat import (
    MockAbandonResp,
    MockAnswerAudioResp,
    MockAnswerRequest,
    MockAnswerResp,
    MockFinishResp,
    MockInProgressResp,
    MockLiveMessage,
    MockLiveStateResp,
    MockParseJdResp,
    MockRetryReviewResp,
    MockStartRequest,
    MockStartResp,
    TTSRequest,
)
from app.services.interview import (
    mock_flow,
    mock_interview_service,
    mock_runtime_service,
)
from app.services.interview.interview_record_service import (
    STATUS_MOCK_IN_PROGRESS,
    STATUS_PROCESSING_REVIEW,
    STATUS_REVIEW_FAILED,
)
from app.services.uploads.file_asset_service import (
    get_owned_file_asset,
    mark_file_asset_consumed,
    store_validated_file_asset,
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


# ── /start ───────────────────────────────────────────────────────────────


@router.post("/mock-interviews/start", response_model=MockStartResp)
@limiter.limit(RATE_EXPENSIVE)
def start_mock_interview(
    request: Request,
    response: Response,
    body: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Atomically create the record + conversation + runtime and return the
    opening interviewer line. No pre-created chat session — start owns it."""
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
            jd_text=body.jd_text,
            interviewer_style=body.interviewer_style,
            target_question_count=body.target_question_count,
        )
        db.commit()
    except mock_flow.ResumeNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except mock_flow.ResumeNotReadyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        if (
            mock_runtime_service.get_active_runtime(db, user_id=current_user.username)
            is not None
        ):
            raise HTTPException(
                status_code=409,
                detail="已有进行中的模拟面试，请先继续或放弃它",
            ) from exc
        logger.exception(
            "mock start integrity failure for user=%s", current_user.username
        )
        raise HTTPException(status_code=500, detail="开始模拟面试失败") from exc
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception(
            "mock start failed for user=%s: %s", current_user.username, exc
        )
        raise HTTPException(
            status_code=500,
            detail=f"开始模拟面试失败：{humanize_error(exc)}",
        ) from exc

    return MockStartResp(
        record_id=started.record.id,
        message=MockLiveMessage(
            id=started.runtime.current_question_message_id,
            speaker="interviewer",
            text=started.plan.opening_message,
        ),
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
    if runtime is None:
        raise HTTPException(status_code=400, detail="该模拟面试不在进行中")

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
    except mock_flow.QuestionBusyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="正在生成下一道问题，请勿重复提交",
        ) from exc
    except mock_interview_service.NextTurnGenerationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="你的回答已保存，面试官暂时没有响应",
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
        message=MockLiveMessage(
            id=turn.question_message_id,
            speaker="interviewer",
            text=turn.interviewer_message,
        ),
        end_suggested=turn.is_ready_to_finish,
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

    if runtime is None:
        raise HTTPException(status_code=409, detail="该模拟面试不在进行中")

    # Require at least one answered turn — an interview with no candidate
    # answers has nothing to review (the FE also gates this, defense in depth).
    if mock_flow.count_answered_turns(db, runtime.conversation_id) == 0:
        raise HTTPException(status_code=400, detail="至少回答一题才能生成复盘")
    record.status = STATUS_PROCESSING_REVIEW
    await asyncio.to_thread(db.commit)

    try:
        await asyncio.to_thread(
            mock_flow.dispatch_review,
            db,
            record_id,
            delete_live_runtime=True,
        )
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

    record.status = STATUS_PROCESSING_REVIEW
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
        conversation_id = runtime.conversation_id if runtime else None
        mock_flow.abandon_mock(db, record, runtime)
        await asyncio.to_thread(db.commit)
        if conversation_id:
            remove_session_results(conversation_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("abandon mock failed for %s: %s", record_id, exc)
        raise HTTPException(
            status_code=500,
            detail=humanize_error(exc),
        ) from exc

    return MockAbandonResp(status="deleted", record_id=record_id)


# ── /in-progress ───────────────────────────────────────────────────────────


@router.get("/mock-interviews/in-progress", response_model=MockInProgressResp)
@limiter.limit(RATE_DEFAULT)
def get_in_progress_mock(
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
    return MockInProgressResp(
        has_in_progress=True,
        record_id=runtime.interview_record_id,
        title=title,
        last_activity_at=(
            runtime.last_activity_at.isoformat() if runtime.last_activity_at else None
        ),
    )


@router.get(
    "/mock-interviews/{record_id}/live-state",
    response_model=MockLiveStateResp,
)
@limiter.limit(RATE_DEFAULT)
def get_mock_live_state(
    request: Request,
    response: Response,
    record_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the canonical live transcript for resume and error recovery."""
    _owned_mock_record_or_404(db, record_id, current_user.username)
    runtime = mock_runtime_service.get_runtime_for_record(
        db,
        interview_record_id=record_id,
    )
    if runtime is None:
        raise HTTPException(status_code=409, detail="该模拟面试不在进行中")
    return MockLiveStateResp(
        messages=[
            MockLiveMessage(**message)
            for message in mock_flow.live_messages(db, runtime.conversation_id)
        ]
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
    from app.services.interview.document_text import extract_document_text
    from app.services.uploads.file_validation import read_validated_upload

    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="JD 文件过大（限制 10MB）")

    declared_ext = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    contents = await read_validated_upload(
        file, purpose="jd", declared_ext=declared_ext
    )

    local_path = create_runtime_temp_file(suffix=declared_ext)
    try:
        with open(local_path, "wb") as stream:
            stream.write(contents)
        text = extract_document_text(local_path) or ""
        return {"text": text, "filename": file.filename, "chars": len(text)}
    except Exception as exc:  # noqa: BLE001
        logger.error("parse_jd_for_mock failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="JD 解析失败，请确认文件格式后重试。",
        ) from exc
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


# ── Voice-answer draft (one upload → transcript + saved original) ─────────


@router.post(
    "/mock-interviews/{record_id}/answer-audio",
    response_model=MockAnswerAudioResp,
)
@limiter.limit(RATE_EXPENSIVE)
async def prepare_answer_audio(
    request: Request,
    response: Response,
    record_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Transcribe and keep one recording without a second client upload."""
    from app.services.uploads.file_validation import read_validated_upload
    from app.services.voice.short_clip_transcription import (
        TranscriptionUnavailable,
        transcribe_short_clip,
    )

    record = _owned_mock_record_or_404(db, record_id, current_user.username)
    runtime = mock_runtime_service.get_runtime_for_record(
        db,
        interview_record_id=record.id,
    )
    if runtime is None:
        raise HTTPException(status_code=409, detail="该模拟面试不在进行中")

    if file.size is not None and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（限制 25MB）")

    contents = await read_validated_upload(file, purpose="audio_clip")

    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    local_path = create_runtime_temp_file(suffix=suffix)
    try:
        with open(local_path, "wb") as stream:
            stream.write(contents)
        try:
            text = (await transcribe_short_clip(local_path, language="zh")).strip()
        except TranscriptionUnavailable as exc:
            logger.error("Short-clip transcription unavailable: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="转写服务暂不可用，录音仍保留在当前页面，请稍后重试",
            ) from exc
        if not text:
            raise HTTPException(
                status_code=422,
                detail="没有识别到有效语音，请重新录制或改用文字回答",
            )

        try:
            asset = store_validated_file_asset(
                db,
                user_id=current_user.username,
                filename=file.filename or "answer.webm",
                purpose="mock_audio_clip",
                file_obj=io.BytesIO(contents),
                content_type=file.content_type or "audio/webm",
                size_bytes=len(contents),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Short-clip storage failed: %s", exc)
            raise HTTPException(
                status_code=503,
                detail="原声保存失败，录音仍保留在当前页面，请稍后重试",
            ) from exc

        logger.info(
            "Prepared mock answer audio: user=%s record=%s text_chars=%d asset=%s",
            current_user.username,
            record_id,
            len(text),
            asset.id,
        )
        return {"text": text, "audio_file_asset_id": asset.id}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Preparing mock answer audio failed: %s", exc)
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
