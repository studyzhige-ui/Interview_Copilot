"""Live media delegates every committed answer to the existing mock operation."""

from __future__ import annotations

from datetime import timedelta
import uuid

from app.core.security import get_current_user
from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.mock_media import MockMediaLease, MockMediaPlayback
from app.models.chat import Conversation, ConversationMessage
from app.interviews.application import mock_flow, mock_runtime_service
from app.interviews.application.interview_record_service import STATUS_MOCK_IN_PROGRESS
from app.media.realtime.asr import LiveASR
from app.media.application.tts_service import tts_service
from app.usage import runtime as usage


class MediaConflict(ValueError):
    pass


def claim(db, *, record_id, username, client_session_id, connection_id):
    record = mock_flow.get_owned_mock_record(db, record_id, username, for_update=True)
    if record is None or record.status != STATUS_MOCK_IN_PROGRESS:
        raise MediaConflict("media_interview_not_active")
    lease = db.get(MockMediaLease, record_id)
    now = utc_now()
    if (
        lease
        and lease.expires_at > now
        and lease.client_session_id != client_session_id
    ):
        raise MediaConflict("media_already_connected")
    if lease is None:
        lease = MockMediaLease(record_id=record_id)
    lease.client_session_id, lease.connection_id = client_session_id, connection_id
    lease.expires_at = now + timedelta(seconds=35)
    db.add(lease)
    db.commit()


class LiveInterview:
    def __init__(self, *, record_id, user_id, username, token, connection_id):
        self.record_id, self.user_id, self.username = record_id, user_id, username
        self.token, self.connection_id = token, connection_id
        self.asr = LiveASR()

    def checked_record(self, db, *, lock=False):
        record = mock_flow.get_owned_mock_record(
            db, self.record_id, self.username, for_update=lock
        )
        lease = db.get(MockMediaLease, self.record_id)
        if (
            record is None
            or record.user_id != self.user_id
            or record.status != STATUS_MOCK_IN_PROGRESS
            or lease is None
            or lease.connection_id != self.connection_id
            or lease.expires_at <= utc_now()
        ):
            raise MediaConflict("media_lease_lost")
        return record, lease

    async def authorize(self):
        # The original credential expires/revokes normally. Reconnecting acquires
        # a refreshed credential; an open data channel is not permanent auth.
        with usage.scope(
            self.user_id, f"media-auth:{self.connection_id}", username=self.username
        ):
            with SessionLocal() as db:
                user = await get_current_user(token=self.token, db=db)
                if user.id != self.user_id or not user.is_active:
                    raise MediaConflict("media_owner_lost")
                _, lease = self.checked_record(db, lock=True)
                lease.expires_at = utc_now() + timedelta(seconds=35)
                db.commit()

    async def state(self):
        await self.authorize()
        with SessionLocal() as db:
            self.checked_record(db)
            cursor = mock_runtime_service.get_runtime_for_record(
                db, interview_record_id=self.record_id
            )
            if cursor is None:
                raise MediaConflict("media_interview_not_active")
            messages = mock_flow.live_messages(db, cursor.conversation_id)
            return {
                "question_message_id": cursor.current_question_message_id,
                "messages": messages,
                "can_listen": bool(
                    messages and messages[-1]["speaker"] == "interviewer"
                ),
            }

    async def partial(self, pcm):
        with usage.scope(
            self.user_id, f"media-partial:{uuid.uuid4()}", username=self.username
        ):
            return await self.asr.window(pcm)

    async def final(self, pcm):
        await self.authorize()
        with usage.scope(
            self.user_id, f"media-final:{uuid.uuid4()}", username=self.username
        ):
            return await self.asr.final(pcm)

    async def commit(self, draft):
        await self.authorize()
        with usage.scope(
            self.user_id, f"media-answer:{draft['request_id']}", username=self.username
        ):
            with SessionLocal() as db:
                record, _ = self.checked_record(db, lock=True)
                cursor = mock_runtime_service.get_runtime_for_record(
                    db, interview_record_id=self.record_id
                )
                result = await mock_flow.submit_answer(
                    db,
                    record=record,
                    runtime=cursor,
                    answer_text=draft["text"],
                    answer_audio_file_asset_id=None,
                    user_id=self.username,
                    question_message_id=draft["question_message_id"],
                    request_id=draft["request_id"],
                )
                return {
                    "message": {
                        "id": result.question_message_id,
                        "speaker": "interviewer",
                        "text": result.interviewer_message,
                    },
                    "end_suggested": result.is_ready_to_finish,
                }

    async def synthesize(self, text):
        from app.core.config import settings

        if settings.TTS_PROVIDER != "local_qwen3_tts":
            raise MediaConflict("media_requires_local_tts")
        with usage.scope(
            self.user_id, f"media-speech:{uuid.uuid4()}", username=self.username
        ):
            result = await tts_service.synthesize(text)
        if result.media_type != "audio/wav":
            raise ValueError("media_synthesis_format")
        return result.data

    async def playback(self, report):
        # Old connections may finish writing their own playback observation
        # after takeover. They cannot change business state or another receipt.
        with SessionLocal() as db:
            record = mock_flow.get_owned_mock_record(db, self.record_id, self.username)
            message = (
                db.query(ConversationMessage)
                .join(Conversation)
                .filter(
                    ConversationMessage.id == report["message_id"],
                    ConversationMessage.role == "assistant",
                    Conversation.subject_type == "interview_record",
                    Conversation.subject_id == self.record_id,
                )
                .first()
            )
            if record is None or record.user_id != self.user_id or message is None:
                return
            if (
                db.get(MockMediaPlayback, (self.record_id, report["playback_id"]))
                is None
            ):
                db.add(MockMediaPlayback(record_id=self.record_id, **report))
                db.commit()

    def release(self):
        with SessionLocal() as db:
            db.query(MockMediaLease).filter_by(
                record_id=self.record_id, connection_id=self.connection_id
            ).delete()
            db.commit()


def playback_reports(db, *, record_id, username):
    record = mock_flow.get_owned_mock_record(db, record_id, username)
    if record is None:
        raise MediaConflict("media_record_not_found")
    return (
        db.query(MockMediaPlayback)
        .filter(MockMediaPlayback.record_id == record_id)
        .order_by(MockMediaPlayback.created_at.desc(), MockMediaPlayback.playback_id)
        .limit(50)
        .all()
    )
