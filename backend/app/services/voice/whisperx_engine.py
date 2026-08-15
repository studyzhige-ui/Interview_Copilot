"""Local WhisperX transcription and Pyannote diarization engine.

Two independent axes:

  * **Transcription** (ASR) — selected by ``TRANSCRIPTION_PROVIDER`` and
    ``TRANSCRIPTION_MODEL`` via ``transcription_registry``. The provider may
    be local WhisperX or a remote OpenAI-compatible endpoint.
  * **Diarization** (speaker separation) — Pyannote, selected by
    ``DIARIZATION_MODE``:
        ``auto``     — load when ASR is local-whisperx (whisperx bundles it
                       and we feed it the same audio); off when ASR is remote.
        ``pyannote`` — force load. Hybrid mode: remote ASR returns word
                       timestamps, local Pyannote labels speakers, we align.
        ``none``     — never load. Transcripts are single-speaker.

Provider selection and remote ASR live in ``transcription_registry``. This
module owns only heavyweight local model state and local inference helpers.
"""

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot

logger = logging.getLogger(__name__)

# Module-level singletons. Each is independently populated; ``whisper_model``
# only when local-whisperx is the active ASR profile, ``diarize_model`` when
# DIARIZATION_MODE allows it. Remote-mode workers leave both as ``None``.
whisper_model = None
diarize_model = None
alignment_models: dict[str, tuple[Any, dict[str, Any], str]] = {}


def _ensure_ffmpeg_available() -> str:
    """Return an FFmpeg executable visible to WhisperX subprocesses.

    Conda installs FFmpeg in ``<env>/Library/bin`` on Windows, but service
    managers do not always preserve the activated shell's PATH when they
    spawn a Celery worker.  Resolve that standard location explicitly and
    expose it to child processes.  Other platforms keep using normal PATH
    resolution.  A missing binary is a deployment error, not an ASR failure.
    """

    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved

    candidate_dirs = [Path(sys.prefix) / "Library" / "bin"]
    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        candidate_dirs.append(Path(conda_prefix) / "Library" / "bin")

    seen: set[Path] = set()
    for candidate_dir in candidate_dirs:
        normalized_dir = candidate_dir.resolve()
        if normalized_dir in seen:
            continue
        seen.add(normalized_dir)
        candidate = normalized_dir / "ffmpeg.exe"
        if not candidate.is_file():
            continue
        path_entries = os.environ.get("PATH", "").split(os.pathsep)
        if str(normalized_dir).casefold() not in {
            entry.casefold() for entry in path_entries if entry
        }:
            os.environ["PATH"] = os.pathsep.join([str(normalized_dir), *path_entries])
        logger.info("FFmpeg resolved from Conda environment: %s", candidate)
        return str(candidate)

    raise RuntimeError(
        "ffmpeg_unavailable: install FFmpeg and expose it on PATH; Windows "
        "Conda deployments may install it with `conda install -c conda-forge "
        "ffmpeg` in the worker's Python environment"
    )


def _local_device() -> str:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            'Local speech models require the "local" dependency group '
            '(pip install -e ".[local]", optionally with the "cuda" extra)'
        ) from exc
    return "cuda" if torch.cuda.is_available() else "cpu"


# ── Decisions ──────────────────────────────────────────────────────────


def _is_local_asr_active() -> bool:
    return (
        settings.TRANSCRIPTION_PROVIDER or "local_whisperx"
    ).strip().lower() == "local_whisperx"


def _should_load_diarization() -> bool:
    """Return True if Pyannote should be loaded into this worker process."""
    mode = (settings.DIARIZATION_MODE or "auto").strip().lower()
    if mode == "none":
        return False
    if mode == "pyannote":
        return True  # hybrid mode forces load
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

    device = _local_device()
    compute_type = "float16" if device == "cuda" else "int8"
    logger.info(f"WhisperX 加载：device={device.upper()} compute={compute_type}")

    hf_cache_dir = prepare_hf_runtime()
    # TRANSCRIPTION_MODEL doubles as the local-whisperx HF id (faster-whisper
    # CTranslate2 weights live there). Resolve to the on-disk snapshot first
    # so we never fall through to a network download at request time.
    whisper_id = (
        settings.TRANSCRIPTION_MODEL or "Systran/faster-whisper-large-v3"
    ).strip()
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
    _ensure_ffmpeg_available()
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

    device = _local_device()
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


