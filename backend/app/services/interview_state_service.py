import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.interview_state import InterviewState
from app.services.state_utils import (
    default_interview_state_payload,
    dump_state_blob,
    parse_state_blob,
)

logger = logging.getLogger(__name__)


def generate_interview_state_id(session_id: str, user_id: str) -> str:
    return f"ivs::{user_id}::{session_id}"


class InterviewStateService:
    def ensure_state(self, session_id: str, user_id: str) -> None:
        db: Session = SessionLocal()
        try:
            row = (
                db.query(InterviewState)
                .filter(
                    InterviewState.session_id == session_id,
                    InterviewState.user_id == user_id,
                )
                .first()
            )
            if row is None:
                db.add(
                    InterviewState(
                        id=generate_interview_state_id(session_id, user_id),
                        session_id=session_id,
                        user_id=user_id,
                        state_json=dump_state_blob(default_interview_state_payload()),
                    )
                )
                db.commit()
        finally:
            db.close()

    def get_state(self, session_id: str, user_id: str) -> dict:
        db: Session = SessionLocal()
        try:
            row = (
                db.query(InterviewState)
                .filter(
                    InterviewState.session_id == session_id,
                    InterviewState.user_id == user_id,
                )
                .first()
            )
            if row is None:
                return default_interview_state_payload()
            return parse_state_blob(row.state_json, default_interview_state_payload)
        finally:
            db.close()

    def update_state(self, session_id: str, user_id: str, payload: dict) -> None:
        db: Session = SessionLocal()
        try:
            row = (
                db.query(InterviewState)
                .filter(
                    InterviewState.session_id == session_id,
                    InterviewState.user_id == user_id,
                )
                .first()
            )
            if row is None:
                row = InterviewState(
                    id=generate_interview_state_id(session_id, user_id),
                    session_id=session_id,
                    user_id=user_id,
                )
                db.add(row)
            row.state_json = dump_state_blob(payload)
            row.updated_at = datetime.utcnow()
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("Failed to update interview state: %s", exc)
            raise
        finally:
            db.close()


interview_state_service = InterviewStateService()
