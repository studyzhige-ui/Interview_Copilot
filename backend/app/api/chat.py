import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db
from app.models.chat import ChatMessage, ChatSession, generate_uuid
from app.models.memory import MemoryItem
from app.models.user import User
from app.services.memory_extraction_service import memory_retrieval_service
from app.services.state_utils import parse_session_state, summarize_session_state
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


class SessionCreateRequest(BaseModel):
    session_type: str = "general"  # "general" | "debrief" | "mock_interview"
    interview_id: str | None = None
    title: str | None = None


class SessionCreateResponse(BaseModel):
    session_id: str
    title: str
    session_type: str


class SessionListItem(BaseModel):
    session_id: str
    title: str
    session_type: str
    state_summary: str
    turn_count: int
    updated_at: str


class MessageItem(BaseModel):
    seq: int
    role: str
    content: str
    created_at: str


class SSEChatRequest(BaseModel):
    message: str


@router.post("/chat/sessions", response_model=SessionCreateResponse)
def create_chat_session(
    request: SessionCreateRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.state_utils import default_session_state_for_type, dump_session_state

    req = request or SessionCreateRequest()
    session_type = req.session_type if req.session_type in {"general", "debrief", "mock_interview"} else "general"

    # Validate interview_id for debrief sessions
    if session_type == "debrief" and req.interview_id:
        from app.models.interview_record import InterviewRecord
        record = db.query(InterviewRecord).filter(
            InterviewRecord.id == req.interview_id,
            InterviewRecord.user_id == current_user.username,
        ).first()
        if record is None:
            raise HTTPException(status_code=404, detail="Interview record not found")

    default_titles = {
        "general": "通用对话",
        "debrief": "面试复盘",
        "mock_interview": "模拟面试",
    }
    title = req.title or default_titles.get(session_type, "新的面试对话")

    state = default_session_state_for_type(session_type, req.interview_id or "")
    new_session = ChatSession(
        id=generate_uuid(),
        user_id=current_user.username,
        title=title,
        session_type=session_type,
        interview_id=req.interview_id,
        session_state=dump_session_state(state),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    return SessionCreateResponse(
        session_id=new_session.id,
        title=new_session.title,
        session_type=new_session.session_type,
    )


@router.get("/chat/sessions", response_model=List[SessionListItem])
def list_chat_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.username)
        .order_by(ChatSession.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        SessionListItem(
            session_id=row.id,
            title=row.title or "新的面试对话",
            session_type=row.session_type or "general",
            state_summary=summarize_session_state(
                parse_session_state(row.session_state, row.session_type or "general")
            ),
            turn_count=row.turn_count or 0,
            updated_at=row.updated_at.isoformat() if row.updated_at else "",
        )
        for row in rows
    ]


@router.get("/chat/history", response_model=List[MessageItem])
def get_chat_history(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.seq.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    rows.reverse()
    return [
        MessageItem(
            seq=row.seq,
            role=row.role,
            content=row.content,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]


@router.patch("/chat/sessions/{session_id}/title")
def update_session_title(
    session_id: str,
    title: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")
    row.title = title
    db.commit()
    return {"status": "success", "session_id": session_id, "new_title": title}


@router.get("/memory/items")
async def list_memory_items(current_user: User = Depends(get_current_user)):
    items = await memory_retrieval_service.get_memory_index(current_user.username)
    return {"status": "success", "items": items, "total": len(items)}


@router.get("/memory/items/{memory_id}")
def get_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(MemoryItem)
        .filter(MemoryItem.id == memory_id, MemoryItem.user_id == current_user.username)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Memory item not found")
    return {
        "status": "success",
            "item": {
                "id": row.id,
                "type": row.type,
                "scope": row.scope,
                "description": row.description,
                "normalized_key": row.normalized_key,
                "content": row.content,
                "confidence": row.confidence or 0.0,
                "importance": row.importance or 0.0,
                "source_session_id": row.source_session_id,
                "last_evidence_seq": row.last_evidence_seq,
                "recall_count": row.recall_count or 0,
                "last_accessed_at": (
                    row.last_accessed_at.isoformat() if row.last_accessed_at else None
                ),
                "embedding_status": row.embedding_status,
                "embedding_model": row.embedding_model,
                "embedded_at": row.embedded_at.isoformat() if row.embedded_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            },
    }


@router.delete("/memory/items/{memory_id}")
def delete_memory_item(
    memory_id: str,
    current_user: User = Depends(get_current_user),
):
    success = memory_retrieval_service.delete_memory(memory_id, current_user.username)
    if not success:
        raise HTTPException(status_code=404, detail="Memory item not found or access denied")
    return {"status": "success", "message": f"Memory {memory_id} deleted"}


@router.get("/chat/transcript")
def get_full_transcript(
    session_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    meta = transcript_service.get_session_meta(session_id)
    messages = transcript_service.get_full_transcript(session_id)
    return {
        "status": "success",
        "session_id": session_id,
        "session_type": meta["session_type"] if meta else "general",
        "turn_count": meta["turn_count"] if meta else 0,
        "compaction_cursor": meta["compaction_cursor"] if meta else 0,
        "session_state": (
            parse_session_state(meta["session_state"], meta.get("session_type", "general"))
            if meta
            else {}
        ),
        "messages": messages,
        "total_messages": len(messages),
    }


def get_ws_current_user(token: str, db: Session) -> User | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username = payload.get("sub")
        if not username:
            return None
        return db.query(User).filter(User.username == username).first()
    except JWTError:
        return None


@router.websocket("/chat/ws/{session_id}")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    user = get_ws_current_user(token, db)
    if not user:
        await websocket.close(code=1008, reason="Unauthorized or expired token")
        return

    session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not session_row or session_row.user_id != user.username:
        await websocket.close(code=1008, reason="Session not found or access denied")
        return

    await websocket.accept()
    from app.agent.agent_executor import stream_chat_with_agent

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            if not message:
                continue
            async for chunk in stream_chat_with_agent(message, user.username, session_id):
                if chunk:
                    await websocket.send_json({"type": "chunk", "content": chunk})
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", session_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("WebSocket pipeline failed: %s", exc)
        try:
            await websocket.send_json({"type": "chunk", "content": f"\n\n[system]: {exc}"})
            await websocket.send_json({"type": "done"})
        except Exception:  # noqa: BLE001
            pass


@router.post("/chat/sse/{session_id}")
async def sse_chat_endpoint(
    session_id: str,
    request: SSEChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not row or row.user_id != current_user.username:
        raise HTTPException(status_code=404, detail="Session not found or access denied")

    from app.agent.agent_executor import stream_chat_with_agent

    async def event_generator():
        try:
            async for chunk in stream_chat_with_agent(
                request.message,
                current_user.username,
                session_id,
            ):
                if chunk:
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"
        except Exception as exc:  # noqa: BLE001
            logger.error("SSE pipeline failed: %s", exc)
            yield f"data: {json.dumps({'type': 'chunk', 'content': f'[system]: {exc}'}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Mock Interview Control Endpoints ─────────────────────────────────

class MockStartRequest(BaseModel):
    session_id: str
    resume_upload_id: str | None = None


class MockAnswerRequest(BaseModel):
    session_id: str
    answer: str


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


@router.post("/chat/mock-interview/start")
async def start_mock_interview(
    request: MockStartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate interview plan and initialize mock interview session."""
    from app.services.mock_interview_service import mock_interview_service
    from app.services.resume_service import resume_service
    from app.services.state_utils import dump_session_state, parse_session_state

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
    from app.services.state_utils import parse_session_state

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
    from app.services.state_utils import dump_session_state, parse_session_state

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
    from app.services.state_utils import dump_session_state, parse_session_state

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
    from app.services.tts_service import tts_service

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

