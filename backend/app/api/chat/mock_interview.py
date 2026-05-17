"""Mock-interview control endpoints + TTS.

v6 chain (Runtime Director):
  start    -> generate_brief (LLM #1) builds the cacheable prefix + map + opening
  answer   -> run_director  (LLM #2) decides this turn (with up to MAX_DIRECTOR_RETRIES)
              -> every SUMMARY_EVERY_N_TURNS the older history is summarised (LLM #3)
  finish   -> snapshot state -> dispatch InterviewAnalysisOrchestrator (Celery)
"""

import json
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile

from app.core.rate_limit import RATE_EXPENSIVE, RATE_UPLOAD, limiter
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


# ── /start ─────────────────────────────────────────────────────────────


@router.post("/chat/mock-interview/start")
async def start_mock_interview(
    request: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Initialise the Runtime Director session: load resume+JD, ask the LLM
    to build a thin interview map + opening line, freeze the cacheable prefix
    into state, and return the opening to the frontend."""
    from app.services.mock_interview_service import (
        DEFAULT_TURN_BUDGETS,
        VALID_PHASES,
        build_prefix,
        generate_brief,
        prefix_hash,
    )
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
        "mock_start: user=%s session=%s resume=%s jd_upload=%s jd_text_len=%d style=%s voice=%s",
        current_user.username, request.session_id,
        request.resume_upload_id, request.jd_upload_id,
        len(request.jd_text or ""),
        request.interviewer_style, request.voice_mode,
    )

    # Load resume text. /upload/resume/direct only stores the file; we extract
    # on demand here.
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

    jd_context = (request.jd_text or "").strip()
    if not jd_context and request.jd_upload_id:
        from app.services.knowledge_text_service import load_knowledge_text
        try:
            jd_context = load_knowledge_text(db, request.jd_upload_id, current_user.username)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JD load failed: %s", exc)
            jd_context = ""
    logger.info("mock_start: jd_context_chars=%d", len(jd_context))

    # Build the cacheable prefix *once* and stash it in session_state. Every
    # subsequent LLM call this session reuses it verbatim so DeepSeek's
    # prompt cache can hit on it.
    cacheable_prefix = build_prefix(resume_context, jd_context, request.interviewer_style)

    # LLM #1: interview brief + opening
    try:
        brief = await generate_brief(
            resume_context=resume_context,
            jd_context=jd_context,
            interviewer_style=request.interviewer_style,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("mock_start: brief generation failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"生成面试地图失败: {type(exc).__name__}: {exc}",
        ) from exc

    # Initial state machine
    state = parse_session_state(session.session_state, "mock_interview")
    state.update({
        "schema_version": 2,
        "resume_context": resume_context,
        "jd_context": jd_context,
        "interviewer_style": request.interviewer_style,
        "voice_mode": request.voice_mode,

        "cacheable_prefix": cacheable_prefix,
        "prefix_hash": prefix_hash(cacheable_prefix),

        "interview_plan": brief.interview_plan,
        "current_phase": "self_intro",
        "current_topic": "self_intro",
        "phase_progress": {p: 0 for p in VALID_PHASES},
        "follow_up_depth": 0,

        "pending_response": brief.opening_spoken,
        "pending_question": brief.opening_question,

        "qa_history": [],
        "qa_history_summary": "",

        "covered_topics": [],
        "weak_topics": [],
        "strong_topics": [],

        "min_turns": brief.min_turns,
        "target_turns": brief.target_turns,
        "max_turns": brief.max_turns,
        "turn_count": 0,
        "reverse_qa_prompted": False,
        "is_finished": False,
    })
    session.session_state = dump_session_state(state)
    db.commit()

    plan_phases = [
        {
            "phase_id": ph["phase"],
            "phase_name": _PHASE_NAME_MAP.get(ph["phase"], ph["phase"]),
            "question_count": int(ph.get("budget") or 1),
        }
        for ph in brief.interview_plan.get("phases", [])
    ]

    return {
        "status": "started",
        "plan_phases": plan_phases,
        "current_question": {
            "done": False,
            "phase_id": "self_intro",
            "phase_name": _PHASE_NAME_MAP.get("self_intro", "self_intro"),
            "question_idx": 0,
            "total_questions_in_phase": next(
                (p.get("budget") for p in brief.interview_plan.get("phases", []) if p.get("phase") == "self_intro"),
                1,
            ),
            "question": brief.opening_question,
            "spoken_response": brief.opening_spoken,
        },
    }


_PHASE_NAME_MAP = {
    "self_intro": "自我介绍",
    "resume_deep_dive": "项目深挖",
    "technical": "技术深度",
    "behavioral": "行为面试",
    "reverse_qa": "反问环节",
}


# ── /in-progress + /abandon ────────────────────────────────────────────


@router.get("/chat/mock-interview/in-progress")
async def get_in_progress_mock(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user's most recent unfinished mock-interview, if any.

    Sweeps any stale "shell" sessions (created but never produced a Q&A —
    e.g. plan generation failed, user closed the tab mid-startup) before
    answering, so the resume banner never shows for sessions that have no
    real content to recover.
    """
    from app.models.chat import ChatMessage
    from app.models.interview_record import InterviewRecord

    candidates = (
        db.query(ChatSession)
        .filter(
            ChatSession.user_id == current_user.username,
            ChatSession.session_type == "mock_interview",
            ChatSession.archived_at.is_(None),
        )
        .order_by(ChatSession.updated_at.desc())
        .all()
    )

    chosen: ChatSession | None = None
    purged = 0
    for sess in candidates:
        try:
            state = parse_session_state(sess.session_state, "mock_interview") or {}
        except Exception:  # noqa: BLE001
            state = {}
        qa_history = state.get("qa_history") or []
        is_finished = bool(state.get("is_finished"))

        # Stale shell: no Q&A AND not actively marked finished. Hard-delete it
        # along with its chat messages + any draft InterviewRecord so it
        # doesn't keep haunting the resume banner.
        if not qa_history and not is_finished:
            record_id = state.get("interview_record_id") or sess.interview_id
            if record_id:
                (
                    db.query(InterviewRecord)
                    .filter(
                        InterviewRecord.id == record_id,
                        InterviewRecord.user_id == current_user.username,
                    )
                    .delete(synchronize_session=False)
                )
            db.query(ChatMessage).filter(ChatMessage.session_id == sess.id).delete(
                synchronize_session=False
            )
            db.delete(sess)
            purged += 1
            continue

        if is_finished:
            continue

        # First non-finished session with real Q&A is the one we surface.
        if chosen is None:
            chosen = sess

    if purged:
        db.commit()
        logger.info("Purged %d stale empty mock_interview shell(s) for user=%s", purged, current_user.username)

    if chosen is None:
        return {"has_in_progress": False}

    try:
        state = parse_session_state(chosen.session_state, "mock_interview") or {}
    except Exception:  # noqa: BLE001
        state = {}
    qa_history = state.get("qa_history") or []

    return {
        "has_in_progress": True,
        "session_id": chosen.id,
        "title": chosen.title,
        "current_phase": state.get("current_phase"),
        "current_question_idx": int(state.get("turn_count", len(qa_history)) or 0),
        "qa_count": len(qa_history),
        "last_activity_at": chosen.updated_at.isoformat() if chosen.updated_at else None,
    }


@router.post("/chat/mock-interview/abandon")
async def abandon_mock_interview(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard-delete an in-progress mock session (+ any draft record / chat
    messages). Per user spec, abandon means "this never happened"."""
    from app.models.chat import ChatMessage
    from app.models.interview_record import InterviewRecord

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

    try:
        state = parse_session_state(session.session_state, "mock_interview")
        record_id = state.get("interview_record_id") or session.interview_id
        if record_id:
            (
                db.query(InterviewRecord)
                .filter(
                    InterviewRecord.id == record_id,
                    InterviewRecord.user_id == current_user.username,
                )
                .delete(synchronize_session=False)
            )

        db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).delete(synchronize_session=False)

        db.delete(session)
        db.commit()
        return {"status": "deleted", "session_id": session_id}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("abandon_mock_interview failed for %s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"放弃失败: {type(exc).__name__}: {exc}",
        ) from exc


# ── /question ──────────────────────────────────────────────────────────


@router.get("/chat/mock-interview/question")
async def get_current_question(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return what the interviewer is currently waiting on. Backed by
    ``state.pending_question`` + ``state.pending_response`` — no LLM call."""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_session_state(session.session_state, "mock_interview")
    _require_v2_schema(state)
    if state.get("is_finished"):
        return {"done": True, "message": "面试已完成"}

    return {
        "done": False,
        "phase_id": state.get("current_phase", "self_intro"),
        "phase_name": _PHASE_NAME_MAP.get(state.get("current_phase", ""), ""),
        "question_idx": int(state.get("turn_count", 0)),
        "total_questions_in_phase": _phase_budget(state, state.get("current_phase", "")),
        "question": state.get("pending_question") or "",
        "spoken_response": state.get("pending_response") or "",
    }


# ── /answer ────────────────────────────────────────────────────────────


@router.post("/chat/mock-interview/answer")
@limiter.limit(RATE_EXPENSIVE)
async def submit_mock_answer(
    request: Request,
    response: Response,
    body: MockAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Drive one turn through the Runtime Director.

    State-machine write order is critical (v6 fix):
      1. Snapshot `answered_phase` / `answered_topic` from CURRENT state.
      2. Append the freshly-finished QA to qa_history under THOSE labels.
      3. Increment `phase_progress[answered_phase]` (the phase that was just
         answered — NOT the LLM's `result.phase`, which is the NEXT phase).
      4. Only AFTER that, swap pending_* / current_* to the next turn.
    """
    from app.services.mock_interview_service import (
        DISPLAY_INTENT,
        MAX_FOLLOW_UP_DEPTH,
        SUMMARY_EVERY_N_TURNS,
        DirectorRetryExhausted,
        apply_state_update,
        normalize_topic,
        run_director,
        summarize_history,
    )

    session = db.query(ChatSession).filter(
        ChatSession.id == body.session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_session_state(session.session_state, "mock_interview")
    _require_v2_schema(state)

    if state.get("is_finished"):
        raise HTTPException(status_code=400, detail="Interview already finished")

    # turn_count tracks the answer we just received. Increment *before*
    # calling director so V4 (max_turns guard) sees the correct count.
    state["turn_count"] = int(state.get("turn_count", 0)) + 1

    # LLM #2 (Runtime Director, with retry)
    try:
        result = await run_director(state, body.answer)
    except DirectorRetryExhausted as exc:
        logger.warning(
            "Director retries exhausted for session %s: %s",
            body.session_id, exc.last_violation,
        )
        # Roll the turn counter back so the user can retry without it being
        # counted twice toward max_turns.
        state["turn_count"] = max(0, int(state.get("turn_count", 1)) - 1)
        session.session_state = dump_session_state(state)
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="面试官暂时无法回应，请重试。",
        ) from exc

    # ── State machine writes (strict order) ────────────────────────────
    answered_phase = state.get("current_phase") or "self_intro"
    answered_topic = state.get("current_topic") or normalize_topic(answered_phase)

    qa_entry = {
        "spoken_response": state.get("pending_response") or "",
        "question": state.get("pending_question") or "",
        "answer": body.answer,
        "phase": answered_phase,
        "topic": answered_topic,
        "action": result.action,
        "answer_quality": {
            "level": result.answer_quality.level,
            "reason": result.answer_quality.reason,
        },
    }
    qa_history = list(state.get("qa_history") or [])
    qa_history.append(qa_entry)
    state["qa_history"] = qa_history

    progress = dict(state.get("phase_progress") or {})
    progress[answered_phase] = int(progress.get(answered_phase, 0)) + 1
    state["phase_progress"] = progress

    # Switch to next turn
    state["pending_response"] = result.spoken_response
    state["pending_question"] = result.next_question
    state["current_phase"] = result.phase
    state["current_topic"] = normalize_topic(result.topic) or normalize_topic(result.phase)
    state["follow_up_depth"] = (
        int(state.get("follow_up_depth", 0)) + 1
        if result.action == "follow_up"
        else 0
    )

    apply_state_update(state, result.state_update)
    if result.phase == "reverse_qa":
        state["reverse_qa_prompted"] = True
    if result.should_finish:
        state["is_finished"] = True

    # LLM #3 (rolling summary, every N turns; non-fatal on failure)
    turn_count = state["turn_count"]
    if turn_count > 0 and turn_count % SUMMARY_EVERY_N_TURNS == 0:
        try:
            state["qa_history_summary"] = await summarize_history(state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Rolling summary failed (non-fatal): %s", exc)

    session.session_state = dump_session_state(state)
    db.commit()

    # The frontend ``interviewer_response`` field stays as one string for
    # backward compat (TTS reads it). The new fields let the UI eventually
    # render the承接 / next-question split distinctly.
    speech_chunks = [result.spoken_response]
    if result.next_question:
        speech_chunks.append(result.next_question)
    interviewer_response = "\n\n".join(s for s in speech_chunks if s).strip()

    return {
        "interviewer_response": interviewer_response,
        "spoken_response": result.spoken_response,
        "next_question": result.next_question,
        "action": result.action,
        "display_intent": DISPLAY_INTENT.get(result.action, result.action),
        "is_finished": state["is_finished"],
        "phase_progress": {
            "current_phase": state["current_phase"],
            "turn_count": state["turn_count"],
            "max_turns": int(state.get("max_turns", 14)),
            "follow_up_depth": int(state.get("follow_up_depth", 0)),
        },
    }


# ── /finish ────────────────────────────────────────────────────────────


@router.post("/chat/mock-interview/finish")
async def finish_mock_interview(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Snapshot the in-flight state, create the InterviewRecord +
    MockInterviewSession, then dispatch the unified analysis orchestrator."""
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
    _require_v2_schema(state)
    qa_history = state.get("qa_history", []) or []
    if not qa_history:
        raise HTTPException(status_code=400, detail="No Q&A to finish")

    plan_json = json.dumps(state.get("interview_plan", {}), ensure_ascii=False)
    resume_snapshot = state.get("resume_context", "") or ""
    jd_snapshot = state.get("jd_context", "") or ""

    record = interview_record_service.create_for_mock(
        user_id=current_user.username,
        title=session.title or "模拟面试",
        resume_text_snapshot=resume_snapshot,
        jd_text_snapshot=jd_snapshot,
        interview_plan=plan_json,
        db=db,
    )

    now = _dt.utcnow()
    mis = MockInterviewSession(
        user_id=current_user.username,
        interview_record_id=record.id,
        status="finished",
        current_phase=state.get("current_phase"),
        current_question_idx=int(state.get("turn_count", 0) or 0),
        qa_buffer_json=json.dumps(qa_history, ensure_ascii=False),
        plan_snapshot_json=plan_json,
        interviewer_style=state.get("interviewer_style", "professional"),
        voice_mode=state.get("voice_mode", "hybrid"),
        last_activity_at=now,
        archived_at=now,
    )
    db.add(mis)

    state["is_finished"] = True
    session.session_state = dump_session_state(state)
    session.archived_at = now

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


# ── Helpers ────────────────────────────────────────────────────────────


def _require_v2_schema(state: dict) -> None:
    """Reject sessions whose state was produced by the pre-v6 plan-based
    pipeline. Old shapes have ``interview_plan`` keyed phases but no
    ``cacheable_prefix`` / ``pending_question``. The cleanest UX is to make
    the user re-start instead of patching a broken state on the fly."""
    if int(state.get("schema_version", 0) or 0) >= 2:
        return
    raise HTTPException(
        status_code=410,
        detail="此模拟面试由旧版本创建，无法继续。请放弃后重新开始。",
    )


def _phase_budget(state: dict, phase: str) -> int:
    for ph in (state.get("interview_plan") or {}).get("phases", []):
        if isinstance(ph, dict) and ph.get("phase") == phase:
            try:
                return int(ph.get("budget") or 1)
            except (TypeError, ValueError):
                return 1
    return 1


async def _parse_resume_on_demand(db: Session, upload_id: str, user_id: str) -> str:
    """Download a resume upload (or knowledge_document) and return its plain
    text, truncated."""
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
            UserUpload.purpose.in_(("interview_resume", "knowledge_document")),
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

    return resume_text[:8000]


# ── Stateless JD parsing ───────────────────────────────────────────────


@router.post("/chat/mock-interview/parse-jd")
async def parse_jd_for_mock(
    file: UploadFile = File(...),
    _current_user: User = Depends(get_current_user),
):
    """Parse a JD file inline and return its plain text. Does NOT persist."""
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


# ── Short-clip transcription (MediaRecorder → text) ────────────────────


@router.post("/chat/mock-interview/transcribe")
@limiter.limit(RATE_EXPENSIVE)
async def transcribe_short_clip(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    language: str = Query("zh", description="Force decode language; 'auto' to detect"),
    current_user: User = Depends(get_current_user),
):
    """Transcribe a short audio clip (webm/opus/mp3/wav) to text."""
    if file.size is not None and file.size > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="音频过大（限制 25MB）")

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


# ── TTS ────────────────────────────────────────────────────────────────


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
