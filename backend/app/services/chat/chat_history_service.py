"""Chat-session and chat-message storage service.

Manages persistent chat history (``Conversation`` / ``ConversationMessage`` rows) —
sessions, recent turns, full transcripts, cursor advancement.

Hierarchy (post-0018): an ``interview_record`` has many ``conversations``;
each session IS the chat thread (its own ``summary`` compaction,
its own monotonic ``conversation_messages.seq``). The earlier "session → many
conversations" hierarchy from 0015/0017 was reverted — multi-thread
brainstorming now lives as siblings under the same record.

Content blocks (Stage G refactor — Anthropic Claude Code style):
  Each ConversationMessage carries TWO representations of the assistant turn:
    * ``content``               — plain text preview (used by session
                                  list UI, memory extraction)
    * ``content_blocks_json``   — JSON ``[BetaContentBlock, ...]`` so the
                                  agent loop's interleaved
                                  text / tool_use / tool_result chain
                                  round-trips for the frontend folded-
                                  card UX. NULL on legacy rows; the
                                  reader synthesises a single-text-block
                                  array as the fallback.
"""

import json
import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.chat import ConversationMessage, Conversation, generate_uuid

logger = logging.getLogger(__name__)


class TranscriptService:
    def ensure_session(self, session_id: str, user_id: str) -> str:
        db: Session = SessionLocal()
        try:
            row = db.query(Conversation).filter(Conversation.id == session_id).first()
            if row is None:
                row = Conversation(
                    id=session_id or generate_uuid(),
                    user_id=resolve_user_pk(db, user_id),
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
        ai_blocks: list[dict] | None = None,
        user_blocks: list[dict] | None = None,
    ) -> int:
        """Persist one ``User → Agent`` turn.

        ``user_msg`` / ``ai_msg`` are the plain-text canonical form.
        ``user_blocks`` / ``ai_blocks`` are the optional Anthropic
        BetaContentBlock arrays — populate them when the turn included
        tool calls (L2 agent) so the frontend can render the same
        interleaved text + tool_use / tool_result UX it saw live.
        When ``ai_blocks`` is None the reader synthesises a single text
        block from ``ai_msg`` at GET time.
        """
        db: Session = SessionLocal()
        try:
            session_row = db.query(Conversation).filter(Conversation.id == session_id).first()
            if session_row is None:
                session_row = Conversation(
                    id=session_id,
                    user_id=resolve_user_pk(db, user_id),
                )
                db.add(session_row)
                db.flush()

            max_seq = (
                db.query(func.max(ConversationMessage.seq))
                .filter(ConversationMessage.session_id == session_id)
                .scalar()
            )
            next_seq = (max_seq + 1) if max_seq else 1

            db.add(ConversationMessage(
                session_id=session_id, seq=next_seq, role="User",
                content=user_msg,
                content_blocks_json=(
                    json.dumps(user_blocks, ensure_ascii=False)
                    if user_blocks else None
                ),
                rewritten_query=rewritten_query,
            ))
            db.add(ConversationMessage(
                session_id=session_id, seq=next_seq + 1, role="Agent",
                content=ai_msg,
                content_blocks_json=(
                    json.dumps(ai_blocks, ensure_ascii=False)
                    if ai_blocks else None
                ),
            ))

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
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.session_id == session_id,
                    ConversationMessage.seq > after_seq,
                )
                .order_by(ConversationMessage.seq.desc())
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
                db.query(ConversationMessage)
                .filter(
                    ConversationMessage.session_id == session_id,
                    ConversationMessage.seq >= start_seq,
                    ConversationMessage.seq <= end_seq,
                )
                .order_by(ConversationMessage.seq.asc())
                .all()
            )
            return [self._message_to_dict(row) for row in rows]
        finally:
            db.close()

    def get_full_transcript(self, session_id: str) -> list[dict]:
        db: Session = SessionLocal()
        try:
            rows = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.session_id == session_id)
                .order_by(ConversationMessage.seq.asc())
                .all()
            )
            return [self._message_to_dict(row) for row in rows]
        finally:
            db.close()

    def get_session_meta(self, session_id: str) -> dict | None:
        db: Session = SessionLocal()
        try:
            row = db.query(Conversation).filter(Conversation.id == session_id).first()
            if row is None:
                return None
            return {
                "session_id": row.id,
                # Owner pk (users.id). build_interview_reference matches it
                # pk==pk against the bound interview_record's user_id.
                "user_id": row.user_id,
                "session_type": row.session_type or "general",
                "interview_id": row.interview_id,
                "turn_count": row.turn_count or 0,
                "compaction_cursor": row.compaction_cursor or 0,
                "memory_extraction_cursor": row.memory_extraction_cursor or 0,
                "summary": row.summary or "",
            }
        finally:
            db.close()

    def update_session_fields(self, session_id: str, **kwargs) -> None:
        db: Session = SessionLocal()
        try:
            row = db.query(Conversation).filter(Conversation.id == session_id).first()
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
    def _message_to_dict(row: ConversationMessage) -> dict:
        """Serialize one row. ``blocks`` is always populated — either
        parsed from ``content_blocks_json`` or synthesised as a single
        text block from ``content`` (read-time backfill for legacy rows
        and L1 chat turns that don't bother to write blocks_json)."""
        blocks: list[dict] | None = None
        if row.content_blocks_json:
            try:
                parsed = json.loads(row.content_blocks_json)
                if isinstance(parsed, list):
                    blocks = parsed
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "conversation_messages id=%s has unparseable content_blocks_json; "
                    "falling back to single-text-block synthesis",
                    row.id,
                )
        if blocks is None:
            # Read-time backfill: synthesise the Claude-Code shape from
            # the plain-text content. Frontend always receives a uniform
            # blocks array, regardless of whether the row was written
            # before or after the Stage-G refactor.
            blocks = [{"type": "text", "text": row.content or ""}]
        return {
            "seq": row.seq,
            "role": row.role,
            "content": row.content,
            "blocks": blocks,
            "rewritten_query": row.rewritten_query,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


transcript_service = TranscriptService()


__all__ = ["TranscriptService", "transcript_service"]
