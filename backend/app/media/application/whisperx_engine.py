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
_whisper_model_id: str | None = None
_diarization_model_id: str | None = None
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
    """Return True if this worker should request broker diarization."""
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
    global whisper_model, _whisper_model_id
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
    _whisper_model_id = whisper_id
    logger.info("WhisperX ready.")


def _init_diarize_only():
    """Bind the broker client in ``diarize_model``; never load Pyannote here.

    Independent from WhisperX so hybrid mode (remote ASR + local diarization)
    can request broker diarization without forcing a WhisperX ASR download.
    """
    global diarize_model, _diarization_model_id
    if diarize_model is not None:
        return
    if not _should_load_diarization():
        return

    from app.local_inference.diarization import DiarizationClient

    diarize_model = DiarizationClient(model=settings.DIARIZATION_MODEL_ID)
    _diarization_model_id = settings.DIARIZATION_MODEL_ID
    logger.info("Pyannote broker client ready (mode=%s).", settings.DIARIZATION_MODE)


def _get_alignment_model(language: str) -> tuple[Any, dict[str, Any], str]:
    """Load a local forced-alignment model once per worker/language."""

    normalized = (language or "zh").strip().lower()
    cached = alignment_models.get(normalized)
    if cached is not None:
        return cached
    from nltk.data import find
    from whisperx.alignment import PUNKT_LANGUAGES

    try:
        find(f"tokenizers/punkt_tab/{PUNKT_LANGUAGES.get(normalized, 'english')}/")
    except LookupError as exc:
        raise RuntimeError(
            "alignment_tokenizer_missing: run `python -m nltk.downloader punkt_tab` "
            "before starting the worker; the application will not download it during inference"
        ) from exc
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
        _init_diarize_only()


# ── Local-only synchronous pipeline (used by registry's local profile) ─


