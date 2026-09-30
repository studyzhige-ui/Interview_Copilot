"""Plain-text transcription for short, single-speaker recordings."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TranscriptionUnavailable(RuntimeError):
    """The configured ASR provider or local model is not ready."""


async def transcribe_short_clip(file_path: str, *, language: str = "zh") -> str:
    """Return plain text for one candidate recording.

    Remote providers stay outside the local ML process. The local path loads
    WhisperX lazily and intentionally skips diarization because a mock-answer
    clip has exactly one speaker.
    """
    from app.media.application import transcription_registry
    from app.core.execution_errors import ModelOutcomeUnknownError

    try:
        return await transcription_registry.transcribe_plain(
            file_path,
            language=language,
        )
    except transcription_registry.LocalProviderOnly:
        pass
    except ModelOutcomeUnknownError:
        # Do not disguise an unconfirmed dispatch/settlement as service downtime.
        raise
    except Exception as exc:  # noqa: BLE001 — provider transport/config failure
        raise TranscriptionUnavailable from exc

    from app.media.application.workers import pool

    # Admission and settlement run inside the real worker. Cancellation of the
    # async waiter cannot close its slot or start a concurrent mutable model.
    return await pool("local").run(_local_clip, file_path, language)


def _local_clip(file_path: str, language: str) -> str:
    from app.media.application import whisperx_engine
    from app.media.application import transcription_registry
    from app.usage import media, runtime

    units = media.audio_units(file_path)
    cfg = transcription_registry.resolve_transcription()

    def transcribe():
        if whisperx_engine.whisper_model is None:
            whisperx_engine.init_whisper_model()
        model = whisperx_engine.whisper_model
        if model is None:
            raise TranscriptionUnavailable("WhisperX model did not initialize")
        import whisperx

        audio = whisperx.load_audio(file_path)
        kwargs = {"batch_size": 8}
        if language and language.lower() != "auto":
            kwargs["language"] = language
        return model.transcribe(audio, **kwargs)

    result = runtime.invoke_sync(
        transcribe,
        observed=lambda _: units,
        **media.descriptor(cfg, file_path, language, units),
    )
    segments = result.get("segments", []) if isinstance(result, dict) else []
    return " ".join(
        (segment.get("text", "") or "").strip() for segment in segments
    ).strip()


__all__ = ["TranscriptionUnavailable", "transcribe_short_clip"]
