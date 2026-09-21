"""Application-facing local synthesis; no SDK import or automatic provider retry."""

from __future__ import annotations

import io
import uuid
import wave

from app.core.config import settings
from .client import Client, configured_socket_path
from .config import binding_for
from .protocol import VERSION, request
from .synthesis_audio import SAMPLE_RATE, SYNTHESIS_TOKENS, decode_synthesis_result


def make_synthesis_request(binding, text, voice, language, *, timeout=120):
    return request(
        {
            "version": VERSION,
            "id": uuid.uuid4().hex,
            "role": "synthesis",
            "binding": binding,
            "operation": "synthesize",
            "text": text,
            "voice": voice,
            "language": language,
            "priority": "interactive",
            "timeout": timeout,
        }
    )


class SynthesisClient:
    def __init__(self, *, model: str, revision=None, client=None):
        self.binding = binding_for("synthesis", model, revision, 1, SYNTHESIS_TOKENS)
        self.client = client or Client(
            configured_socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )

    async def synthesize(self, text: str, voice: str, language: str) -> bytes:
        task = make_synthesis_request(
            self.binding, text, voice, language, timeout=self.client.timeout
        )
        value = await self.client.acall(task, dimension=1)
        pcm = decode_synthesis_result(task, value)
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(SAMPLE_RATE)
                output.writeframes(pcm)
            return buffer.getvalue()
