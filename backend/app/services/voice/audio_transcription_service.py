"""Provider-neutral entry point for long-form audio transcription."""

import logging

from app.services.voice.transcription_registry import resolve_transcription, transcribe

logger = logging.getLogger(__name__)


async def transcribe_media(file_path: str, language: str = "zh") -> str:
    """Transcribe media with the configured provider and speaker labeling."""
    config = resolve_transcription()
    try:
        logger.info(
            "Transcribing %s via provider=%s model=%s language=%s",
            file_path,
            config.provider_id,
            config.model,
            language,
        )
        text = await transcribe(file_path, language=language)
        logger.info("Transcription completed (%d chars).", len(text))
        return text
    except Exception:
        logger.exception("Transcription failed via provider=%s", config.provider_id)
        raise


__all__ = ["transcribe_media"]
