"""Bounded synthesis through the existing explicitly selected Edge provider.

Synthesis is disabled by default. Removing a local model never selects a network
provider automatically. Generated MP3 bytes do not certify actual playback.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.core.config import settings
from app.core.model_policy import require_local_model

MAX_TEXT_CHARACTERS = 600


@dataclass(frozen=True)
class SynthesizedAudio:
    data: bytes
    media_type: str
    provider: str
    model: str


class TTSService:
    async def synthesize(self, text: str, voice: str | None = None) -> SynthesizedAudio:
        from app.usage import runtime

        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARACTERS:
            raise ValueError("tts_input_capacity")
        text = text.strip()
        provider = settings.TTS_PROVIDER
        voice = voice if voice is not None else settings.TTS_DEFAULT_VOICE
        maximum = settings.USAGE_TTS_MAX_BYTES
        if provider != "edge":
            raise ValueError("tts_disabled_or_unsupported")
        if not isinstance(voice, str) or not re.fullmatch(
            r"[a-z]{2,3}-[A-Z]{2}-[A-Za-z][A-Za-z0-9]*Neural", voice
        ):
            raise ValueError("invalid_tts_voice")
        if not text:
            return SynthesizedAudio(b"", "audio/mpeg", provider, voice)
        require_local_model("tts", is_local=False)
        import edge_tts
        from app.core.provider_streams import close_provider_stream

        async def generate():
            stream = edge_tts.Communicate(text, voice).stream()
            buffer = io.BytesIO()
            try:
                async for chunk in stream:
                    if chunk["type"] == "audio":
                        if buffer.tell() + len(chunk["data"]) > maximum:
                            raise ValueError("tts_output_capacity")
                        buffer.write(chunk["data"])
                audio = buffer.getvalue()
                if not audio:
                    raise ValueError("tts_empty_audio")
                return audio
            finally:
                await close_provider_stream(stream)
                buffer.close()

        units = {"requests": 1, "characters": len(text)}
        audio = await runtime.invoke_async(
            generate,
            meter="speech",
            provider=provider,
            model=voice,
            content={"text": text, "voice": voice},
            units=units,
            observed=lambda _: units,
        )
        return SynthesizedAudio(audio, "audio/mpeg", provider, voice)


tts_service = TTSService()
