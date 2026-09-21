"""Authorize media generations and route final answers through the existing flow.

Only durable facts survive reconnect. PCM and provisional ASR are never stored.
The record lock precedes the media lock in every transaction. A reconnect fences
unaccepted audio; an already committed answer may finish into its original receipt.
"""

from dataclasses import dataclass
from datetime import timedelta
import hashlib
import io
import uuid
import wave
from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.types import utc_now
from app.models.interview_record import InterviewRecord
from app.models.mock_media_session import MockMediaSession, MockMediaPlayback
from app.interviews.application import (
    mock_flow,
    mock_runtime_service,
    mock_answer_receipts,
)
from app.interviews.application.interview_record_service import STATUS_MOCK_IN_PROGRESS
from app.media.realtime.asr import LiveASR
from app.media.application.tts_service import tts_service
from app.usage import runtime as usage


@dataclass(frozen=True)
class MediaLease:
    id: str
    generation: int
    record_id: str
    user_pk: int
    username: str


def _record(db, record_id, user_pk):
    row = db.scalar(
        select(InterviewRecord)
        .where(
            InterviewRecord.id == record_id,
            InterviewRecord.user_id == user_pk,
            InterviewRecord.source == "mock",
        )
        .with_for_update()
    )
    if row is None or row.status != STATUS_MOCK_IN_PROGRESS:
        raise ValueError("media_record_unavailable")
    return row


def _session(db, lease):
    row = db.scalar(
        select(MockMediaSession)
        .where(
            MockMediaSession.id == lease.id,
            MockMediaSession.record_id == lease.record_id,
            MockMediaSession.generation == lease.generation,
            MockMediaSession.lease_until > utc_now(),
        )
        .with_for_update()
    )
    if row is None:
        raise ValueError("media_generation_expired")
    return row


def claim(record_id: str, user_pk: int, username: str, client_id: str) -> MediaLease:
    with SessionLocal() as db:
        _record(db, record_id, user_pk)
        rows = list(
            db.scalars(
                select(MockMediaSession).where(MockMediaSession.record_id == record_id)
            )
        )
        if any(
            row.client_session_id != client_id and row.lease_until > utc_now()
            for row in rows
        ):
            raise ValueError("another_media_session_active")
        row = next((r for r in rows if r.client_session_id == client_id), None)
        if row is None:
            if len(rows) >= 32:
                raise ValueError("media_session_capacity")
            row = MockMediaSession(
                id=str(uuid.uuid4()),
                record_id=record_id,
                client_session_id=client_id,
                generation=1,
            )
            db.add(row)
        else:
            row.generation += 1
            db.query(MockMediaPlayback).filter_by(
                session_id=row.id, state="generated"
            ).update(
                {MockMediaPlayback.state: "interrupted"}, synchronize_session=False
            )
        row.lease_until = utc_now() + timedelta(seconds=35)
        lease = MediaLease(row.id, row.generation, record_id, user_pk, username)
        db.commit()
        return lease


def renew(lease: MediaLease):
    with SessionLocal() as db:
        _record(db, lease.record_id, lease.user_pk)
        _session(db, lease).lease_until = utc_now() + timedelta(seconds=35)
        db.commit()


def release(lease: MediaLease):
    with SessionLocal() as db:
        # A late close cannot revoke a replacement generation.
        db.query(MockMediaSession).filter_by(
            id=lease.id, generation=lease.generation
        ).update({MockMediaSession.lease_until: utc_now()}, synchronize_session=False)
        db.query(MockMediaPlayback).filter_by(
            session_id=lease.id, generation=lease.generation, state="generated"
        ).update({MockMediaPlayback.state: "interrupted"}, synchronize_session=False)
        db.commit()


def state(lease: MediaLease):
    with SessionLocal() as db:
        _record(db, lease.record_id, lease.user_pk)
        row = _session(db, lease)
        cursor = mock_runtime_service.get_runtime_for_record(
            db, interview_record_id=lease.record_id
        )
        if cursor is None:
            raise ValueError("media_record_unavailable")
        messages = mock_flow.live_messages(db, cursor.conversation_id)
        question = next(
            (m for m in reversed(messages) if m["speaker"] == "interviewer"), None
        )
        receipt = (
            mock_answer_receipts.read_receipt(
                db, lease.record_id, row.pending_request_id
            )
            if row.pending_request_id
            else None
        )
        return {
            "question": question,
            "answer_pending": bool(messages and messages[-1]["speaker"] == "candidate"),
            "request_id": row.pending_request_id,
            "request_status": receipt.status if receipt else None,
        }


