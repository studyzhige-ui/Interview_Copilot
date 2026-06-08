"""Mock-interview control endpoints + TTS.

v6 chain (Runtime Director):
  start    -> generate_brief (LLM #1) builds the cacheable prefix + map + opening
  answer   -> run_director  (LLM #2) decides this turn (with up to MAX_DIRECTOR_RETRIES)
              -> every SUMMARY_EVERY_N_TURNS the older history is summarised (LLM #3)
  finish   -> snapshot state -> dispatch InterviewAnalysisOrchestrator (Celery)
"""

import asyncio
import time
import json
import logging
import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile

from app.core.rate_limit import RATE_DEFAULT, RATE_EXPENSIVE, RATE_UPLOAD, limiter
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.error_messages import humanize_error
from app.core.security import get_current_user
from app.core.user_identity import resolve_user_pk
from app.db.database import get_db
from app.models.chat import ChatSession, generate_uuid
from app.models.user import User
from app.schemas.chat import (
    MockAbandonResp,
    MockAnswerRequest,
    MockAnswerResp,
    MockFinishResp,
    MockInProgressResp,
    MockParseJdResp,
    MockQuestion,
    MockStartRequest,
    MockStartResp,
    MockTranscribeResp,
    TTSRequest,
)
from app.services.chat.mock_interview_state import dump_mock_state, parse_mock_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ── /start ─────────────────────────────────────────────────────────────


