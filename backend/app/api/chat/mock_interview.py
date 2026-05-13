"""Mock-interview control endpoints + TTS."""

import json
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatSession, generate_uuid
from app.models.user import User
from app.schemas.chat import MockAnswerRequest, MockStartRequest, TTSRequest
from app.services.chat.session_state import dump_session_state, parse_session_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


@router.post("/chat/mock-interview/start")
async def start_mock_interview(
    request: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate interview plan and initialize mock interview session."""
    from app.services.mock_interview_service import mock_interview_service
    from app.services.resume_service import resume_service

    session = db.query(ChatSession).filter(
        ChatSession.id == request.session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "mock_interview":
        raise HTTPException(status_code=400, detail="Session is not a mock interview")

    logger.info(
        "mock_start: user=%s session=%s resume=%s jd_upload=%s jd_text_len=%d",
        current_user.username, request.session_id,
        request.resume_upload_id, request.jd_upload_id,
        len(request.jd_text or ""),
    )

    # Load resume context if available. The /upload/resume/direct endpoint
    # only stores the file in S3 — we extract text on demand here.
    resume_context = ""
    if request.resume_upload_id:
        try:
            sections = resume_service.get_sections_by_upload(
                request.resume_upload_id, current_user.username,
            )
            if not sections:
                resume_context = await _parse_resume_on_demand(
                    db, request.resume_upload_id, current_user.username,
                )
            else:
                resume_context = resume_service.format_for_context(sections)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Resume context load failed: %s", exc)
            resume_context = ""
    logger.info("mock_start: resume_context_chars=%d", len(resume_context))

    # Load JD context. Explicit jd_text wins; otherwise resolve from upload id.
    jd_context = (request.jd_text or "").strip()
    if not jd_context and request.jd_upload_id:
        from app.services.knowledge_text_service import load_knowledge_text
        try:
            jd_context = load_knowledge_text(db, request.jd_upload_id, current_user.username)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JD load failed: %s", exc)
            jd_context = ""
    logger.info("mock_start: jd_context_chars=%d", len(jd_context))

    # Structured extraction (one LLM call each). Failures degrade gracefully —
    # the plan generator falls back to a generic, no-grounding prompt.
    resume_evidence: dict = {}
    jd_requirements: dict = {}
    try:
        from app.services.interview.structured_extraction import (
            extract_jd_requirements,
            extract_resume_evidence,
        )
        if resume_context.strip():
            resume_evidence = await extract_resume_evidence(resume_context)
        if jd_context.strip():
            jd_requirements = await extract_jd_requirements(jd_context)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mock_start: structured extraction failed (non-fatal): %s", exc)

    # Generate plan (LLM call — can take 5-15s on cold model)
    try:
        plan = await mock_interview_service.generate_plan(
            resume_context,
            jd_context=jd_context,
            resume_evidence=resume_evidence,
            jd_requirements=jd_requirements,
            interviewer_style=request.interviewer_style,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("mock_start: plan generation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"生成面试计划失败: {type(exc).__name__}: {exc}",
        ) from exc

    # Initialize session state
    state = parse_session_state(session.session_state, "mock_interview")
    state["interview_plan"] = plan
    state["current_phase"] = plan["phases"][0]["phase_id"] if plan.get("phases") else ""
    state["current_question_idx"] = 0
    state["qa_history"] = []
    state["resume_context"] = resume_context[:2000]
    state["jd_context"] = jd_context[:2000]
    state["resume_structured"] = resume_evidence
    state["jd_structured"] = jd_requirements
    state["interviewer_style"] = request.interviewer_style
    state["voice_mode"] = request.voice_mode
    session.session_state = dump_session_state(state)
    db.commit()

    # Get first question
    question_info = mock_interview_service.get_current_question(state, plan)

    return {
        "status": "started",
        "plan_phases": [
            {"phase_id": p["phase_id"], "phase_name": p["phase_name"], "question_count": len(p.get("questions", []))}
            for p in plan.get("phases", [])
        ],
        "current_question": question_info,
    }


@router.get("/chat/mock-interview/in-progress")
async def get_in_progress_mock(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return any mock-interview ChatSession that the user has not finished.

    Used by the MockSetup page to offer a "resume your previous interview"
    option instead of silently starting a fresh one. Returns ``null``-shaped
    payload when there's nothing in flight.
    """
    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.user_id == current_user.username,
            ChatSession.session_type == "mock_interview",
            ChatSession.archived_at.is_(None),
        )
        .order_by(ChatSession.updated_at.desc())
        .first()
    )
    if session is None:
        return {"has_in_progress": False}

    try:
        state = parse_session_state(session.session_state, "mock_interview")
    except Exception:  # noqa: BLE001
        state = {}
    qa_history = state.get("qa_history") or []
    if state.get("is_finished"):
        return {"has_in_progress": False}

    return {
        "has_in_progress": True,
        "session_id": session.id,
        "title": session.title,
        "current_phase": state.get("current_phase"),
        "current_question_idx": state.get("current_question_idx", 0),
        "qa_count": len(qa_history),
        "last_activity_at": session.updated_at.isoformat() if session.updated_at else None,
    }


