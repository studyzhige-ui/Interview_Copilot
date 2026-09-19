"""Canonical, immutable word evidence for interview audio.

This module deliberately contains no LLM logic.  It turns aligned ASR words
and diarization tracks into a validated evidence graph.  Every later display
or QA projection must cite these stable word identities.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


EVIDENCE_SCHEMA_VERSION = 2
_TURN_PAUSE_SECONDS = 1.2
_NON_LEXICAL = {
    "嗯",
    "呃",
    "额",
    "啊",
    "唔",
    "erm",
    "uh",
    "um",
    "[noise]",
    "[music]",
    "[laughter]",
}
_PUNCTUATION_ONLY = re.compile(r"^[\s\W_]+$", re.UNICODE)


class AudioEvidenceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_asset_id: str
    file_asset_version: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_seconds: float = Field(ge=0)


class EvidenceModels(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asr: str
    alignment: str
    diarization: str


class DiarizationInterval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    end: float = Field(gt=0)
    speaker_id: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_interval(self) -> "DiarizationInterval":
        if self.end <= self.start:
            raise ValueError("diarization interval must have positive duration")
        return self


class EvidenceWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word_id: str = Field(pattern=r"^w\d{6}$")
    text: str = Field(min_length=1)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    asr_confidence: float | None = Field(default=None, ge=0, le=1)
    alignment_status: Literal["aligned", "estimated", "missing"]
    speaker_id: str | None = Field(default=None, max_length=80)
    speaker_confidence: float | None = Field(default=None, ge=0, le=1)
    overlap: bool = False

    @model_validator(mode="after")
    def validate_interval(self) -> "EvidenceWord":
        if (self.start is None) != (self.end is None):
            raise ValueError("word timing must provide both start and end")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("word interval must have positive duration")
        if self.alignment_status == "missing" and self.start is not None:
            raise ValueError("missing alignment cannot carry fabricated timing")
        if self.alignment_status != "missing" and self.start is None:
            raise ValueError("timed alignment status requires word timing")
        return self


class AcousticTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(pattern=r"^t\d{4}$")
    speaker_id: str | None = Field(default=None, max_length=80)
    start_word_id: str = Field(pattern=r"^w\d{6}$")
    end_word_id: str = Field(pattern=r"^w\d{6}$")


class DiarizationTracks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    regular: list[DiarizationInterval]
    exclusive: list[DiarizationInterval]


class TranscriptEvidence(BaseModel):
    """Versioned interview-audio evidence.

    The validator makes the graph safe to persist: identifiers are unique,
    words are chronological and acoustic turns are complete contiguous ranges.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = EVIDENCE_SCHEMA_VERSION
    audio: AudioEvidenceIdentity
    language: str | None = None
    models: EvidenceModels
    words: list[EvidenceWord] = Field(min_length=1)
    diarization: DiarizationTracks
    acoustic_turns: list[AcousticTurn] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> "TranscriptEvidence":
        ids = [word.word_id for word in self.words]
        if len(ids) != len(set(ids)):
            raise ValueError("word ids must be unique")
        index = {word_id: offset for offset, word_id in enumerate(ids)}
        for offset, word in enumerate(self.words):
            previous = self.words[offset - 1] if offset else None
            if (
                previous is not None
                and previous.start is not None
                and word.start is not None
                and word.start < previous.start
            ):
                raise ValueError("words must be ordered by start time")

        expected_start = 0
        turn_ids: set[str] = set()
        for turn in self.acoustic_turns:
            if turn.turn_id in turn_ids:
                raise ValueError("turn ids must be unique")
            turn_ids.add(turn.turn_id)
            if turn.start_word_id not in index or turn.end_word_id not in index:
                raise ValueError("acoustic turn references unknown word")
            start = index[turn.start_word_id]
            end = index[turn.end_word_id]
            if start != expected_start or end < start:
                raise ValueError("acoustic turns must partition words contiguously")
            if any(
                self.words[pos].speaker_id != turn.speaker_id
                for pos in range(start, end + 1)
            ):
                raise ValueError("acoustic turn crosses speaker identity")
            expected_start = end + 1
        if expected_start != len(self.words):
            raise ValueError("acoustic turns must cover every word")
        return self

    def word_index(self) -> dict[str, int]:
        return {word.word_id: index for index, word in enumerate(self.words)}

    def word_map(self) -> dict[str, EvidenceWord]:
        return {word.word_id: word for word in self.words}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _overlap(start: float, end: float, interval: DiarizationInterval) -> float:
    return max(0.0, min(end, interval.end) - max(start, interval.start))


def _assign_speaker(
    *,
    start: float,
    end: float,
    exclusive: list[DiarizationInterval],
    regular: list[DiarizationInterval],
) -> tuple[str | None, float | None, bool]:
    duration = max(end - start, 1e-6)
    exclusive_scores: dict[str, float] = {}
    for interval in exclusive:
        amount = _overlap(start, end, interval)
        if amount:
            exclusive_scores[interval.speaker_id] = (
                exclusive_scores.get(interval.speaker_id, 0.0) + amount
            )
    if exclusive_scores:
        speaker, amount = max(exclusive_scores.items(), key=lambda item: item[1])
        confidence: float | None = min(1.0, amount / duration)
    else:
        speaker, confidence = None, None

    regular_speakers = {
        interval.speaker_id
        for interval in regular
        if _overlap(start, end, interval) > 0
    }
    return speaker, confidence, len(regular_speakers) > 1


