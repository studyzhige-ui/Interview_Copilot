"""Bounded provisional and final recognition through the existing WhisperX path."""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from app.core.config import settings
from app.local_inference.audio import MAX_PCM_BYTES, SAMPLE_RATE


def _local_pcm(pcm):
    # The worker owns its temporary input through completion, even if its async
    # waiter is cancelled. The existing local clip path owns model/accounting.
    from app.media.application.short_clip_transcription import _local_clip

    with tempfile.TemporaryDirectory(prefix="copilot-live-asr-") as directory:
        path = Path(directory) / "window.wav"
        with wave.open(str(path), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(SAMPLE_RATE)
            audio.writeframes(pcm)
        return _local_clip(str(path), "auto")


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
        return await pool("local").run(_local_pcm, pcm)

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
