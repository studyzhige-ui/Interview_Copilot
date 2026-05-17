"""Audio transcription service.

Two independent axes:

  * **Transcription** (ASR) — selected by ``TRANSCRIPTION_PROFILE_ID`` via
    ``transcription_registry``. Local WhisperX OR a remote OpenAI-style
    /v1/audio/transcriptions endpoint.
  * **Diarization** (speaker separation) — Pyannote, selected by
    ``DIARIZATION_MODE``:
        ``auto``     — load when ASR is local-whisperx (whisperx bundles it
                       and we feed it the same audio); off when ASR is remote.
        ``pyannote`` — force load. Hybrid mode: remote ASR returns word
                       timestamps, local Pyannote labels speakers, we align.
        ``none``     — never load. Transcripts are single-speaker.

The public surface (``init_whisper_model``, ``transcribe_media``) is kept
the same so existing callers (Celery worker bootstrap, analysis pipeline)
don't need updates.
"""

import asyncio
import logging
from typing import Any, Optional

import torch

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot

logger = logging.getLogger(__name__)

# Module-level singletons. Each is independently populated; ``whisper_model``
# only when local-whisperx is the active ASR profile, ``diarize_model`` when
# DIARIZATION_MODE allows it. Remote-mode workers leave both as ``None``.
whisper_model = None
diarize_model = None


# ── Decisions ──────────────────────────────────────────────────────────


def _is_local_asr_active() -> bool:
    return (settings.TRANSCRIPTION_PROVIDER or "local_whisperx").strip().lower() == "local_whisperx"


def _should_load_diarization() -> bool:
    """Return True if Pyannote should be loaded into this worker process."""
    mode = (settings.DIARIZATION_MODE or "auto").strip().lower()
    if mode == "none":
        return False
    if mode == "pyannote":
        return True   # hybrid mode forces load
    # mode == "auto"
    return _is_local_asr_active()


# ── Loaders ────────────────────────────────────────────────────────────


def _init_whisper_only():
    """Load WhisperX into ``whisper_model``. No-op if already loaded / not needed."""
    global whisper_model
    if whisper_model is not None:
        return
    if not _is_local_asr_active():
        return  # remote ASR active → no WhisperX needed

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    logger.info(f"WhisperX 加载：device={device.upper()} compute={compute_type}")

    hf_cache_dir = prepare_hf_runtime()
    # TRANSCRIPTION_MODEL doubles as the local-whisperx HF id (faster-whisper
    # CTranslate2 weights live there). Resolve to the on-disk snapshot first
    # so we never fall through to a network download at request time.
    whisper_id = (settings.TRANSCRIPTION_MODEL or "Systran/faster-whisper-large-v3").strip()
    local_whisper_path = resolve_local_snapshot(whisper_id)
    if local_whisper_path is None:
        from app.core.hf_runtime import format_missing_model_error
        raise RuntimeError(
            format_missing_model_error(
                model_id=whisper_id,
                role="WhisperX ASR",
                filter_substring="whisper",
                fix_hint="python scripts/init_models.py --only whisper",
            )
        )
    import whisperx
    whisper_model = whisperx.load_model(
        local_whisper_path,
        device,
        compute_type=compute_type,
        download_root=str(hf_cache_dir),
        local_files_only=True,
    )
    logger.info("WhisperX ready.")


