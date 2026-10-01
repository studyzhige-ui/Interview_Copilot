"""Provider-neutral entry point for long-form audio transcription."""

import logging

from app.media.application.transcription_registry import ResolvedTranscription
from app.media.application.transcription_registry import resolve_transcription
from app.media.application.transcript_evidence import TranscriptEvidence
from app.media.application.transcription_registry import transcribe

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
    config: ResolvedTranscription | None = None,
) -> TranscriptEvidence:
    """Produce complete evidence with a frozen provider and captured source.

    Resolve capability before file I/O or usage admission. The worker owns
    both capture and model execution, including after waiter cancellation.
    """
    from app.media.application.evidence_pipeline import resolve_evidence_collector
    from app.media.application.workers import pool

    config = config if config is not None else resolve_transcription()
    collector = resolve_evidence_collector(config.provider.kind)
    return await pool("local").run(
        _collect_evidence,
        file_path,
        file_asset_id=file_asset_id,
        file_asset_version=file_asset_version,
        language=language,
        config=config,
        collector=collector,
    )


def _collect_evidence(
    file_path, *, file_asset_id, file_asset_version, language, config, collector
):
    from app.core.config import settings
    from app.media.application.evidence_pipeline import compose_transcript_evidence
    from app.media.application.evidence_source import capture_evidence_source
    from app.usage import media, runtime

    with capture_evidence_source(
        file_path,
        file_asset_id=file_asset_id,
        file_asset_version=file_asset_version,
        max_bytes=settings.USAGE_AUDIO_MAX_BYTES,
    ) as source:
        units = media.audio_units(source.path)
        descriptor = media.descriptor(config, source.path, language, units)
        return runtime.invoke_sync(
            lambda: compose_transcript_evidence(
                source,
                collector(source.path, model=config.model, language=language),
                max_duration_ms=settings.USAGE_AUDIO_MAX_MS,
            ),
            observed=lambda _: units,
            **descriptor,
        )


__all__ = ["transcribe_interview_evidence", "transcribe_media"]