def _get_alignment_model(language: str) -> tuple[Any, dict[str, Any], str]:
    """Load a local forced-alignment model once per worker/language."""

    normalized = (language or "zh").strip().lower()
    cached = alignment_models.get(normalized)
    if cached is not None:
        return cached
    configured_id = settings.TRANSCRIPTION_ALIGNMENT_MODEL.strip()
    local_path = resolve_local_snapshot(configured_id)
    if local_path is None:
        from app.core.hf_runtime import format_missing_model_error

        raise RuntimeError(
            format_missing_model_error(
                model_id=configured_id,
                role="Interview word alignment",
                filter_substring="wav2vec",
                fix_hint="python scripts/init_models.py --only alignment",
            )
        )
    import whisperx

    model, metadata = whisperx.load_align_model(
        language_code=normalized,
        device=_local_device(),
        model_name=local_path,
        model_cache_only=True,
    )
    cached = (model, metadata, configured_id)
    alignment_models[normalized] = cached
    return cached


def init_whisper_model():
    """Load whichever local models the current config needs.

    Called from the Celery ``worker_process_init`` signal so each worker
    pays the cold-load cost once at startup, not on the first request.
    The function is conservative: if the active provider is fully remote
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


def _transcribe_with_word_timestamps(
    audio: Any,
    *,
    language: str | None,
) -> dict[str, Any]:
    """Run the loaded CTranslate2 model with real word timestamps.

    WhisperX's batched pipeline intentionally returns segment timestamps only.
    Segment-majority diarization is not sufficient for interviews because a
    single segment can contain both a question and its answer. When Pyannote is
    active we therefore use the same already-loaded faster-whisper model with
    ``word_timestamps=True``; no second ASR model or semantic rewrite is added.
    """

    segments, info = whisper_model.model.transcribe(
        audio,
        language=language,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )
    serialized: list[dict[str, Any]] = []
    for segment in segments:
        words = [
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
                "score": word.probability,
            }
            for word in (segment.words or [])
            if word.start is not None and word.end is not None
        ]
        serialized.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": words,
            }
        )
    return {"segments": serialized, "language": info.language}


def _run_whisperx_sync(file_path: str, language: str | None = "zh") -> str:
    """WhisperX + Pyannote pipeline. Returns markdown with speaker prefixes.

    ``language`` is a WhisperX language hint. Forcing the language is the
    single most effective accuracy boost for monolingual audio because
    Whisper's auto-detect is occasionally wrong on short clips. Pass
    ``None`` (or ``"auto"``) to let Whisper detect per clip.
    """
    if not whisper_model:
        raise RuntimeError(
            "Local WhisperX is not loaded. Set TRANSCRIPTION_PROVIDER="
            "local_whisperx and let the worker initialize it, or configure a "
            "remote transcription provider."
        )
    if whisper_model == "mock_model":
        return (
            "**[Speaker 1]**: 请问你的项目难点是什么？\n\n"
            "**[Speaker 2]**: 难点在于高并发处理下，分布式锁发生脑裂的情况。\n\n"
            "**[Speaker 1]**: 你是怎么解决的？\n\n"
            "**[Speaker 2]**: 我采用了 Redisson 的看门狗机制。"
        )

    _ensure_ffmpeg_available()
    import whisperx

    audio = whisperx.load_audio(file_path)
    # WhisperX raises if we pass an unknown string, so map "auto" → None.
    effective_lang = (
        None if (language or "").strip().lower() in {"", "auto"} else language
    )
    if diarize_model is not None:
        result = _transcribe_with_word_timestamps(
            audio,
            language=effective_lang,
        )
        diarize_segments = diarize_model(
            audio,
            min_speakers=settings.DIARIZATION_MIN_SPEAKERS,
            max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
        )
        result = whisperx.assign_word_speakers(diarize_segments, result)
    else:
        kwargs: dict = {"batch_size": 16}
        if effective_lang:
            kwargs["language"] = effective_lang
        result = whisper_model.transcribe(audio, **kwargs)
    return _segments_to_markdown(result.get("segments", []))


def _annotation_intervals(annotation: Any) -> list[dict[str, Any]]:
    return [
        {
            "start": float(segment.start),
            "end": float(segment.end),
            "speaker_id": str(speaker),
        }
        for segment, _track, speaker in annotation.itertracks(yield_label=True)
    ]


def _run_diarization_tracks(
    audio: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return regular and Community-1 exclusive diarization tracks."""

    if diarize_model is None:
        raise RuntimeError(
            "interview_evidence_requires_diarization: set DIARIZATION_MODE=auto "
            "and install the configured Community-1 model"
        )
    import torch

    audio_data = {
        "waveform": torch.from_numpy(audio[None, :]),
        "sample_rate": 16_000,
    }
    bounds: dict[str, int] = {
        "min_speakers": settings.DIARIZATION_MIN_SPEAKERS,
        "max_speakers": settings.DIARIZATION_MAX_SPEAKERS,
    }
    if settings.DIARIZATION_MIN_SPEAKERS == settings.DIARIZATION_MAX_SPEAKERS:
        bounds = {"num_speakers": settings.DIARIZATION_MIN_SPEAKERS}
    output = diarize_model.model(audio_data, **bounds)
    regular = getattr(output, "speaker_diarization", None)
    exclusive = getattr(output, "exclusive_speaker_diarization", None)
    if regular is None or exclusive is None:
        raise RuntimeError(
            "configured diarization model does not expose regular and exclusive tracks"
        )
    return _annotation_intervals(regular), _annotation_intervals(exclusive)