def _init_diarize_only():
    """Load Pyannote into ``diarize_model``. No-op if already loaded / not needed.

    Independent from WhisperX so hybrid mode (remote ASR + local diarization)
    can opt in just to Pyannote without forcing a WhisperX download.
    """
    global diarize_model
    if diarize_model is not None:
        return
    if not _should_load_diarization():
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    prepare_hf_runtime()
    diarization_model_path = resolve_local_snapshot(settings.DIARIZATION_MODEL_ID)
    if diarization_model_path is None:
        from app.core.hf_runtime import format_missing_model_error
        raise RuntimeError(
            format_missing_model_error(
                model_id=settings.DIARIZATION_MODEL_ID,
                role="Diarization",
                filter_substring="diariz",
                fix_hint="python scripts/init_models.py --only diarization",
            )
        )
    # whisperx.diarize.DiarizationPipeline is a thin wrapper around the real
    # pyannote pipeline — using it here means we get the same speaker label
    # format as the pure-local path, so downstream alignment / formatting
    # code is identical regardless of which ASR produced the words.
    from whisperx.diarize import DiarizationPipeline
    diarize_model = DiarizationPipeline(
        model_name=diarization_model_path,
        device=device,
    )
    logger.info("Pyannote diarization ready (mode=%s).", settings.DIARIZATION_MODE)


def init_whisper_model():
    """Load whichever local models the current config needs.

    Called from the Celery ``worker_process_init`` signal so each worker
    pays the cold-load cost once at startup, not on the first request.
    The function is conservative: if the active profile is fully remote
    AND DIARIZATION_MODE != 'pyannote', this is a complete no-op.
    """
    if not _is_local_asr_active() and not _should_load_diarization():
        logger.info(
            "Voice models: ASR remote (%s) and diarization off — nothing to load.",
            settings.TRANSCRIPTION_PROVIDER,
        )
        return
    if _is_local_asr_active():
        try:
            _init_whisper_only()
        except Exception as exc:
            # Local WhisperX is part of the configured stack — fail loud
            # so the operator notices the model is missing / mis-named
            # and either downloads it or switches TRANSCRIPTION_PROVIDER
            # to a remote one. Silently degrading hides config drift.
            logger.error("WhisperX load failed: %s", exc)
            raise
    if _should_load_diarization():
        try:
            _init_diarize_only()
        except Exception as exc:
            # Hybrid mode is opt-in — if Pyannote can't load, downgrade to
            # single-speaker rather than failing the whole worker.
            logger.warning(
                "Pyannote load failed; diarization disabled for this worker: %s",
                exc,
            )


# ── Local-only synchronous pipeline (used by registry's local profile) ─


def _run_whisperx_sync(file_path: str, language: str | None = "zh") -> str:
    """WhisperX + Pyannote pipeline. Returns markdown with speaker prefixes.

    ``language`` is a WhisperX language hint. Forcing the language is the
    single most effective accuracy boost for monolingual audio because
    Whisper's auto-detect is occasionally wrong on short clips. Pass
    ``None`` (or ``"auto"``) to let Whisper detect per clip.
    """
    if not whisper_model:
        raise RuntimeError(
            "Local WhisperX is not loaded. Either set TRANSCRIPTION_PROFILE_ID="
            "local-whisperx and let the worker init load it, or pick a remote "
            "profile."
        )
    if whisper_model == "mock_model":
        return (
            "**[Speaker 1]**: 请问你的项目难点是什么？\n\n"
            "**[Speaker 2]**: 难点在于高并发处理下，分布式锁发生脑裂的情况。\n\n"
            "**[Speaker 1]**: 你是怎么解决的？\n\n"
            "**[Speaker 2]**: 我采用了 Redisson 的看门狗机制。"
        )

    import whisperx

    audio = whisperx.load_audio(file_path)
    # WhisperX raises if we pass an unknown string, so map "auto" → None.
    effective_lang = None if (language or "").strip().lower() in {"", "auto"} else language
    kwargs: dict = {"batch_size": 16}
    if effective_lang:
        kwargs["language"] = effective_lang
    result = whisper_model.transcribe(audio, **kwargs)
    if diarize_model is not None:
        diarize_segments = diarize_model(audio, min_speakers=2, max_speakers=2)
        result = whisperx.assign_word_speakers(diarize_segments, result)
    return _segments_to_markdown(result.get("segments", []))


# ── Hybrid path: align remote-ASR words with local Pyannote speakers ──