def build_transcript_evidence(
    *,
    file_asset_id: str,
    file_asset_version: str,
    audio_sha256: str,
    duration_seconds: float,
    language: str | None,
    asr_model: str,
    alignment_model: str,
    diarization_model: str,
    raw_words: list[dict[str, Any]],
    regular_intervals: list[dict[str, Any]],
    exclusive_intervals: list[dict[str, Any]],
) -> TranscriptEvidence:
    """Build canonical evidence from provider output without semantic edits."""

    regular = [DiarizationInterval.model_validate(item) for item in regular_intervals]
    exclusive = [
        DiarizationInterval.model_validate(item) for item in exclusive_intervals
    ]
    words: list[EvidenceWord] = []
    for raw in raw_words:
        text = str(raw.get("word") or raw.get("text") or "")
        if not text.strip():
            continue
        raw_start = raw.get("start")
        raw_end = raw.get("end")
        start = float(raw_start) if raw_start is not None else None
        end = float(raw_end) if raw_end is not None else None
        if start is not None and end is not None:
            speaker, speaker_confidence, overlap = _assign_speaker(
                start=start,
                end=end,
                exclusive=exclusive,
                regular=regular,
            )
        else:
            speaker, speaker_confidence, overlap = None, None, False
        raw_score = raw.get("score", raw.get("probability"))
        confidence = float(raw_score) if raw_score is not None else None
        words.append(
            EvidenceWord(
                word_id=f"w{len(words) + 1:06d}",
                text=text,
                start=start,
                end=end,
                asr_confidence=confidence,
                alignment_status=(
                    str(raw.get("alignment_status") or "aligned")
                    if start is not None
                    else "missing"
                ),
                speaker_id=speaker,
                speaker_confidence=speaker_confidence,
                overlap=overlap,
            )
        )
    if not words:
        raise ValueError("ASR produced no aligned words")

    turns: list[AcousticTurn] = []
    start_index = 0
    for index in range(1, len(words) + 1):
        boundary = index == len(words)
        if not boundary:
            previous = words[index - 1]
            current = words[index]
            boundary = current.speaker_id != previous.speaker_id
            if not boundary and current.start is not None and previous.end is not None:
                boundary = current.start - previous.end > _TURN_PAUSE_SECONDS
        if boundary:
            turns.append(
                AcousticTurn(
                    turn_id=f"t{len(turns) + 1:04d}",
                    speaker_id=words[start_index].speaker_id,
                    start_word_id=words[start_index].word_id,
                    end_word_id=words[index - 1].word_id,
                )
            )
            start_index = index

    return TranscriptEvidence(
        audio=AudioEvidenceIdentity(
            file_asset_id=file_asset_id,
            file_asset_version=file_asset_version,
            sha256=audio_sha256,
            duration_seconds=duration_seconds,
        ),
        language=language,
        models=EvidenceModels(
            asr=asr_model,
            alignment=alignment_model,
            diarization=diarization_model,
        ),
        words=words,
        diarization=DiarizationTracks(regular=regular, exclusive=exclusive),
        acoustic_turns=turns,
    )


def render_word_ids(
    evidence: TranscriptEvidence,
    word_ids: list[str],
    *,
    hidden_word_ids: set[str] | None = None,
    punctuation_after: dict[str, str] | None = None,
) -> str:
    """Render source words in evidence order; never accept model-authored text."""

    hidden = hidden_word_ids or set()
    punctuation = punctuation_after or {}
    selected = set(word_ids)
    pieces: list[str] = []
    for word in evidence.words:
        if word.word_id not in selected or word.word_id in hidden:
            continue
        pieces.append(word.text)
        if mark := punctuation.get(word.word_id):
            pieces.append(mark)
    return "".join(pieces).strip()


def strict_display_hidden_words(words: list[EvidenceWord]) -> dict[str, str]:
    """Return only audit-safe, non-semantic cleanup edits.

    This is intentionally conservative.  It does not remove discourse markers
    such as “然后” or “就是”, because they may carry the candidate's meaning.
    """

    hidden: dict[str, str] = {}
    previous_visible: EvidenceWord | None = None
    for word in words:
        normalized = word.text.strip().lower()
        if normalized in _NON_LEXICAL:
            hidden[word.word_id] = "filled_pause_or_noise"
            continue
        if (
            previous_visible is not None
            and normalized
            and normalized == previous_visible.text.strip().lower()
            and word.start is not None
            and previous_visible.end is not None
            and word.start - previous_visible.end <= 0.45
        ):
            hidden[word.word_id] = "immediate_exact_repetition"
            continue
        previous_visible = word
    return hidden


def is_substantive_word(word: EvidenceWord) -> bool:
    normalized = word.text.strip().lower()
    return bool(
        normalized
        and normalized not in _NON_LEXICAL
        and not _PUNCTUATION_ONLY.fullmatch(normalized)
    )


def render_raw_turns(evidence: TranscriptEvidence) -> str:
    index = evidence.word_index()
    lines: list[str] = []
    for turn in evidence.acoustic_turns:
        start = index[turn.start_word_id]
        end = index[turn.end_word_id]
        body = "".join(word.text for word in evidence.words[start : end + 1]).strip()
        if body:
            lines.append(f"**[{turn.speaker_id or 'UNKNOWN'}]**: {body}")
    return "\n\n".join(lines)


__all__ = [
    "AcousticTurn",
    "DiarizationInterval",
    "EvidenceWord",
    "TranscriptEvidence",
    "build_transcript_evidence",
    "is_substantive_word",
    "render_raw_turns",
    "render_word_ids",
    "sha256_file",
    "strict_display_hidden_words",
]
