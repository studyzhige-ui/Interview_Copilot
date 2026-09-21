"""Provider-neutral composition of aligned words and global speaker evidence.

Adapters own ASR/alignment/diarization execution. This boundary owns source
identity, completion and structural validation, and canonical word identities.
No provider may publish text-only or partial results as interview evidence.
"""

from __future__ import annotations

import math
from typing import Any

from app.media.application.evidence_contracts import EvidenceCollector, EvidenceParts
from app.media.application.evidence_source import EvidenceSource
from app.media.application.transcript_evidence import (
    DiarizationInterval,
    TranscriptEvidence,
    build_transcript_evidence,
)


MAX_EVIDENCE_WORDS = 200_000
MAX_EVIDENCE_TEXT_BYTES = 1_000_000
MAX_DIARIZATION_INTERVALS = 200_000


class EvidenceProviderUnsupported(RuntimeError):
    """The selected provider cannot produce the complete evidence contract."""


def _whisperx_collector(path: str, *, model: str, language: str | None):
    from app.media.application.whisperx_engine import collect_interview_evidence_sync

    return collect_interview_evidence_sync(path, model=model, language=language)


def _qwen_collector(path: str, *, model: str, language: str | None):
    from app.media.application.qwen_evidence import collect_qwen_evidence_sync

    return collect_qwen_evidence_sync(path, model=model, language=language)


# Explicit complete capabilities. Qwen uses the same source/publication fences;
# WhisperX remains selectable for migration and quality comparison, not fallback.
_EVIDENCE_COLLECTORS: dict[str, EvidenceCollector] = {
    "local_whisperx": _whisperx_collector,
    "local_qwen_asr": _qwen_collector,
}


def resolve_evidence_collector(provider_kind: str) -> EvidenceCollector:
    try:
        return _EVIDENCE_COLLECTORS[provider_kind]
    except KeyError:
        raise EvidenceProviderUnsupported(
            "interview_evidence_provider_unsupported: selected provider lacks "
            "a complete local evidence collector; no fallback was attempted"
        ) from None


def _finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _check_tracks(
    raw: list[dict[str, Any]], duration: float, *, exclusive: bool
) -> list[DiarizationInterval]:
    if not raw or len(raw) > MAX_DIARIZATION_INTERVALS:
        raise ValueError("evidence_diarization_missing_or_excessive")
    result = []
    previous_start = previous_end = 0.0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("invalid_evidence_diarization")
        start, end = item.get("start"), item.get("end")
        if (
            not _finite_number(start)
            or not _finite_number(end)
            or not 0 <= start < end <= duration
            or start < previous_start
            or (exclusive and start < previous_end)
        ):
            raise ValueError("invalid_evidence_diarization_time")
        interval = DiarizationInterval.model_validate(item)
        result.append(interval)
        previous_start, previous_end = start, end
    return result


def compose_transcript_evidence(
    source: EvidenceSource, parts: EvidenceParts, *, max_duration_ms: int
) -> TranscriptEvidence:
    """Validate complete provider observations before creating a v2 graph."""
    if parts.complete is not True:
        raise ValueError("interview_evidence_incomplete")
    transcript = parts.transcript
    duration = transcript.duration_seconds
    if (
        type(max_duration_ms) is not int
        or max_duration_ms <= 0
        or not _finite_number(duration)
        or not 0 < duration * 1000 <= max_duration_ms
    ):
        raise ValueError("invalid_evidence_duration")
    if any(
        not isinstance(model, str) or not model.strip()
        for model in (
            transcript.asr_model,
            transcript.alignment_model,
            parts.speakers.model,
        )
    ):
        raise ValueError("evidence_model_identity_missing")
    if not transcript.words or len(transcript.words) > MAX_EVIDENCE_WORDS:
        raise ValueError("evidence_word_capacity")

    total = 0
    previous_start = 0.0
    timed = False
    for word in transcript.words:
        if not isinstance(word, dict):
            raise ValueError("invalid_evidence_word")
        text = word.get("word", word.get("text"))
        if not isinstance(text, str) or not text.strip():
            raise ValueError("invalid_evidence_word_text")
        total += len(text.encode("utf-8"))
        if total > MAX_EVIDENCE_TEXT_BYTES:
            raise ValueError("evidence_text_capacity")
        confidence = word.get("score", word.get("probability"))
        if confidence is not None and (
            not _finite_number(confidence) or not 0 <= confidence <= 1
        ):
            raise ValueError("invalid_evidence_word_confidence")
        start, end = word.get("start"), word.get("end")
        if start is None and end is None:
            continue  # Unknown alignment stays unknown; never fabricate a time.
        if (
            not _finite_number(start)
            or not _finite_number(end)
            or not 0 <= start < end <= duration
            or start < previous_start
        ):
            raise ValueError("invalid_evidence_word_time")
        timed, previous_start = True, start
    if not timed:
        raise ValueError("evidence_has_no_aligned_words")

    regular = _check_tracks(parts.speakers.regular, duration, exclusive=False)
    exclusive = _check_tracks(parts.speakers.exclusive, duration, exclusive=True)
    if not {row.speaker_id for row in exclusive} <= {row.speaker_id for row in regular}:
        raise ValueError("evidence_exclusive_speaker_unknown")
    return build_transcript_evidence(
        file_asset_id=source.file_asset_id,
        file_asset_version=source.file_asset_version,
        audio_sha256=source.sha256,
        duration_seconds=duration,
        language=transcript.language,
        asr_model=transcript.asr_model,
        alignment_model=transcript.alignment_model,
        diarization_model=parts.speakers.model,
        raw_words=transcript.words,
        regular_intervals=parts.speakers.regular,
        exclusive_intervals=parts.speakers.exclusive,
    )