def align_remote_words_with_local_diarization(
    file_path: str,
    asr_segments: list[dict[str, Any]],
) -> str:
    """Return speaker-labelled markdown for a remote ASR result.

    ``asr_segments`` follows the OpenAI ``verbose_json`` shape: a list of
    ``{"start", "end", "text", "words": [{"word", "start", "end"}, ...]}``.
    We feed the raw audio to Pyannote, then use whisperx's
    ``assign_word_speakers`` to label each word, and finally collapse
    consecutive same-speaker words into a single ``**[Speaker]**:`` line.

    If diarization isn't loaded for this worker (DIARIZATION_MODE=none, or
    Pyannote model missing) we degrade to single-speaker output instead of
    raising.
    """
    if diarize_model is None:
        logger.info(
            "Hybrid diarization requested but diarize_model not loaded; "
            "returning single-speaker output."
        )
        flat = " ".join(seg.get("text", "").strip() for seg in asr_segments).strip()
        return f"**[Speaker 1]**: {flat}" if flat else ""

    import whisperx

    audio = whisperx.load_audio(file_path)
    diarize_segments = diarize_model(audio, min_speakers=2, max_speakers=2)
    # whisperx.assign_word_speakers wants a dict with "segments" containing
    # word-level entries. The OpenAI verbose_json shape is already close —
    # word entries use "word"/"start"/"end" keys, exactly what whisperx expects.
    result = whisperx.assign_word_speakers(
        diarize_segments,
        {"segments": asr_segments},
    )
    return _segments_to_markdown(result.get("segments", []))


def _segments_to_markdown(segments: list[dict[str, Any]]) -> str:
    """Collapse consecutive same-speaker segments into ``**[X]**: text`` lines."""
    lines: list[str] = []
    current_speaker: Optional[str] = None
    current_sentence: list[str] = []
    for segment in segments:
        speaker = segment.get("speaker", "UNKNOWN")
        text = segment.get("text", "").strip()
        if speaker != current_speaker:
            if current_speaker is not None and current_sentence:
                lines.append(f"**[{current_speaker}]**: {' '.join(current_sentence)}")
            current_speaker = speaker
            current_sentence = [text] if text else []
        elif text:
            current_sentence.append(text)
    if current_speaker is not None and current_sentence:
        lines.append(f"**[{current_speaker}]**: {' '.join(current_sentence)}")
    return "\n\n".join(lines)


# ── Public entry-point ─────────────────────────────────────────────────


async def transcribe_media(file_path: str, language: str = "zh") -> str:
    """Transcribe an audio/video file to speaker-labelled markdown.

    ``language`` is a WhisperX language hint:
      * ``"zh"`` / ``"en"`` / any ISO-639-1 code: force the decoder.
      * ``"auto"``: let Whisper detect per clip (slower, occasionally
        misidentifies — only use for genuinely mixed audio).

    Dispatches by the active TRANSCRIPTION_PROVIDER + MODEL. When the
    provider is remote AND DIARIZATION_MODE=pyannote, the registry calls
    back into this module's ``align_remote_words_with_local_diarization``
    to produce speaker-separated output.
    """
    from app.services.voice.transcription_registry import resolve_transcription, transcribe

    cfg = resolve_transcription()
    try:
        logger.info(
            "Transcribing %s via provider=%s model=%s language=%s",
            file_path, cfg.provider_id, cfg.model, language,
        )
        # Pass language through; remote providers map "auto" → None.
        # Local WhisperX (_run_whisperx_sync) also honours None for auto.
        text = await transcribe(file_path, language=language)
        logger.info("Transcription completed (%d chars).", len(text))
        return text
    except Exception as e:
        logger.error(f"Transcription failed via provider={cfg.provider_id}: {e}")
        raise


__all__ = [
    "init_whisper_model",
    "transcribe_media",
    "_run_whisperx_sync",
    "align_remote_words_with_local_diarization",
    "whisper_model",
    "diarize_model",
]