def run_interview_evidence_sync(
    file_path: str,
    *,
    file_asset_id: str,
    file_asset_version: str,
    language: str | None = "zh",
):
    """Create immutable v2 evidence for an uploaded interview recording.

    Unlike the generic transcription API, this path fails closed unless it can
    produce forced-aligned words and both diarization tracks.
    """

    if not whisper_model or whisper_model == "mock_model":
        raise RuntimeError("local WhisperX is not loaded for interview evidence")
    _ensure_ffmpeg_available()
    import whisperx

    from app.services.voice.transcript_evidence import (
        build_transcript_evidence,
        sha256_file,
    )

    audio = whisperx.load_audio(file_path)
    effective_lang = (
        None if (language or "").strip().lower() in {"", "auto"} else language
    )
    asr_result = whisper_model.transcribe(
        audio,
        batch_size=16,
        language=effective_lang,
    )
    detected_language = str(asr_result.get("language") or effective_lang or "zh")
    align_model, align_metadata, alignment_id = _get_alignment_model(detected_language)
    aligned = whisperx.align(
        asr_result.get("segments") or [],
        align_model,
        align_metadata,
        audio,
        _local_device(),
        return_char_alignments=False,
    )
    raw_words = list(aligned.get("word_segments") or [])
    regular, exclusive = _run_diarization_tracks(audio)
    evidence = build_transcript_evidence(
        file_asset_id=file_asset_id,
        file_asset_version=file_asset_version,
        audio_sha256=sha256_file(file_path),
        duration_seconds=float(len(audio)) / 16_000.0,
        language=detected_language,
        asr_model=settings.TRANSCRIPTION_MODEL,
        alignment_model=alignment_id,
        diarization_model=settings.DIARIZATION_MODEL_ID,
        raw_words=raw_words,
        regular_intervals=regular,
        exclusive_intervals=exclusive,
    )
    return evidence


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

    _ensure_ffmpeg_available()
    import whisperx

    audio = whisperx.load_audio(file_path)
    diarize_segments = diarize_model(
        audio,
        min_speakers=settings.DIARIZATION_MIN_SPEAKERS,
        max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
    )
    # whisperx.assign_word_speakers wants a dict with "segments" containing
    # word-level entries. The OpenAI verbose_json shape is already close —
    # word entries use "word"/"start"/"end" keys, exactly what whisperx expects.
    result = whisperx.assign_word_speakers(
        diarize_segments,
        {"segments": asr_segments},
    )
    return _segments_to_markdown(result.get("segments", []))


def _segments_to_markdown(segments: list[dict[str, Any]]) -> str:
    """Render diarized words without collapsing alternating speakers.

    ``whisperx.assign_word_speakers`` labels both segments and individual
    words. A segment-level label is only the majority speaker and may contain
    a complete interviewer/candidate exchange, so using it as the turn owner
    destroys the QA boundary before analysis starts. Prefer word-level labels
    and fall back to the segment label only when a provider supplied no words.
    """

    lines: list[str] = []
    current_speaker: Optional[str] = None
    current_tokens: list[str] = []

    def flush() -> None:
        nonlocal current_tokens
        text = "".join(current_tokens).strip()
        if current_speaker is not None and text:
            lines.append(f"**[{current_speaker}]**: {text}")
        current_tokens = []

    def append(speaker: str, token: str) -> None:
        nonlocal current_speaker
        if not token:
            return
        if speaker != current_speaker:
            flush()
            current_speaker = speaker
        current_tokens.append(token)

    for segment in segments:
        fallback_speaker = str(segment.get("speaker") or "UNKNOWN")
        words = segment.get("words")
        usable_words = (
            [word for word in words if isinstance(word, dict) and word.get("word")]
            if isinstance(words, list)
            else []
        )
        if usable_words:
            for word in usable_words:
                append(
                    str(word.get("speaker") or fallback_speaker),
                    str(word["word"]),
                )
            continue
        fallback_text = str(segment.get("text") or "").strip()
        if fallback_text and fallback_speaker == current_speaker and current_tokens:
            fallback_text = f" {fallback_text}"
        append(fallback_speaker, fallback_text)
    flush()
    return "\n\n".join(lines)


__all__ = [
    "init_whisper_model",
    "_run_whisperx_sync",
    "align_remote_words_with_local_diarization",
    "run_interview_evidence_sync",
    "whisper_model",
    "diarize_model",
]