@router.post("/chat/mock-interview/start", response_model=MockStartResp)
@limiter.limit(RATE_EXPENSIVE)
async def start_mock_interview(
    request: Request,
    response: Response,
    body: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Initialise the Runtime Director session: load resume+JD, ask the LLM
    to build a thin interview map + opening line, freeze the cacheable prefix
    into state, and return the opening to the frontend."""
    from app.services.interview.mock_interview_service import (
        VALID_PHASES,
        build_prefix,
        generate_brief,
        prefix_hash,
    )
    from app.services.resume.resume_service import resume_service

    session = db.query(ChatSession).filter(
        ChatSession.id == body.session_id,
        ChatSession.user_id == resolve_user_pk(db, current_user.username),
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "mock_interview":
        raise HTTPException(status_code=400, detail="Session is not a mock interview")

    # Per-phase timing is captured so the "why is mock start slow"
    # question has a real answer in the logs. The chain has exactly
    # ONE LLM call (generate_brief) — anything beyond that is local
    # work (S3 download, PDF parse, DB commit). When users report
    # slowness, we look at this log line first.
    #
    # Single ``mock_start_timing`` line is emitted only on the
    # success path (after commit). On the error path the exception
    # already includes ``logger.exception`` with the failing phase,
    # so we don't double-log a partial timing breakdown that would
    # just confuse readers.
    _t_marks: dict[str, float] = {}

    def _mark(label: str) -> None:
        _t_marks[label] = time.perf_counter()

    def _ms(label_from: str, label_to: str) -> float:
        # ``%.1f`` in the log format truncates display precision;
        # no need to round here.
        return (_t_marks[label_to] - _t_marks[label_from]) * 1000

    _mark("begin")

    logger.info(
        "mock_start: user=%s session=%s resume=%s jd_upload=%s jd_text_len=%d style=%s voice=%s",
        current_user.username, body.session_id,
        body.resume_upload_id, body.jd_upload_id,
        len(body.jd_text or ""),
        body.interviewer_style, body.voice_mode,
    )

    # Resume text resolution. Three tiers, fastest first:
    #
    #   1. ``resume_sections`` — the dedicated structured-parsing table
    #      used by older flows. Hot when present.
    #
    #   2. ``document_chunks`` — when the resume was added to the
    #      library, ingestion ALREADY parsed the PDF into chunks (in
    #      Postgres ``document_chunks``). We just read them back and
    #      concatenate — no S3 round-trip, no LlamaParse call.
    #      Resolves in ~5-50 ms.
    #
    #   3. ``_parse_resume_on_demand`` — last-resort cold path. S3
    #      download + LlamaParse fresh parse. The historical default,
    #      which is why mock_start used to take 8-10 seconds on every
    #      fresh resume (the LlamaParse round-trip alone is 7-8 s on
    #      a typical 2-page CV). Now only fires when the upload has
    #      neither parsed sections NOR a library row.
    #
    # **Tier order is load-bearing** — sections > chunks > reparse.
    # A future contributor swapping these will silently regress mock
    # interview quality (sections are structured/cleaned; chunks are
    # raw concatenated text). The helper-level pieces are pinned by
    # ``tests/test_services/test_knowledge_text_service.py`` (chunks
    # priority over reparse) but the THIS-FILE wiring is verified by
    # hand right now — add an integration test if you change this
    # block.
    resume_context = ""
    resume_source = "none"
    if body.resume_upload_id:
        try:
            sections = resume_service.get_sections_by_upload(
                body.resume_upload_id, current_user.username,
            )
            if sections:
                resume_context = resume_service.format_for_context(sections)
                resume_source = "sections"
            else:
                from app.services.knowledge.knowledge_text_service import (
                    find_knowledge_doc_by_upload,
                    read_full_text_from_chunks,
                )
                kdoc = find_knowledge_doc_by_upload(
                    db, body.resume_upload_id, current_user.username,
                )
                if kdoc is not None:
                    text, node_count = read_full_text_from_chunks(kdoc)
                    if node_count > 0:
                        resume_context = text
                        resume_source = "chunks"
                if not resume_context:
                    resume_context = await _parse_resume_on_demand(
                        db, body.resume_upload_id, current_user.username,
                    )
                    resume_source = "reparsed" if resume_context else "none"
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Resume context load failed (tier reached=%s): %s",
                resume_source, exc,
            )
            resume_context = ""
    _mark("resume_done")
    logger.info(
        "mock_start: resume_context_chars=%d source=%s",
        len(resume_context), resume_source,
    )

    jd_context = (body.jd_text or "").strip()
    if not jd_context and body.jd_upload_id:
        from app.services.knowledge.knowledge_text_service import load_knowledge_text
        try:
            jd_context = load_knowledge_text(db, body.jd_upload_id, current_user.username)
        except Exception as exc:  # noqa: BLE001
            logger.warning("JD load failed: %s", exc)
            jd_context = ""
    _mark("jd_done")
    logger.info("mock_start: jd_context_chars=%d", len(jd_context))

    # Build the cacheable prefix *once* and stash it in mock_interview_state. Every
    # subsequent LLM call this session reuses it verbatim so DeepSeek's
    # prompt cache can hit on it.
    cacheable_prefix = build_prefix(resume_context, jd_context, body.interviewer_style)
    _mark("prefix_done")

    # LLM #1 (the ONLY LLM call in this endpoint): interview brief + opening.
    try:
        brief = await generate_brief(
            resume_context=resume_context,
            jd_context=jd_context,
            interviewer_style=body.interviewer_style,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("mock_start: brief generation failed: %s", exc)
        # Humanize so a model-side failure (e.g. 402 balance) tells the user
        # what to fix, instead of leaking ``APIStatusError: Error code: 402``.
        # Full detail still goes to the log above.
        raise HTTPException(
            status_code=500,
            detail=f"开始模拟面试失败：{humanize_error(exc)}",
        ) from exc
    _mark("brief_done")

    # Initial state machine
    state = parse_mock_state(session.mock_interview_state)
    state.update({
        "schema_version": 2,
        "resume_context": resume_context,
        "jd_context": jd_context,
        "interviewer_style": body.interviewer_style,
        "voice_mode": body.voice_mode,

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
    session.mock_interview_state = dump_mock_state(state)
    # Wrap sync commit in to_thread so the event loop isn't blocked on the
    # network round-trip to Postgres (every other in-flight request would
    # stall otherwise).
    await asyncio.to_thread(db.commit)
    _mark("commit_done")

    # Phase-by-phase latency. Use a single log line so log scrapers can
    # ingest it as one event. Whenever a user reports "mock start is
    # slow", grep this and the biggest field is the answer.
    logger.info(
        "mock_start_timing: total=%.1fms resume=%.1fms (source=%s) "
        "jd=%.1fms prefix=%.1fms brief_llm=%.1fms commit=%.1fms",
        _ms("begin", "commit_done"),
        _ms("begin", "resume_done"), resume_source,
        _ms("resume_done", "jd_done"),
        _ms("jd_done", "prefix_done"),
        _ms("prefix_done", "brief_done"),
        _ms("brief_done", "commit_done"),
    )

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


@router.get("/chat/mock-interview/in-progress", response_model=MockInProgressResp)
@limiter.limit(RATE_DEFAULT)
async def get_in_progress_mock(
    request: Request,
    response: Response,
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
            ChatSession.user_id == resolve_user_pk(db, current_user.username),
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
            state = parse_mock_state(sess.mock_interview_state) or {}
        except Exception:  # noqa: BLE001
            state = {}
        qa_history = state.get("qa_history") or []
        is_finished = bool(state.get("is_finished"))

        # "Has the brief LLM call ever completed for this session?"
        # A successful ``start_mock_interview`` writes ``interview_plan``
        # + ``pending_question`` (the opening line) into mock_interview_state.
        # If neither exists, the session is a stale shell — created
        # but never actually launched (plan generation failed, user
        # closed the tab mid-startup, etc.).
        #
        # CRITICAL: we cannot use ``qa_history`` alone as the
        # liveness signal. ``qa_history`` only fills in once the
        # user ANSWERS the first question. A user who started a
        # mock, saw the opening prompt "请简单做个自我介绍" and
        # then switched tabs would have ``qa_history=[]`` but a
        # fully valid in-progress session — pre-fix this very page
        # would silently hard-delete that session under them, and
        # the resume banner never appeared because the candidate
        # row was gone by the time the banner queried.
        brief_launched = bool(state.get("interview_plan")) or bool(
            state.get("pending_question")
        )

        if not qa_history and not is_finished and not brief_launched:
            record_id = state.get("interview_record_id") or sess.interview_id
            if record_id:
                (
                    db.query(InterviewRecord)
                    .filter(
                        InterviewRecord.id == record_id,
                        InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
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

        # First non-finished session with a launched brief (regardless
        # of whether the user answered anything yet) is the one we
        # surface for resume.
        if chosen is None:
            chosen = sess

    if purged:
        await asyncio.to_thread(db.commit)
        logger.info("Purged %d stale empty mock_interview shell(s) for user=%s", purged, current_user.username)

    if chosen is None:
        return {"has_in_progress": False}

    try:
        state = parse_mock_state(chosen.mock_interview_state) or {}
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


@router.post("/chat/mock-interview/abandon", response_model=MockAbandonResp)
@limiter.limit(RATE_DEFAULT)
async def abandon_mock_interview(
    request: Request,
    response: Response,
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
            ChatSession.user_id == resolve_user_pk(db, current_user.username),
            ChatSession.session_type == "mock_interview",
        )
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        state = parse_mock_state(session.mock_interview_state)
        record_id = state.get("interview_record_id") or session.interview_id
        if record_id:
            (
                db.query(InterviewRecord)
                .filter(
                    InterviewRecord.id == record_id,
                    InterviewRecord.user_id == resolve_user_pk(db, current_user.username),
                )
                .delete(synchronize_session=False)
            )

        db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).delete(synchronize_session=False)

        db.delete(session)
        await asyncio.to_thread(db.commit)
        return {"status": "deleted", "session_id": session_id}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("abandon_mock_interview failed for %s: %s", session_id, exc)
        raise HTTPException(
            status_code=500,
            detail=f"放弃失败: {type(exc).__name__}: {exc}",
        ) from exc


# ── /question ──────────────────────────────────────────────────────────


@router.get("/chat/mock-interview/question", response_model=MockQuestion)
@limiter.limit(RATE_DEFAULT)
async def get_current_question(
    request: Request,
    response: Response,
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return what the interviewer is currently waiting on. Backed by
    ``state.pending_question`` + ``state.pending_response`` — no LLM call."""
    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == resolve_user_pk(db, current_user.username),
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_mock_state(session.mock_interview_state)
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


@router.post("/chat/mock-interview/answer", response_model=MockAnswerResp)
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
    from app.services.interview.mock_interview_service import (
        DISPLAY_INTENT,
        SUMMARY_EVERY_N_TURNS,
        DirectorRetryExhausted,
        apply_state_update,
        normalize_topic,
        run_director,
        summarize_history,
    )

    session = db.query(ChatSession).filter(
        ChatSession.id == body.session_id,
        ChatSession.user_id == resolve_user_pk(db, current_user.username),
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_mock_state(session.mock_interview_state)
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
        session.mock_interview_state = dump_mock_state(state)
        await asyncio.to_thread(db.commit)
        raise HTTPException(
            status_code=503,
            detail="面试官暂时无法回应，请重试。",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        # Safety net: an unexpected director failure (e.g. a 402 balance
        # error that propagated instead of being retried as a violation)
        # would otherwise surface as a bare 500. Roll the turn counter back
        # like the retry path, and humanize so the user gets an actionable
        # reason instead of a generic "internal error".
        logger.exception(
            "next-question director failed for %s: %s", body.session_id, exc,
        )
        state["turn_count"] = max(0, int(state.get("turn_count", 1)) - 1)
        session.mock_interview_state = dump_mock_state(state)
        await asyncio.to_thread(db.commit)
        raise HTTPException(status_code=500, detail=humanize_error(exc)) from exc

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

    session.mock_interview_state = dump_mock_state(state)
    await asyncio.to_thread(db.commit)

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


@router.post("/chat/mock-interview/finish", response_model=MockFinishResp)
@limiter.limit(RATE_EXPENSIVE)
async def finish_mock_interview(
    request: Request,
    response: Response,
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Snapshot the in-flight state, create the InterviewRecord +
    MockInterviewSession, then dispatch the unified analysis orchestrator."""
    from datetime import datetime as _dt

    from app.models.mock_interview_session import MockInterviewSession
    from app.services.interview.interview_record_service import (
        STATUS_ANALYZING,
        interview_record_service,
    )
    from app.worker.tasks import process_interview_analysis

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == resolve_user_pk(db, current_user.username),
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.session_type != "mock_interview":
        raise HTTPException(status_code=400, detail="Session is not a mock interview")

    state = parse_mock_state(session.mock_interview_state)
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
        user_id=resolve_user_pk(db, current_user.username),
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
    session.mock_interview_state = dump_mock_state(state)
    session.archived_at = now

    debrief_session = ChatSession(
        id=generate_uuid(),
        user_id=resolve_user_pk(db, current_user.username),
        title=f"复盘: {session.title or '模拟面试'}",
        session_type="debrief",
        interview_id=record.id,
    )
    db.add(debrief_session)
    await asyncio.to_thread(db.commit)

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

    from app.services.storage_service import download_file_from_s3
    from app.services.uploads.file_asset_service import get_owned_file_asset
    from app.services.voice.file_parser import extract_resume_text

    upload = get_owned_file_asset(db, file_asset_id=upload_id, user_id=user_id)
    if (
        upload is None
        or upload.purpose not in ("interview_resume", "knowledge_document")
        or not upload.storage_uri
    ):
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


@router.post("/chat/mock-interview/parse-jd", response_model=MockParseJdResp)
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

    # validate_upload owns size + magic-byte checks; the older size guard
    # below is now redundant but kept as a fast-path so a 100MB upload
    # gets rejected before we read it into memory.
    if file.size is not None and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="JD 文件过大（限制 10MB）")

    declared_ext = os.path.splitext(file.filename or "")[1].lower() or ".pdf"
    contents = await validate_upload(file, purpose="jd", declared_ext=declared_ext)

    suffix = declared_ext
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
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


# ── Short-clip transcription (MediaRecorder → text) ────────────────────


@router.post("/chat/mock-interview/transcribe", response_model=MockTranscribeResp)
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

    # Fast-path size guard (avoids reading megabytes for over-cap uploads);
    # validate_upload re-asserts size + magic-byte.
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
                    status_code=503,
                    detail="转写模型未就绪，请稍后重试",
                ) from exc

        import whisperx  # type: ignore

        # ``load_audio`` decodes the file from disk (sync) and
        # ``whisper_model.transcribe`` runs a 1-5s CPU/GPU pass on
        # the audio. Both block the event loop if called inline from
        # an async handler — every concurrent /chat/sse turn would
        # stall while transcription runs. Dispatch via to_thread so
        # the loop stays free to drive other in-flight requests.
        audio = await asyncio.to_thread(whisperx.load_audio, local_path)
        kwargs: dict = {"batch_size": 8}
        if language and language.lower() != "auto":
            kwargs["language"] = language
        result = await asyncio.to_thread(
            ats.whisper_model.transcribe, audio, **kwargs,
        )
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
@limiter.limit(RATE_EXPENSIVE)
async def synthesize_speech(
    request: Request,
    response: Response,
    body: TTSRequest,
    _current_user: User = Depends(get_current_user),
):
    """Convert text to speech using edge-tts. Returns mp3 audio stream."""
    from app.services.voice.tts_service import tts_service

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    audio_bytes = await tts_service.synthesize(
        text=body.text,
        voice=body.voice,
    )
    if not audio_bytes:
        raise HTTPException(status_code=500, detail="TTS synthesis failed")

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Length": str(len(audio_bytes))},
    )
