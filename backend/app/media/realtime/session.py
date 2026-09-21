"""A bounded realtime conversation controller independent of WebRTC and SQL.

Provisional ASR is ephemeral. Final drafts commit only explicitly or through the
session's explicit hands-free opt-in. Reconnect reads receipts, never replays a
model call. Audio receipts describe browser reports, NOT evidence of hearing.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from typing import Protocol, Callable, Awaitable

from app.core.background_tasks import safe_background_task
from app.media.realtime.vad import VoiceActivity, VoiceEvent, RATE
from app.schemas.realtime import MediaCommand


class MediaApplication(Protocol):
    async def current(self) -> dict: ...
    async def heartbeat(self): ...
    async def close(self): ...
    async def transcribe(self, pcm: bytes) -> str: ...
    async def synthesize(self, text: str) -> tuple[bytes, int]: ...
    async def submit(self, question_id: int, text: str, request_id: str) -> dict: ...
    async def register_audio(
        self, question_id: int, text: str, pcm: bytes, rate: int
    ) -> str: ...
    async def acknowledge(self, audio_id: str, samples: int, complete: bool): ...
    async def interrupt_audio(self, audio_id: str): ...


def speech_chunks(text: str, maximum: int = 180):
    """Preserve every character; prefer punctuation/space without inventing text."""
    if not isinstance(text, str) or not 0 < len(text) <= 16000:
        raise ValueError("speech_text_capacity")
    while text:
        if len(text) <= maximum:
            yield text
            return
        prefix = text[:maximum]
        boundaries = list(re.finditer(r"[。！？!?\n]|[.]\s|\s", prefix))
        cut = (
            boundaries[-1].end()
            if boundaries and boundaries[-1].end() >= maximum // 3
            else maximum
        )
        yield text[:cut]
        text = text[cut:]


class RealtimeSession:
    def __init__(
        self,
        app: MediaApplication,
        emit: Callable[[dict], Awaitable[None]],
        *,
        auto_submit=False,
        threshold=0.015,
        silence_ms=900,
    ):
        self.app, self.emit = app, emit
        self.auto_submit = auto_submit
        self.vad = VoiceActivity(threshold=threshold, silence_ms=silence_ms)
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=3)
        self.asr_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.preview_task = self.speech_task = self.commit_task = None
        self.closed = False
        self.epoch = 0
        self.parts: list[str] = []
        self.draft: tuple[str, str, int] | None = None
        self.question = None
        self.blocked = False
        self.audio_id = None
        self.playback_done: asyncio.Event | None = None
        self.last_preview_samples = 0
        self.preview_revision = 0
        self.finalizing = False
        self.last_command = time.monotonic()
        self.started = time.monotonic()
        self.last_ack = 0

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # All public workers emit safe errors themselves.

        task.add_done_callback(done)
        return task

    async def send(self, **event):
        if not self.closed:
            await self.emit(event)

    async def start(self):
        await self.sync()
        self.spawn(self.consume())
        self.spawn(self.monitor())

    async def sync(self):
        snapshot = await self.app.current()
        question = snapshot["question"]
        if self.question and question and self.question["id"] != question["id"]:
            self.epoch += 1
            self.vad.reset()
            self.parts.clear()
            self.finalizing = False
        self.question = question
        self.blocked = snapshot["answer_pending"]
        await self.send(type="state", **snapshot)

    async def monitor(self):
        try:
            while not self.closed:
                await asyncio.sleep(10)
                if (
                    time.monotonic() - self.last_command > 40
                    or time.monotonic() - self.started > 3600
                ):
                    raise ValueError("media_idle_or_lifetime_limit")
                await self.app.heartbeat()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send(type="error", code="media_session_expired")
            await self.close()

    async def feed(self, frame: bytes):
        if (
            self.closed
            or self.blocked
            or self.draft is not None
            or self.finalizing
            or self.commit_task is not None
        ):
            return
        for event in self.vad.feed(frame):
            if event.kind == "start":
                await self.interrupt()
                await self.send(type="speech_start")
            else:
                self.enqueue(event)
        pcm = self.vad.preview()
        if (
            len(pcm) >= self.last_preview_samples + RATE * 2 * 4
            and not self.asr_lock.locked()
            and self.queue.empty()
            and (self.preview_task is None or self.preview_task.done())
        ):
            self.last_preview_samples = len(pcm)
            self.preview_task = self.spawn(
                self.preview(pcm, self.epoch, self.preview_revision)
            )

    def enqueue(self, event: VoiceEvent):
        if event.kind == "empty":
            return
        self.last_preview_samples = 0
        self.preview_revision += 1
        if event.kind == "final":
            self.finalizing = True
        try:
            self.queue.put_nowait((self.epoch, event))
        except asyncio.QueueFull:
            # Never drop a finalized segment and pretend the answer is complete.
            self.blocked = True
            self.vad.reset()
            self.epoch += 1
            raise ValueError("realtime_asr_backpressure") from None

    async def preview(self, pcm, epoch, revision):
        try:
            async with self.asr_lock:
                text = await self.app.transcribe(pcm)
            if (
                epoch == self.epoch
                and revision == self.preview_revision
                and self.vad.active
                and self.draft is None
            ):
                await self.send(type="partial", text="\n".join([*self.parts, text]))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Preview failure cannot publish partial text or trigger a retry loop.
            await self.send(type="notice", code="preview_unavailable")

    async def consume(self):
        while not self.closed:
            epoch, event = await self.queue.get()
            try:
                if epoch != self.epoch:
                    continue
                text = ""
                if event.pcm:
                    async with self.asr_lock:
                        text = await self.app.transcribe(event.pcm)
                if epoch != self.epoch or self.closed:
                    continue
                if not isinstance(text, str) or len(text) > 16000:
                    raise ValueError("invalid_live_transcription")
                if text.strip():
                    self.parts.append(text.strip())
                final_text = "\n".join(self.parts)
                if len(final_text) > 16000:
                    raise ValueError("live_transcript_capacity")
                if event.kind == "final":
                    self.epoch += 1  # Fence in-flight previews of this utterance.
                    self.parts = []
                    if not final_text.strip():
                        self.finalizing = False
                        await self.send(type="notice", code="no_speech_transcribed")
                        continue
                    self.draft = (str(uuid.uuid4()), final_text, self.question["id"])
                    await self.send(
                        type="final", draft_id=self.draft[0], text=final_text
                    )
                    if self.auto_submit:
                        self.commit(self.draft[0], str(uuid.uuid4()))
                else:
                    await self.send(type="partial", text=final_text)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.blocked = True
                self.epoch += 1
                self.vad.reset()
                self.parts.clear()
                await self.send(type="error", code="transcription_unconfirmed")
            finally:
                self.queue.task_done()

    async def control(self, raw: str):
        if self.closed:
            return
        if not isinstance(raw, str) or len(raw.encode()) > 2048:
            raise ValueError("media_control_capacity")

        # Duplicate JSON keys are not permitted on the control channel.
        def unique(items):
            obj = {}
            for key, value in items:
                if key in obj:
                    raise ValueError("duplicate_media_key")
                obj[key] = value
            return obj

        command = MediaCommand.model_validate(
            json.loads(raw, object_pairs_hook=unique)
        ).checked()
        self.last_command = time.monotonic()
        if command.type == "sync":
            await self.sync()
        elif command.type == "finish_utterance":
            if not self.blocked and not self.draft:
                self.enqueue(self.vad.finish())
        elif command.type == "interrupt":
            await self.interrupt()
        elif command.type == "discard":
            if self.commit_task is None:
                self.epoch += 1
                self.parts.clear()
                self.draft = None
                self.finalizing = False
                self.vad.reset()
                await self.sync()
                await self.send(type="cleared")
        elif command.type == "commit":
            self.commit(command.draft_id, command.request_id)
        elif command.type == "speak":
            if (
                self.question
                and not self.blocked
                and self.commit_task is None
                and not self.vad.active
            ):
                await self.start_speech(self.question)
        elif command.type == "playback":
            if (
                command.audio_id != self.audio_id
                or command.played_samples < self.last_ack
            ):
                raise ValueError("playback_identity_mismatch")
            await self.app.acknowledge(
                command.audio_id, command.played_samples, command.complete
            )
            self.last_ack = command.played_samples
            if command.complete and self.playback_done is not None:
                self.playback_done.set()

    def commit(self, draft_id, request_id):
        if self.closed or self.commit_task is not None:
            return
        if (
            self.draft is None
            or draft_id != self.draft[0]
            or self.question is None
            or self.blocked
            or self.draft[2] != self.question["id"]
        ):
            raise ValueError("live_draft_not_current")
        text = self.draft[1]
        question_id = self.question["id"]
        # This task belongs to the business operation, not the socket lifetime.
        # The existing application records completed/unknown even after disconnect.
        self.commit_task = safe_background_task(
            self.submit(question_id, text, request_id), name="realtime-final-answer"
        )

    async def submit(self, question_id, text, request_id):
        try:
            await self.send(type="submitting", request_id=request_id)
            response = await self.app.submit(question_id, text, request_id)
            self.draft = None
            self.question = response["message"]
            self.finalizing = self.blocked = False
            self.vad.reset()
            await self.send(type="answer", request_id=request_id, **response)
            if not self.closed:
                await self.start_speech(self.question)
        except asyncio.CancelledError:
            self.blocked = True
            raise
        except Exception:
            self.blocked = True
            await self.send(
                type="error", code="answer_unconfirmed", request_id=request_id
            )
        finally:
            self.commit_task = None

    async def interrupt(self):
        task, self.speech_task = self.speech_task, None
        audio_id, self.audio_id = self.audio_id, None
        # Invalidate browser playback first; model cancellation may require cleanup.
        await self.send(type="interrupt")
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if audio_id is not None:
            await self.app.interrupt_audio(audio_id)
        self.playback_done = None

    async def start_speech(self, question):
        await self.interrupt()
        self.speech_task = self.spawn(self.speak(question))

    async def speak(self, question):
        pending = None
        try:
            chunks = iter(speech_chunks(question["text"]))
            part = next(chunks)
            pending = asyncio.create_task(self.app.synthesize(part))
            while True:
                pcm, rate = await pending
                following = next(chunks, None)
                pending = (
                    asyncio.create_task(self.app.synthesize(following))
                    if following is not None
                    else None
                )
                if self.closed:
                    return
                self.audio_id = await self.app.register_audio(
                    question["id"], part, pcm, rate
                )
                audio_id = self.audio_id
                self.last_ack = 0
                self.playback_done = asyncio.Event()
                await self.send(
                    type="audio_start",
                    audio_id=audio_id,
                    rate=rate,
                    samples=len(pcm) // 2,
                    sha256=hashlib.sha256(pcm).hexdigest(),
                )
                for offset in range(0, len(pcm), 12288):
                    await self.send(
                        type="audio",
                        audio_id=audio_id,
                        offset=offset // 2,
                        pcm=base64.b64encode(pcm[offset : offset + 12288]).decode(
                            "ascii"
                        ),
                    )
                await self.send(type="audio_end", audio_id=audio_id)
                await asyncio.wait_for(
                    self.playback_done.wait(), len(pcm) / (rate * 2) + 15
                )
                self.audio_id = None
                if following is None:
                    break
                part = following
            await self.send(type="speech_done")
        except asyncio.CancelledError:
            raise
        except Exception:
            audio_id, self.audio_id = self.audio_id, None
            if audio_id is not None:
                await self.app.interrupt_audio(audio_id)
            await self.send(type="interrupt")
            await self.send(type="notice", code="speech_unavailable")
        finally:
            if pending is not None:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.epoch += 1
        self.vad.reset()
        self.parts.clear()
        self.draft = None
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        tasks = [task for task in self.tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.app.close()
