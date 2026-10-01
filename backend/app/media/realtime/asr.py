"""Incremental bounded-window ASR adapter over the existing broker.

This adapter re-decodes provisional windows; it is not native stateful Qwen
streaming. Final text is computed from the complete retained turn, not partials.
"""

from __future__ import annotations

import hashlib
from app.core.config import settings
from app.local_inference.audio import AUDIO_OUTPUT_TOKENS, MAX_PCM_BYTES, SAMPLE_RATE
from app.local_inference.client import (
    Client,
    configured_socket_path,
    make_audio_request,
)
from app.local_inference.config import binding_for
from app.usage import runtime


class LiveASR:
    def __init__(self):
        if settings.TRANSCRIPTION_PROVIDER != "local_qwen_asr":
            raise ValueError("realtime_requires_local_qwen_asr")
        self.model = settings.TRANSCRIPTION_MODEL
        self.binding = binding_for(
            "transcription",
            self.model,
            settings.MODEL_REVISIONS_JSON.get(self.model),
            1,
            AUDIO_OUTPUT_TOKENS,
        )
        self.client = Client(
            configured_socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )

    async def window(self, pcm: bytes) -> str:
        request = make_audio_request(
            "transcription",
            self.binding,
            pcm,
            language=None,
            priority="interactive",
            timeout=self.client.timeout,
        )
        units = {
            "requests": 1,
            "audio_ms": (len(pcm) * 1000 + SAMPLE_RATE * 2 - 1) // (SAMPLE_RATE * 2),
        }
        result = await runtime.invoke_async(
            lambda: self.client.acall(request, dimension=1),
            meter="transcription",
            provider="local_qwen_asr",
            model=self.model,
            content={
                "binding": self.binding,
                "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
            },
            units=units,
            observed=lambda _: units,
        )
        return result["text"].strip()

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
