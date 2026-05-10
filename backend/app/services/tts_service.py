"""Text-to-Speech service using edge-tts (Microsoft free TTS).

Converts text to mp3 audio bytes. Used by the mock interview voice pipeline
to let the AI interviewer "speak" questions aloud.
"""

import io
import logging

import edge_tts

from app.core.config import settings

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
        voice = voice or DEFAULT_VOICE
        if not text.strip():
            return b""

        communicate = edge_tts.Communicate(text.strip(), voice)
        buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        audio_bytes = buffer.getvalue()
        logger.debug("TTS synthesized %d bytes for %d chars", len(audio_bytes), len(text))
        return audio_bytes


tts_service = TTSService()
