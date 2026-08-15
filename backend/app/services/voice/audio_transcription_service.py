"""Provider-neutral entry point for long-form audio transcription."""

import asyncio
import logging

from app.services.voice.transcription_registry import resolve_transcription, transcribe

logger = logging.getLogger(__name__)


async def transcribe_media(file_path: str, language: str | None = "zh") -> str:
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


async def transcribe_interview_evidence(
    file_path: str,
    *,
    file_asset_id: str,
    file_asset_version: str,
    language: str | None = "zh",
):
    """Produce auditable word evidence for interview review.

    Generic document transcription may return text only. Interview QA cannot:
    a provider without forced-aligned words and exclusive diarization is a
    typed deployment limitation, not a reason to fall back to text guessing.
    """

    config = resolve_transcription()
    if config.provider.kind != "local_whisperx":
        raise RuntimeError(
            "interview_evidence_provider_unsupported: configure the dedicated "
            "local_whisperx analysis worker"
        )
    from app.services.voice.whisperx_engine import run_interview_evidence_sync

    return await asyncio.to_thread(
        run_interview_evidence_sync,
        file_path,
        file_asset_id=file_asset_id,
        file_asset_version=file_asset_version,
        language=language,
    )


__all__ = ["transcribe_interview_evidence", "transcribe_media"]
