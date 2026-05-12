"""Chat-session and chat-message storage service.

Manages persistent chat history (``ChatSession`` / ``ChatMessage`` rows) —
sessions, recent turns, full transcripts, cursor advancement.  Renamed
from ``transcript_service`` to remove ambiguity with the audio
transcription pipeline.

The public class is still ``TranscriptService`` and the module-level
singleton is ``transcript_service`` to avoid touching every call site
in one pass; these aliases may be renamed in a follow-up.
"""

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.chat import ChatMessage, ChatSession, default_session_state, generate_uuid

logger = logging.getLogger(__name__)


class TranscriptService:
    def ensure_session(self, session_id: str, user_id: str) -> str:
        db: Session = SessionLocal()
        try:
            row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if row is None:
                row = ChatSession(
                    id=session_id or generate_uuid(),
                    user_id=user_id,
                    session_state=default_session_state(),
                )
                db.add(row)
                db.commit()
            return row.id
        finally:
            db.close()

    def append_turn(
        self,
        session_id: str,
        user_id: str,
        user_msg: str,
        ai_msg: str,
        rewritten_query: str | None = None,
    ) -> int:
        db: Session = SessionLocal()
        try:
            session_row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if session_row is None:
                session_row = ChatSession(
                    id=session_id,
                    user_id=user_id,
                    session_state=default_session_state(),
                )
                db.add(session_row)
                db.flush()

            max_seq = (
                db.query(func.max(ChatMessage.seq))
                .filter(ChatMessage.session_id == session_id)
                .scalar()
            )
            next_seq = (max_seq + 1) if max_seq else 1

            db.add(
                ChatMessage(
                    session_id=session_id,
                    seq=next_seq,
                    role="User",
                    content=user_msg,
                    rewritten_query=rewritten_query,
                )
            )
            db.add(
                ChatMessage(
                    session_id=session_id,
                    seq=next_seq + 1,
                    role="Agent",
                    content=ai_msg,
                )
            )

            session_row.turn_count = (session_row.turn_count or 0) + 1
            session_row.updated_at = datetime.utcnow()
            db.commit()
            return next_seq + 1
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_recent_turns(
        self,
        session_id: str,
        max_turns: int = 10,
        after_seq: int = 0,
    ) -> list[dict]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.seq > after_seq,
                )
                .order_by(ChatMessage.seq.desc())
                .limit(max_turns * 2)
                .all()
            )
            rows.reverse()
            return [self._message_to_dict(row) for row in rows]
        finally:
            db.close()

    def get_messages_in_range(
        self,
        session_id: str,
        start_seq: int,
        end_seq: int,
    ) -> list[dict]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.seq >= start_seq,
                    ChatMessage.seq <= end_seq,
                )
                .order_by(ChatMessage.seq.asc())
                .all()
            )
            return [self._message_to_dict(row) for row in rows]
        finally:
            db.close()

    def get_full_transcript(self, session_id: str) -> list[dict]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.seq.asc())
                .all()
            )
            return [self._message_to_dict(row) for row in rows]
        finally:
            db.close()

    def get_session_meta(self, session_id: str) -> dict | None:
        db: Session = SessionLocal()
        try:
            row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if row is None:
                return None
            return {
                "session_id": row.id,
                "user_id": row.user_id,
                "session_type": row.session_type or "general",
                "interview_id": row.interview_id,
                "turn_count": row.turn_count or 0,
                "compaction_cursor": row.compaction_cursor or 0,
                "memory_extraction_cursor": row.memory_extraction_cursor or 0,
                "session_state": row.session_state or default_session_state(),
            }
        finally:
            db.close()

    def update_session_fields(self, session_id: str, **kwargs) -> None:
        db: Session = SessionLocal()
        try:
            row = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if row is None:
                return
            for key, value in kwargs.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Failed to update session fields: %s", exc)
            raise
        finally:
            db.close()

    @staticmethod
    def _message_to_dict(row: ChatMessage) -> dict:
        return {
            "seq": row.seq,
            "role": row.role,
            "content": row.content,
            "rewritten_query": row.rewritten_query,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


transcript_service = TranscriptService()


__all__ = ["TranscriptService", "transcript_service"]
