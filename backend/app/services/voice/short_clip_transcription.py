"""Plain-text transcription for short, single-speaker recordings."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# The shared FasterWhisper pipeline mutates tokenizer/options during a call.
# Serialising local requests prevents concurrent clips from corrupting it.
_whisper_lock = asyncio.Lock()


class TranscriptionUnavailable(RuntimeError):
    """The configured ASR provider or local model is not ready."""


async def transcribe_short_clip(file_path: str, *, language: str = "zh") -> str:
    """Return plain text for one candidate recording.

    Remote providers stay outside the local ML process. The local path loads
    WhisperX lazily and intentionally skips diarization because a mock-answer
    clip has exactly one speaker.
    """
    from app.services.voice import transcription_registry

    try:
        return await transcription_registry.transcribe_plain(
            file_path,
            language=language,
        )
    except transcription_registry.LocalProviderOnly:
        pass
    except Exception as exc:  # noqa: BLE001 — provider transport/config failure
        raise TranscriptionUnavailable from exc

    from app.services.voice import whisperx_engine

    if whisperx_engine.whisper_model is None:
        async with _whisper_lock:
            if whisperx_engine.whisper_model is None:
                try:
                    await asyncio.to_thread(whisperx_engine.init_whisper_model)
                except Exception as exc:  # noqa: BLE001
                    logger.error("WhisperX initialization failed: %s", exc)
                    raise TranscriptionUnavailable from exc

    model = whisperx_engine.whisper_model
    if model is None:
        raise TranscriptionUnavailable("WhisperX model did not initialize")

    import whisperx  # type: ignore

    audio = await asyncio.to_thread(whisperx.load_audio, file_path)
    kwargs: dict = {"batch_size": 8}
    if language and language.lower() != "auto":
        kwargs["language"] = language
    async with _whisper_lock:
        result = await asyncio.to_thread(
            model.transcribe,
            audio,
            **kwargs,
        )
    segments = result.get("segments", []) if isinstance(result, dict) else []
    return " ".join(
        (segment.get("text", "") or "").strip() for segment in segments
    ).strip()


__all__ = ["TranscriptionUnavailable", "transcribe_short_clip"]
