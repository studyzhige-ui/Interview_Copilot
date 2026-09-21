"""A live connection owns audio, provisional text and playback, not interviews.

Only explicit commit of the final draft calls the injected application boundary.
Reconnect asks that boundary for canonical state. No partial or timeout is an
answer; no catch/reconnect path resubmits a model request.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
import uuid
from contextlib import suppress

from app.core.bounded_work import BoundedWorkPool
from .detection import SAMPLE_RATE, SpeechGate
from .playback import Playback, pcm_from_wav, sentences


class MediaSession:
    def __init__(self, *, config, services, detectors, send, connection_id=None):
        self.config, self.services, self.detectors, self.send = (
            config,
            services,
            detectors,
            send,
        )
        self.id = connection_id or str(uuid.uuid4())
        self.cpu = BoundedWorkPool("live-detectors", workers=2, queue_size=2)
        self.gate = SpeechGate(config.speech_threshold, config.silence_ms)
        self.audio = bytearray()
        self.phase = "connecting"
        self.draft = None
        self.question_id = None
        self.utterance = 0
        self.sequence = 0
        self.closed = False
        self.last_ping = self.created = time.monotonic()
        self.partial = self.endpoint = self.finalizing = self.answering = (
            self.speaking
        ) = None
        self.playback = None
        self.playback_ack = asyncio.Event()
        self.tasks = set()
        self.last_partial = self.last_endpoint = 0

    def task(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)

        def done(finished):
            self.tasks.discard(finished)
            if not finished.cancelled():
                finished.exception()  # Exceptions are handled at the owning boundary.

        task.add_done_callback(done)
        return task

    async def emit(self, kind, **fields):
        if self.closed:
            return
        self.sequence += 1
        await self.send(
            {"type": kind, "connection_id": self.id, "seq": self.sequence, **fields}
        )

    async def open(self):
        state = await self.services.state()
        self.question_id = state["question_message_id"]
        self.phase = "listening" if state.get("can_listen", True) else "blocked"
        await self.emit("state", question_message_id=self.question_id, phase=self.phase)
        self.task(self.watchdog())

    async def watchdog(self):
        try:
            while not self.closed:
                await asyncio.sleep(10)
                if (
                    time.monotonic() - self.created > self.config.session_seconds
                    or time.monotonic() - self.last_ping > 35
                ):
                    await self.emit("error", code="media_session_expired")
                    await self.close()
                    return
                await self.services.authorize()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.emit("error", code="media_authorization_lost")
            await self.close()

    async def feed(self, pcm):
        if self.closed or self.phase != "listening":
            return
        started, retained = self.gate.feed(
            pcm, await self.cpu.run(self.detectors.speech, pcm)
        )
        if started:
            self.utterance += 1
            self.last_partial = self.last_endpoint = 0
            await self.interrupt()
            await self.emit("speech.start", utterance=self.utterance)
        self.audio.extend(retained)
        if len(self.audio) > self.config.max_turn_seconds * SAMPLE_RATE * 2:
            await self.block("turn_capacity_exceeded")
            return
        now = len(self.audio) // 2
        if (
            now - self.last_partial >= self.config.partial_seconds * SAMPLE_RATE
            and not self.running(self.partial)
        ):
            self.last_partial = now
            self.partial = self.task(
                self.provisional(
                    bytes(self.audio[-30 * SAMPLE_RATE * 2 :]), self.utterance
                )
            )
        if (
            self.gate.may_end
            and now - self.last_endpoint >= SAMPLE_RATE // 2
            and not self.running(self.endpoint)
        ):
            self.last_endpoint = now
            self.endpoint = self.task(
                self.consider_end(
                    bytes(self.audio[-8 * SAMPLE_RATE * 2 :]),
                    self.gate.version,
                    self.utterance,
                )
            )

    @staticmethod
    def running(task):
        return task is not None and not task.done()

    async def provisional(self, pcm, utterance):
        try:
            text = await self.services.partial(pcm)
            if self.phase == "listening" and self.utterance == utterance:
                await self.emit("transcript.partial", text=text, utterance=utterance)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Partial failure never becomes final text or switches providers.
            await self.emit("notice", code="partial_unavailable")

    async def consider_end(self, pcm, version, utterance):
        try:
            score = await self.cpu.run(self.detectors.ended, pcm)
            if (
                self.phase == "listening"
                and self.utterance == utterance
                and self.gate.version == version
                and self.gate.may_end
                and score >= self.config.endpoint_threshold
            ):
                self.finish()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.block("endpoint_unavailable")

    def finish(self):
        if self.closed or self.phase != "listening" or not self.gate.active:
            return
        # Change state synchronously, before a second command/frame can enter.
        self.phase = "finalizing"
        if self.running(self.partial):
            self.partial.cancel()
        self.finalizing = self.task(self.finalize(bytes(self.audio)))

    async def finalize(self, pcm):
        try:
            await self.emit("phase", phase=self.phase)
            if self.partial:
                await asyncio.gather(self.partial, return_exceptions=True)
            text = await self.services.final(pcm)
            if not isinstance(text, str) or not text.strip() or len(text) > 16000:
                raise ValueError("final_transcript_invalid")
            self.draft = {
                "request_id": str(uuid.uuid4()),
                "question_message_id": self.question_id,
                "text": text,
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
            }
            self.audio.clear()
            self.gate.reset()
            self.phase = "awaiting_commit"
            await self.emit("transcript.final", **self.draft)
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.block("final_transcription_failed")

    async def control(self, command):
        if self.closed or command.connection_id != self.id:
            return
        action = command.action
        if action == "ping":
            self.last_ping = time.monotonic()
        elif action == "interrupt":
            await self.interrupt()
        elif action == "finish":
            self.finish()
        elif action == "discard" and self.phase in {
            "listening",
            "awaiting_commit",
            "blocked",
        }:
            self.utterance += 1
            for task in (self.partial, self.endpoint):
                if self.running(task):
                    task.cancel()
            self.audio.clear()
            self.draft = None
            self.gate.reset()
            state = await self.services.state()
            self.question_id = state["question_message_id"]
            self.phase = "listening" if state.get("can_listen", True) else "blocked"
            await self.emit("phase", phase=self.phase)
        elif action == "commit" and self.phase == "awaiting_commit":
            if command.request_id != self.draft["request_id"]:
                raise ValueError("stale_media_commit")
            self.phase = "answering"
            self.answering = self.task(self.commit(dict(self.draft)))
        elif (
            action == "ack"
            and self.playback
            and command.playback_id == self.playback.id
        ):
            self.playback.acknowledge(command.samples)
            self.playback_ack.set()
        elif (
            action == "play_question"
            and self.phase == "listening"
            and not self.gate.active
        ):
            state = await self.services.state()
            message = next(
                (
                    m
                    for m in reversed(state["messages"])
                    if m["speaker"] == "interviewer"
                ),
                None,
            )
            if message:
                await self.start_speaking(message)

    async def commit(self, draft):
        try:
            await self.emit("phase", phase=self.phase, request_id=draft["request_id"])
            result = await self.services.commit(draft)
            self.question_id = result["message"]["id"]
            self.draft = None
            self.phase = "listening"
            await self.emit(
                "answer.completed", request_id=draft["request_id"], **result
            )
            await self.start_speaking(result["message"])
        except asyncio.CancelledError:
            raise
        except Exception:
            # The application may have committed Phase A. A new connection
            # reads its durable receipt rather than submitting this draft again.
            self.phase = "blocked"
            await self.emit("answer.unconfirmed", request_id=draft["request_id"])

    async def start_speaking(self, message):
        await self.interrupt()
        self.speaking = self.task(self.speak(message))

    async def interrupt(self):
        if self.running(self.speaking):
            self.speaking.cancel()
            await self.emit("audio.cancel")
            await asyncio.gather(self.speaking, return_exceptions=True)
        self.playback = None

    async def speak(self, message):
        playback = Playback(str(uuid.uuid4()), message["id"])
        self.playback = playback
        status = "interrupted"
        try:
            for text in sentences(message["text"]):
                pcm = pcm_from_wav(await self.services.synthesize(text))
                playback.generated += len(pcm) // 2
                if playback.generated > 24_000 * 600:
                    raise ValueError("playback_capacity")
                start = playback.delivered
                self.playback_ack.clear()
                await self.emit(
                    "audio.start",
                    playback_id=playback.id,
                    offset=start,
                    samples=len(pcm) // 2,
                    sample_rate=24000,
                )
                for offset in range(0, len(pcm), 12_000):
                    part = pcm[offset : offset + 12_000]
                    await self.emit(
                        "audio.data",
                        playback_id=playback.id,
                        data=base64.b64encode(part).decode("ascii"),
                    )
                    playback.delivered += len(part) // 2
                await self.emit(
                    "audio.end", playback_id=playback.id, samples=playback.delivered
                )
                # At most one complete sentence is buffered by the browser.
                async with asyncio.timeout(len(pcm) / 48000 + 15):
                    while playback.reported < playback.delivered:
                        await self.playback_ack.wait()
                        self.playback_ack.clear()
            status = "completed"
        except asyncio.CancelledError:
            raise
        except Exception:
            status = "failed"
            await self.emit("audio.cancel")
            await self.emit("notice", code="local_speech_unavailable")
        finally:
            # A client report is not proof of human perception. Save the actual
            # generated, sent and client-reported counters separately.
            with suppress(Exception):
                await self.services.playback(playback.snapshot(status))
            if self.playback is playback:
                self.playback = None

    async def block(self, code):
        self.phase = "blocked"
        for task in (self.partial, self.endpoint):
            if self.running(task) and task is not asyncio.current_task():
                task.cancel()
        self.audio.clear()
        self.gate.reset()
        await self.emit("error", code=code)

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.phase = "closed"
        self.audio.clear()
        self.draft = None
        current = asyncio.current_task()
        tasks = [task for task in self.tasks if task is not current]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.cpu.shutdown()
