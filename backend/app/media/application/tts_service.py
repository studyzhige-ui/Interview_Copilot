"""Text-to-Speech using the third-party edge-tts client (not an Azure SLA).

Converts text to mp3 audio bytes. Used by the mock interview voice pipeline
to let the AI interviewer "speak" questions aloud.
"""

import io
import logging

import edge_tts

from app.core.config import settings
from app.core.model_policy import require_local_model

logger = logging.getLogger(__name__)

DEFAULT_VOICE = getattr(settings, "TTS_DEFAULT_VOICE", "zh-CN-YunxiNeural")


class TTSService:
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
    ) -> bytes:
        """Synthesize text to mp3 bytes using edge-tts.

        Args:
            text: The text to convert to speech.
            voice: TTS voice name. Defaults to zh-CN-YunxiNeural (male).
                   Other good options: zh-CN-XiaoxiaoNeural (female).

        Returns:
            mp3 audio bytes.
        """
        if not isinstance(text, str) or len(text) > 100_000:
            raise ValueError("tts_input_capacity")
        voice = voice or DEFAULT_VOICE
        if not text.strip():
            return b""

        require_local_model("tts", is_local=False)
        from app.usage import runtime
        from app.core.provider_streams import close_provider_stream

        async def generate():
            communicate = edge_tts.Communicate(text.strip(), voice)
            stream = communicate.stream()
            buffer = io.BytesIO()
            try:
                async for chunk in stream:
                    if chunk["type"] == "audio":
                        if (
                            buffer.tell() + len(chunk["data"])
                            > settings.USAGE_TTS_MAX_BYTES
                        ):
                            raise ValueError("tts_output_capacity")
                        buffer.write(chunk["data"])
                return buffer.getvalue()
            finally:
                await close_provider_stream(stream)
                buffer.close()

        units = {"requests": 1, "characters": len(text.strip())}
        audio_bytes = await runtime.invoke_async(
            generate,
            meter="speech",
            provider="edge",
            model=voice,
            content={"text": text.strip()},
            units=units,
            observed=lambda _: units,
        )
        logger.debug(
            "TTS synthesized %d bytes for %d chars", len(audio_bytes), len(text)
        )
        return audio_bytes


tts_service = TTSService()


__all__ = ["TTSService", "tts_service", "DEFAULT_VOICE"]