def register_audio(
    lease: MediaLease, question_id: int, text: str, pcm: bytes, rate: int
):
    if rate != 24000 or not pcm or len(pcm) % 2 or len(pcm) > 2880000:
        raise ValueError("invalid_media_output")
    with SessionLocal() as db:
        _record(db, lease.record_id, lease.user_pk)
        _session(db, lease)
        cursor = mock_runtime_service.get_runtime_for_record(
            db, interview_record_id=lease.record_id
        )
        if cursor is None or cursor.current_question_message_id != question_id:
            raise ValueError("media_question_changed")
        if db.query(MockMediaPlayback).filter_by(session_id=lease.id).count() >= 2000:
            raise ValueError("media_playback_capacity")
        audio_id = str(uuid.uuid4())
        db.add(
            MockMediaPlayback(
                id=audio_id,
                session_id=lease.id,
                generation=lease.generation,
                question_message_id=question_id,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                audio_sha256=hashlib.sha256(pcm).hexdigest(),
                sample_rate=rate,
                generated_samples=len(pcm) // 2,
                reported_samples=0,
                state="generated",
            )
        )
        db.commit()
        return audio_id


def acknowledge(lease: MediaLease, audio_id: str, samples: int, complete: bool):
    with SessionLocal() as db:
        _record(db, lease.record_id, lease.user_pk)
        _session(db, lease)
        row = db.scalar(
            select(MockMediaPlayback)
            .where(
                MockMediaPlayback.id == audio_id,
                MockMediaPlayback.session_id == lease.id,
                MockMediaPlayback.generation == lease.generation,
            )
            .with_for_update()
        )
        if (
            row is None
            or type(samples) is not int
            or not row.reported_samples <= samples <= row.generated_samples
        ):
            raise ValueError("invalid_playback_ack")
        if row.state == "interrupted" or (
            complete and samples != row.generated_samples
        ):
            raise ValueError("invalid_playback_ack")
        row.reported_samples = samples
        if complete:
            row.state = "client_reported"
        db.commit()


def interrupt_audio(lease: MediaLease, audio_id: str):
    with SessionLocal() as db:
        db.query(MockMediaPlayback).filter_by(
            id=audio_id,
            session_id=lease.id,
            generation=lease.generation,
            state="generated",
        ).update({MockMediaPlayback.state: "interrupted"}, synchronize_session=False)
        db.commit()


async def submit_final(lease: MediaLease, question_id: int, text: str, request_id: str):
    with usage.scope(
        lease.user_pk, f"media-answer:{request_id}", username=lease.username
    ):
        with SessionLocal() as db:
            record = _record(db, lease.record_id, lease.user_pk)
            media = _session(db, lease)
            media.pending_request_id = request_id
            cursor = mock_runtime_service.get_runtime_for_record(
                db, interview_record_id=lease.record_id
            )
            turn = await mock_flow.submit_answer(
                db,
                record=record,
                runtime=cursor,
                answer_text=text,
                answer_audio_file_asset_id=None,
                user_id=lease.username,
                question_message_id=question_id,
                request_id=request_id,
            )
            return {
                "message": {
                    "id": turn.question_message_id,
                    "speaker": "interviewer",
                    "text": turn.interviewer_message,
                },
                "end_suggested": turn.is_ready_to_finish,
            }


class InterviewMedia:
    """No ORM objects or database connections cross the long-lived media boundary."""

    def __init__(self, lease: MediaLease):
        self.lease = lease
        self.asr = LiveASR()

    async def transcribe(self, pcm):
        with usage.scope(
            self.lease.user_pk,
            f"media-asr:{uuid.uuid4()}",
            username=self.lease.username,
        ):
            return await self.asr.transcribe(pcm)

    async def synthesize(self, text):
        with usage.scope(
            self.lease.user_pk,
            f"media-tts:{uuid.uuid4()}",
            username=self.lease.username,
        ):
            result = await tts_service.synthesize(text)
        if result.media_type != "audio/wav":
            raise ValueError("realtime_requires_local_wav")
        with wave.open(io.BytesIO(result.data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                1,
                2,
                24000,
            ) or not 0 < audio.getnframes() <= 1440000:
                raise ValueError("invalid_media_output")
            return audio.readframes(audio.getnframes()), 24000

    async def current(self):
        import asyncio

        return await asyncio.to_thread(state, self.lease)

    async def heartbeat(self):
        import asyncio

        return await asyncio.to_thread(state, self.lease)

    async def close(self):
        import asyncio

        return await asyncio.to_thread(release, self.lease)

    async def submit(self, question_id, text, request_id):
        return await submit_final(self.lease, question_id, text, request_id)

    async def register_audio(self, question_id, text, pcm, rate):
        import asyncio

        return await asyncio.to_thread(
            register_audio, self.lease, question_id, text, pcm, rate
        )

    async def acknowledge(self, audio_id, samples, complete):
        import asyncio

        return await asyncio.to_thread(
            acknowledge, self.lease, audio_id, samples, complete
        )

    async def interrupt_audio(self, audio_id):
        import asyncio

        return await asyncio.to_thread(interrupt_audio, self.lease, audio_id)
