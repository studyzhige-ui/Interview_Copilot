"""One speech operation for local TTS and explicitly selected legacy Edge.

The generated audio format travels with its bytes. An unavailable local model
never falls back to a network provider. Generation is not evidence of playback.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from app.core.config import settings
from app.core.model_policy import require_local_model


@dataclass(frozen=True)
class SynthesizedAudio:
    data: bytes
    media_type: str
    provider: str
    model: str


class TTSService:
    async def synthesize(self, text: str, voice: str | None = None) -> SynthesizedAudio:
        from app.local_inference.synthesis_audio import MAX_TEXT_CHARACTERS, VOICES
        from app.usage import runtime

        if not isinstance(text, str) or len(text) > MAX_TEXT_CHARACTERS:
            raise ValueError("tts_input_capacity")
        text = text.strip()
        provider, model = settings.TTS_PROVIDER, settings.TTS_MODEL
        voice = voice if voice is not None else settings.TTS_DEFAULT_VOICE
        language = settings.TTS_LANGUAGE
        maximum = settings.USAGE_TTS_MAX_BYTES
        if provider not in {"local_qwen3_tts", "edge"}:
            raise ValueError("unsupported_tts_provider")
        is_local = provider == "local_qwen3_tts"
        media_type = "audio/wav" if is_local else "audio/mpeg"
        if not text:
            return SynthesizedAudio(b"", media_type, provider, model)
        require_local_model("tts", is_local=is_local)

        if is_local:
            from app.local_inference.synthesis import (
                SynthesisClient,
                make_synthesis_request,
            )

            client = SynthesisClient(
                model=model, revision=settings.MODEL_REVISIONS_JSON.get(model)
            )
            # Pure validation before usage admission or any model dispatch.
            make_synthesis_request(
                client.binding, text, voice, language, timeout=client.client.timeout
            )

            async def generate():
                audio = await client.synthesize(text, voice, language)
                if len(audio) > maximum:
                    raise ValueError("tts_output_capacity")
                return audio

            identity = {"binding": client.binding, "language": language, "voice": voice}
        else:
            if (
                not isinstance(voice, str)
                or not voice.strip()
                or len(voice) > 100
                or voice in VOICES
            ):
                raise ValueError("invalid_tts_voice")
            # Legacy network synthesis exists only for explicitly configured
            # deployments. Policy rejection above happens before this import.
            import edge_tts
            from app.core.provider_streams import close_provider_stream

            model = voice
            identity = {"voice": voice}

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
            model=model,
            content={"text": text, **identity},
            units=units,
            observed=lambda _: units,
        )
        return SynthesizedAudio(audio, media_type, provider, model)


tts_service = TTSService()