@router.post("/chat/mock-interview/abandon")
async def abandon_mock_interview(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-archive an in-progress mock session so it stops showing up under
    /mock-interview/in-progress. No InterviewRecord is created."""
    from datetime import datetime as _dt

    session = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.username,
            ChatSession.session_type == "mock_interview",
        )
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session.archived_at = _dt.utcnow()
    db.add(session)
    db.commit()
    return {"status": "abandoned", "session_id": session.id}


@router.get("/chat/mock-interview/question")
async def get_current_question(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the current question for the mock interview."""
    from app.services.mock_interview_service import mock_interview_service

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_session_state(session.session_state, "mock_interview")
    plan = state.get("interview_plan", {})
    return mock_interview_service.get_current_question(state, plan)


@router.post("/chat/mock-interview/answer")
async def submit_mock_answer(
    request: MockAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit an answer, get the interviewer's natural response (no scoring)."""
    from app.services.mock_interview_service import mock_interview_service

    session = db.query(ChatSession).filter(
        ChatSession.id == request.session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_session_state(session.session_state, "mock_interview")
    plan = state.get("interview_plan", {})

    if state.get("is_finished"):
        raise HTTPException(status_code=400, detail="Interview already finished")

    # Get current question
    question_info = mock_interview_service.get_current_question(state, plan)
    if question_info.get("done"):
        raise HTTPException(status_code=400, detail="No more questions")

    # Generate interviewer response (natural, no scoring)
    qa_history = list(state.get("qa_history", []))
    interviewer_result = await mock_interview_service.generate_interviewer_response(
        question=question_info["question"],
        answer=request.answer,
        phase_id=question_info["phase_id"],
        resume_context=state.get("resume_context", ""),
        qa_history=qa_history,
        interviewer_style=state.get("interviewer_style", "professional"),
    )

    # Record Q&A in history, carrying along any grounding_refs the plan
    # attached so we can persist them onto the InterviewQA row at finish time.
    plan_question = _lookup_plan_question(plan, question_info["phase_id"], question_info["question_idx"])
    qa_history.append({
        "phase_id": question_info["phase_id"],
        "question": question_info["question"],
        "answer": request.answer,
        "grounding_refs": list(plan_question.get("grounding_refs") or []) if plan_question else [],
        "is_follow_up": bool(plan_question.get("is_follow_up")) if plan_question else False,
    })
    state["qa_history"] = qa_history

    # Advance state
    state = mock_interview_service.advance_state(state, plan, interviewer_result)
    session.session_state = dump_session_state(state)
    db.commit()

    is_finished = state.get("is_finished", False)

    # Build response text (what the interviewer says)
    response_text = interviewer_result["response"]
    if not is_finished:
        # Append next question to the response
        next_q = mock_interview_service.get_current_question(state, plan)
        if not next_q.get("done") and next_q.get("question"):
            response_text += f"\n\n{next_q['question']}"

    return {
        "interviewer_response": response_text,
        "is_finished": is_finished,
        "phase_progress": {
            "current_phase": state.get("current_phase", ""),
            "question_idx": state.get("current_question_idx", 0),
            "total_answered": len(qa_history),
        },
    }


@router.post("/chat/mock-interview/finish")
async def finish_mock_interview(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """End the mock interview: snapshot the Q&A buffer, create the InterviewRecord
    and a MockInterviewSession archive row, then hand off to the async analysis
    orchestrator. Returns immediately with the new ``record_id`` so the frontend
    can navigate to the review page and watch progress over SSE."""
    from datetime import datetime as _dt

    from app.models.mock_interview_session import MockInterviewSession
    from app.services.interview_record_service import (
        STATUS_ANALYZING,
        interview_record_service,
    )
    from app.worker.tasks import process_interview_analysis

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "mock_interview":
        raise HTTPException(status_code=400, detail="Session is not a mock interview")

    state = parse_session_state(session.session_state, "mock_interview")
    qa_history = state.get("qa_history", []) or []
    if not qa_history:
        raise HTTPException(status_code=400, detail="No Q&A to finish")

    plan_json = json.dumps(state.get("interview_plan", {}), ensure_ascii=False)
    resume_snapshot = state.get("resume_context", "") or ""
    jd_snapshot = state.get("jd_context", "") or ""

    # Persist the canonical InterviewRecord (analysis runs async after this).
    record = interview_record_service.create_for_mock(
        user_id=current_user.username,
        title=session.title or "模拟面试",
        resume_text_snapshot=resume_snapshot,
        jd_text_snapshot=jd_snapshot,
        interview_plan=plan_json,
        db=db,
    )
    # Carry the structured pools onto the record so the orchestrator can reach
    # them via DB without re-extracting.
    resume_structured = state.get("resume_structured") or {}
    jd_structured = state.get("jd_structured") or {}
    if resume_structured or jd_structured:
        from app.models.interview_record import InterviewRecord as _IR
        row = db.query(_IR).filter(_IR.id == record.id).first()
        if row is not None:
            if resume_structured:
                row.resume_structured_json = json.dumps(resume_structured, ensure_ascii=False)
            if jd_structured:
                row.jd_structured_json = json.dumps(jd_structured, ensure_ascii=False)
            db.add(row)

    # Archive the in-progress mock state. The orchestrator reads
    # qa_buffer_json from this row.
    now = _dt.utcnow()
    mis = MockInterviewSession(
        user_id=current_user.username,
        interview_record_id=record.id,
        status="finished",
        current_phase=state.get("current_phase"),
        current_question_idx=int(state.get("current_question_idx", 0) or 0),
        qa_buffer_json=json.dumps(qa_history, ensure_ascii=False),
        plan_snapshot_json=plan_json,
        interviewer_style=state.get("interviewer_style", "professional"),
        voice_mode=state.get("voice_mode", "hybrid"),
        last_activity_at=now,
        archived_at=now,
    )
    db.add(mis)

    # Mark the chat session as finished + archived (soft-delete).
    state["is_finished"] = True
    session.session_state = dump_session_state(state)
    session.archived_at = now

    # Create the debrief chat session so the user can talk to AI about results.
    debrief_session = ChatSession(
        id=generate_uuid(),
        user_id=current_user.username,
        title=f"复盘: {session.title or '模拟面试'}",
        session_type="debrief",
        interview_id=record.id,
        session_state=json.dumps(
            {"mode": "debrief", "interview_id": record.id, "summary": ""},
            ensure_ascii=False,
        ),
    )
    db.add(debrief_session)
    db.commit()

    # Hand off to the unified analysis orchestrator. The same Celery task that
    # processes uploaded audio handles mock records too — it just skips the
    # transcribe/extract stages.
    task = process_interview_analysis.delay(record.id)
    interview_record_service.set_status(
        record.id, STATUS_ANALYZING, celery_task_id=task.id,
    )

    return {
        "status": "analyzing",
        "record_id": record.id,
        "debrief_session_id": debrief_session.id,
        "task_id": task.id,
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _lookup_plan_question(plan: dict, phase_id: str, question_idx: int) -> dict | None:
    """Return the plan-question dict (with grounding_refs) for the given location."""
    for phase in plan.get("phases", []) or []:
        if phase.get("phase_id") == phase_id:
            questions = phase.get("questions") or []
            if 0 <= question_idx < len(questions):
                q = questions[question_idx]
                return q if isinstance(q, dict) else None
            break
    return None


async def _parse_resume_on_demand(db: Session, upload_id: str, user_id: str) -> str:
    """Download the resume file and return its raw text.

    Earlier this also called ``resume_service.extract_and_store`` to LLM-split
    sections + vectorize, but that added 5–30 s to /start and could make the
    whole mock-interview entry time out. The interview plan prompt works fine
    with raw resume text, so we skip the LLM parse here. ResumeSection rows
    can still be populated later by a dedicated background job.
    """
    import os
    import tempfile

    from app.models.upload import UserUpload
    from app.services.storage_service import download_file_from_s3
    from app.services.voice.file_parser import extract_resume_text

    upload = (
        db.query(UserUpload)
        .filter(
            UserUpload.id == upload_id,
            UserUpload.user_id == user_id,
            UserUpload.purpose == "interview_resume",
        )
        .first()
    )
    if upload is None or not upload.storage_uri:
        return ""

    suffix = os.path.splitext(upload.original_filename or "")[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
    try:
        download_file_from_s3(upload.storage_uri, local_path)
        resume_text = extract_resume_text(local_path) or ""
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass

    # Truncate to a reasonable size for the plan prompt (the PLAN_PROMPT uses
    # the whole string verbatim; 6k chars ~ 11k tokens for Chinese is plenty
    # for a 1M-context model).
    return resume_text[:6000]


# ── Stateless JD parsing (no library pollution) ─────────────────────────


@router.post("/chat/mock-interview/parse-jd")
async def parse_jd_for_mock(
    file: UploadFile = File(...),
    _current_user: User = Depends(get_current_user),
):
    """Parse a JD file inline and return its plain text.

    The mock-interview flow needs JD text but should NOT pollute the user's
    personal knowledge library. This endpoint accepts a file, extracts the
    text via the same parser used for resumes, and returns it. Nothing is
    persisted; the temp file is removed on the way out.

    The caller stores the returned text locally and passes it as
    ``MockStartRequest.jd_text``.
    """
    import os
    import tempfile

    from app.services.voice.file_parser import extract_resume_text

    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="JD 文件过大（限制 10MB）")

    suffix = os.path.splitext(file.filename or "")[1] or ".pdf"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
        contents = await file.read()
        tf.write(contents)
    if not contents:
        try: os.unlink(local_path)
        except OSError: pass
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        text = extract_resume_text(local_path) or ""
        return {"text": text, "filename": file.filename, "chars": len(text)}
    except Exception as exc:  # noqa: BLE001
        logger.error("parse_jd_for_mock failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"JD 解析失败: {exc}") from exc
    finally:
        try: os.unlink(local_path)
        except OSError: pass


# ── Short-clip transcription (frontend MediaRecorder → text) ─────────────


@router.post("/chat/mock-interview/transcribe")
async def transcribe_short_clip(
    file: UploadFile = File(...),
    language: str = Query("zh", description="Force decode language; 'auto' to detect"),
    current_user: User = Depends(get_current_user),
):
    """Transcribe a short audio clip (webm/opus/mp3/wav) to text.

    Reuses the WhisperX model loaded by the Celery worker's warmup. Skips
    diarization (single speaker) and language alignment to keep latency low.

    Returns ``{ "text": "...", "language": "zh" }``.
    """
    if file.size is not None and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（限制 25MB）")

    # Persist upload to a temp file so whisperx can mmap it.
    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
        local_path = tf.name
        contents = await file.read()
        tf.write(contents)
    if not contents:
        try:
            os.unlink(local_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="音频内容为空")

    try:
        from app.services.voice import audio_transcription_service as ats

        # Lazy-load if API process has its own WhisperX instance disabled.
        if ats.whisper_model is None:
            try:
                ats.init_whisper_model()
            except Exception as exc:  # noqa: BLE001
                logger.error("WhisperX init failed in transcribe endpoint: %s", exc)
                raise HTTPException(
                    status_code=503,
                    detail="转写模型未就绪，请稍后重试",
                ) from exc

        import whisperx  # type: ignore

        audio = whisperx.load_audio(local_path)
        kwargs: dict = {"batch_size": 8}
        if language and language.lower() != "auto":
            # Pin the decode language. Without this, WhisperX often misdetects
            # short/quiet Chinese clips as "nn" (Norwegian) and returns empty
            # text — visible in earlier logs as "Detected language: nn (0.62)".
            kwargs["language"] = language
        result = ats.whisper_model.transcribe(audio, **kwargs)
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


@router.post("/chat/mock-interview/tts")
async def synthesize_speech(
    request: TTSRequest,
    _current_user: User = Depends(get_current_user),
):
    """Convert text to speech using edge-tts. Returns mp3 audio stream."""
    from app.services.voice.tts_service import tts_service

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    audio_bytes = await tts_service.synthesize(
        text=request.text,
        voice=request.voice,
    )
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio_bytes))},
    )