def transcribe_with_word_timestamps(
    audio: Any,
    *,
    language: str | None,
) -> dict[str, Any]:
    """Run the loaded CTranslate2 model with real word timestamps.

    WhisperX's batched pipeline intentionally returns segment timestamps only.
    Segment-majority diarization is not sufficient for interviews because a
    single segment can contain both a question and its answer. When Pyannote is
    active we need word-level observations. All local transcription also uses
    this timestamp-aware decoder so an early end token cannot silently discard
    the rest of a VAD batch. No second ASR model or semantic rewrite is added.
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
    result = transcribe_with_word_timestamps(audio, language=effective_lang)
    if diarize_model is not None:
        from app.core.async_runtime import run_async

        diarize_segments = run_async(_diarization_frame(audio))
        result = whisperx.assign_word_speakers(diarize_segments, result)
    return _segments_to_markdown(result.get("segments", []))


async def _run_diarization_observations(audio: Any) -> dict[str, Any]:
    """The broker is the sole owner of the Community-1 model and execution."""
    if diarize_model is None:
        raise RuntimeError("interview_evidence_requires_diarization")
    import numpy as np

    if not np.isfinite(audio).all() or np.any(audio < -1) or np.any(audio > 1):
        raise ValueError("invalid_diarization_audio")
    pcm = np.clip(np.rint(audio * 32768), -32768, 32767).astype("<i2").tobytes()
    return await diarize_model.diarize(
        pcm, max_speakers=settings.DIARIZATION_MAX_SPEAKERS
    )


async def _diarization_frame(audio: Any):
    """Bound generic/hybrid observations too, with one recording identity map."""
    import numpy as np
    import pandas as pd
    from app.media.application.evidence_windows import evidence_windows
    from app.media.application.recording_speakers import RecordingSpeakers

    if not np.isfinite(audio).all() or np.any(audio < -1) or np.any(audio > 1):
        raise ValueError("invalid_diarization_audio")
    identities = RecordingSpeakers()

    async def chunks():
        for i in range(0, len(audio), 16000):
            yield (
                np.clip(np.rint(audio[i : i + 16000] * 32768), -32768, 32767)
                .astype("<i2")
                .tobytes()
            )

    async for window in evidence_windows(
        chunks(),
        max_samples=settings.USAGE_AUDIO_MAX_MS * 16,
        choose_end=lambda pcm, start, end: end,
    ):
        samples = np.frombuffer(window.pcm, dtype="<i2").astype(np.float32) / 32768.0
        result = await _run_diarization_observations(samples)
        identities.observe(result["embeddings"])
    centroids = await identities.resolve(
        diarize_model,
        min_speakers=settings.DIARIZATION_MIN_SPEAKERS,
        max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
    )
    tracks = await _resolved_speaker_tracks(
        chunks(), centroids, choose_end=lambda pcm, start, end: end
    )
    rows = [
        {"start": row["start"], "end": row["end"], "speaker": row["speaker_id"]}
        for row in tracks["regular"]
    ]
    return pd.DataFrame(rows, columns=["start", "end", "speaker"])


async def _resolved_speaker_tracks(blocks, centroids, *, choose_end):
    from app.media.application.evidence_windows import evidence_windows
    from app.media.application.evidence_contracts import MAX_DIARIZATION_INTERVALS

    tracks = {"regular": [], "exclusive": []}
    if not centroids:
        return tracks
    async for window in evidence_windows(
        blocks, max_samples=settings.USAGE_AUDIO_MAX_MS * 16, choose_end=choose_end
    ):
        observed = await diarize_model.diarize(
            window.pcm,
            max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
            centroids=centroids,
        )
        for kind, rows in tracks.items():
            for row in observed[kind]:
                start = max(
                    window.core_start / 16000, window.start / 16000 + row["start"]
                )
                end = min(window.core_end / 16000, window.start / 16000 + row["end"])
                if start < end:
                    if len(rows) >= MAX_DIARIZATION_INTERVALS:
                        raise ValueError("longform_track_capacity")
                    rows.append(
                        {"start": start, "end": end, "speaker_id": row["speaker_id"]}
                    )
    return tracks


def _speech_core_end(pcm: bytes, start: int, limit: int) -> int:
    """Use WhisperX VAD's silence/min-cut boundaries, never a fixed mid-word cut."""
    import numpy as np
    from app.local_inference.audio import SAMPLE_RATE

    audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    vad = whisper_model.vad_model
    scores = vad({"waveform": vad.preprocess_audio(audio), "sample_rate": SAMPLE_RATE})
    chunks = vad.merge_chunks(
        scores,
        (limit - start) / SAMPLE_RATE,
        onset=whisper_model._vad_params["vad_onset"],
        offset=whisper_model._vad_params["vad_offset"],
    )
    spans = [span for chunk in chunks for span in chunk["segments"]]
    # A core limit already in silence needs no adjustment. Otherwise retain
    # the unfinished utterance for the next core, including all its PCM.
    if not any(a * SAMPLE_RATE < limit < b * SAMPLE_RATE for a, b in spans):
        return limit
    candidates = [
        int(b * SAMPLE_RATE) for _, b in spans if start < b * SAMPLE_RATE <= limit
    ]
    if not candidates:
        # Leading silence is also a boundary: carry the whole first utterance
        # rather than slicing it just before its end or repeatedly halving silence.
        starts = [
            int(a * SAMPLE_RATE) for a, _ in spans if start < a * SAMPLE_RATE <= limit
        ]
        if not starts:
            raise ValueError("speech_core_boundary_missing")
        return min(starts)
    end = max(candidates)
    following = next(
        (int(a * SAMPLE_RATE) for a, _ in spans if a * SAMPLE_RATE >= end), end
    )
    return min(limit, (end + following) // 2)


async def _collect_windowed_evidence(
    file_path: str, *, model: str, language: str | None
):
    """One finite decoder, overlapping model windows, one recording evidence result."""
    import asyncio
    import math
    from numbers import Real
    import numpy as np
    import whisperx
    from app.local_inference.audio import SAMPLE_RATE
    from app.media.application.evidence_contracts import (
        AlignedTranscript,
        EvidenceParts,
        SpeakerEvidence,
    )
    from app.media.application.evidence_contracts import (
        MAX_EVIDENCE_WORDS,
        MAX_EVIDENCE_TEXT_BYTES,
    )
    from app.media.application.evidence_windows import evidence_windows
    from app.media.application.evidence_stitching import (
        restore_word_layout,
    )
    from app.media.application.recording_speakers import RecordingSpeakers
    from app.media.application.pcm_stream import PCMStream

    asr, diarizer = whisper_model, diarize_model
    identities = (_whisper_model_id, _diarization_model_id)
    alignment_id = None
    speakers = RecordingSpeakers()
    minimum_speakers = settings.DIARIZATION_MIN_SPEAKERS
    output = []
    languages = set()
    text_bytes = total_samples = 0
    last_word_start = 0.0
    max_ms = settings.USAGE_AUDIO_MAX_MS

    def check_models():
        if (
            asr is not whisper_model
            or diarizer is not diarize_model
            or identities != (_whisper_model_id, _diarization_model_id)
            or identities[0] != model
        ):
            raise ValueError("evidence_model_identity_changed")

    def append_words(words):
        nonlocal text_bytes, last_word_start
        text_bytes += sum(len(w["text"].encode("utf-8")) for w in words)
        if (
            len(output) + len(words) > MAX_EVIDENCE_WORDS
            or text_bytes > MAX_EVIDENCE_TEXT_BYTES
        ):
            raise ValueError("longform_evidence_capacity")
        for word in words:
            if word["start"] is not None:
                if word["start"] < last_word_start:
                    raise ValueError("longform_word_order_reversed")
                last_word_start = word["start"]
        output.extend(words)

    async with PCMStream(
        file_path, max_bytes=settings.USAGE_AUDIO_MAX_BYTES, max_ms=max_ms
    ) as source:
        async for window in evidence_windows(
            source,
            max_samples=max_ms * SAMPLE_RATE // 1000,
            choose_end=_speech_core_end,
        ):
            await asyncio.sleep(0)
            check_models()
            audio = np.frombuffer(window.pcm, dtype="<i2").astype(np.float32) / 32768.0
            offset = window.start / SAMPLE_RATE
            core_start, core_end = (
                window.core_start / SAMPLE_RATE,
                window.core_end / SAMPLE_RATE,
            )
            core_audio = audio[
                window.core_start - window.start : window.core_end - window.start
            ]
            # The timestamp-aware decoder advances through every utterance.
            # Each sample is transcribed once; context is only for diarization.
            result = transcribe_with_word_timestamps(core_audio, language=language)
            diarization = await _run_diarization_observations(audio)
            speakers.observe(diarization["embeddings"])
            segments = result.get("segments") or []
            text = "".join(str(segment["text"]) for segment in segments)
            if text.strip():
                detected = str(result.get("language") or language or "").strip()
                if not detected:
                    raise ValueError("longform_text_without_language")
                align_model, metadata, current_alignment_id = _get_alignment_model(
                    detected
                )
                if alignment_id is not None and alignment_id != current_alignment_id:
                    raise ValueError("evidence_alignment_identity_changed")
                alignment_id = current_alignment_id
                languages.add(detected)
                aligned = whisperx.align(
                    segments,
                    align_model,
                    metadata,
                    core_audio,
                    _local_device(),
                    return_char_alignments=False,
                )
                raw = aligned.get("word_segments") or []
                if (
                    len(raw) > MAX_EVIDENCE_WORDS
                    or len(text.encode("utf-8")) > MAX_EVIDENCE_TEXT_BYTES
                ):
                    raise ValueError("longform_evidence_capacity")
                words = []
                last = 0.0
                for word in raw:
                    start, end = word.get("start"), word.get("end")
                    if start is not None or end is not None:
                        if (
                            any(
                                isinstance(v, bool)
                                or not isinstance(v, Real)
                                or not math.isfinite(v)
                                for v in (start, end)
                            )
                            or not 0 <= start < end <= len(core_audio) / SAMPLE_RATE
                            or start < last
                        ):
                            raise ValueError("invalid_evidence_word_time")
                        start, end = float(start), float(end)
                        last = start
                    score = word.get("score")
                    if score is not None:
                        if (
                            isinstance(score, bool)
                            or not isinstance(score, Real)
                            or not math.isfinite(score)
                            or not 0 <= score <= 1
                        ):
                            raise ValueError("invalid_evidence_word_confidence")
                        score = float(score)
                    words.append(
                        {
                            "text": word["word"],
                            "start": start,
                            "end": end,
                            "score": score,
                        }
                    )
                words = restore_word_layout(text, words, core_start)
            else:
                if any(
                    max(core_start, offset + row["start"])
                    < min(core_end, offset + row["end"])
                    for row in diarization["regular"]
                ):
                    raise ValueError("longform_speech_without_text")
                words = []
            append_words(words)
            total_samples = window.core_end
            check_models()
        if not source.complete:
            raise ValueError("audio_decode_incomplete")
    if not output:
        raise ValueError("recording_has_no_transcribed_speech")
    centroids = await speakers.resolve(
        diarizer,
        min_speakers=minimum_speakers,
        max_speakers=settings.DIARIZATION_MAX_SPEAKERS,
    )
    async with PCMStream(
        file_path, max_bytes=settings.USAGE_AUDIO_MAX_BYTES, max_ms=max_ms
    ) as source:
        tracks = await _resolved_speaker_tracks(
            source, centroids, choose_end=_speech_core_end
        )
        if not source.complete:
            raise ValueError("audio_decode_incomplete")
    check_models()
    return EvidenceParts(
        transcript=AlignedTranscript(
            words=output,
            duration_seconds=total_samples / SAMPLE_RATE,
            language=next(iter(languages)) if len(languages) == 1 else None,
            asr_model=identities[0],
            alignment_model=alignment_id,
        ),
        speakers=SpeakerEvidence(
            regular=tracks["regular"],
            exclusive=tracks["exclusive"],
            model=identities[1],
        ),
        complete=True,
    )


def collect_interview_evidence_sync(
    file_path: str, *, model: str, language: str | None = "zh"
):
    """WhisperX evidence entrypoint, run inside the existing source-owning worker."""
    import asyncio

    if not whisper_model or whisper_model == "mock_model":
        raise RuntimeError("local WhisperX is not loaded for interview evidence")
    if _whisper_model_id != model or not _diarization_model_id:
        raise RuntimeError("interview_evidence_model_identity_changed: reload worker")
    _ensure_ffmpeg_available()
    effective_language = (
        None if (language or "").strip().lower() in {"", "auto"} else language
    )
    return asyncio.run(
        _collect_windowed_evidence(file_path, model=model, language=effective_language)
    )


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

    Explicitly disabled diarization returns a single-speaker transcript.
    A configured but unavailable broker must fail instead of inventing a label.
    """
    if diarize_model is None:
        if _should_load_diarization():
            raise RuntimeError("configured_diarization_client_unavailable")
        logger.info(
            "Hybrid diarization requested but diarize_model not loaded; "
            "returning single-speaker output."
        )
        flat = " ".join(seg.get("text", "").strip() for seg in asr_segments).strip()
        return f"**[Speaker 1]**: {flat}" if flat else ""

    _ensure_ffmpeg_available()
    import whisperx

    audio = whisperx.load_audio(file_path)
    from app.core.async_runtime import run_async

    diarize_segments = run_async(_diarization_frame(audio))
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
    "transcribe_with_word_timestamps",
    "init_whisper_model",
    "_run_whisperx_sync",
    "align_remote_words_with_local_diarization",
    "collect_interview_evidence_sync",
    "whisper_model",
    "diarize_model",
]
