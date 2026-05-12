"""Mock-interview control endpoints + TTS."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
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

    # Load resume context if available
    resume_context = ""
    if request.resume_upload_id:
        sections = resume_service.get_sections_by_upload(
            request.resume_upload_id, current_user.username,
        )
        resume_context = resume_service.format_for_context(sections)

    # Generate plan
    plan = await mock_interview_service.generate_plan(resume_context)

    # Initialize session state
    state = parse_session_state(session.session_state, "mock_interview")
    state["interview_plan"] = plan
    state["current_phase"] = plan["phases"][0]["phase_id"] if plan.get("phases") else ""
    state["current_question_idx"] = 0
    state["qa_history"] = []
    state["resume_context"] = resume_context[:2000]
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
    )

    # Record Q&A in history
    qa_history.append({
        "phase_id": question_info["phase_id"],
        "question": question_info["question"],
        "answer": request.answer,
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
    """End the mock interview: batch evaluate, create record + debrief session."""
    from app.services.interview_record_service import interview_record_service
    from app.services.mock_interview_service import mock_interview_service

    session = db.query(ChatSession).filter(
        ChatSession.id == session_id,
        ChatSession.user_id == current_user.username,
    ).first()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = parse_session_state(session.session_state, "mock_interview")
    qa_history = state.get("qa_history", [])

    # Batch evaluate all Q&A
    analysis = await mock_interview_service.batch_evaluate(
        qa_history=qa_history,
        resume_context=state.get("resume_context", ""),
    )

    # Mark finished
    state["is_finished"] = True
    session.session_state = dump_session_state(state)
    db.commit()

    # Create InterviewRecord
    record = interview_record_service.create_from_mock(
        user_id=current_user.username,
        title=session.title or "模拟面试",
        resume_upload_id=None,
        interview_plan=json.dumps(state.get("interview_plan", {}), ensure_ascii=False),
        db=db,
    )

    # Build transcript from Q&A history
    transcript_lines = []
    for i, entry in enumerate(qa_history, 1):
        transcript_lines.append(f"面试官: {entry.get('question', '')}")
        transcript_lines.append(f"候选人: {entry.get('answer', '')}")
    transcript_text = "\n\n".join(transcript_lines)

    interview_record_service.finish_mock_interview(
        record.id,
        transcript=transcript_text,
        analysis_json=json.dumps(analysis, ensure_ascii=False),
        db=db,
    )

    # Create debrief session for post-interview review
    debrief_session = ChatSession(
        id=generate_uuid(),
        user_id=current_user.username,
        title=f"复盘: {session.title or '模拟面试'}",
        session_type="debrief",
        session_state=json.dumps({
            "record_id": record.id,
            "summary": "",
        }, ensure_ascii=False),
    )
    db.add(debrief_session)
    db.commit()

    return {
        "status": "finished",
        "record_id": record.id,
        "debrief_session_id": debrief_session.id,
        "summary": analysis,
    }


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
