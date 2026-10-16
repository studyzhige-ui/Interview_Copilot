"""Bounded provisional and final recognition through the existing WhisperX path."""

from __future__ import annotations

import uuid
from app.core.config import settings
from app.local_inference.audio import MAX_PCM_BYTES, pcm_payload


class LiveASR:
    def __init__(self):
        if settings.TRANSCRIPTION_PROVIDER != "local_whisperx":
            raise ValueError("realtime_requires_local_whisperx")

    async def window(self, pcm: bytes) -> str:
        from app.media.application.workers import pool

        if (
            not isinstance(pcm, bytes)
            or not 0 < len(pcm) <= MAX_PCM_BYTES
            or len(pcm) % 2
        ):
            raise ValueError("invalid_pcm_size")
        if settings.TRANSCRIPTION_PROVIDER != "local_whisperx":
            raise ValueError("realtime_requires_local_whisperx")
        from app.task_queue.dispatch import dispatch_live_audio
        from app.usage.runtime import current

        actor = current()
        result = dispatch_live_audio(
            pcm_payload(pcm), actor.user_id, f"{actor.operation_id}:{uuid.uuid4().hex}"
        )

        def receive():
            try:
                return result.get(timeout=120, interval=0.1)
            finally:
                result.forget()

        return await pool("probe").run(receive)

    async def final(self, pcm: bytes) -> str:
        parts = []
        total = 0
        for offset in range(0, len(pcm), MAX_PCM_BYTES):
            part = await self.window(pcm[offset : offset + MAX_PCM_BYTES])
            total += len(part)
            if total > 16000:
                raise ValueError("realtime_transcript_capacity")
            if part:
                parts.append(part)
        return "\n".join(parts)
