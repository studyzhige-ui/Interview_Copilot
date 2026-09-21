"""Provider observations shared by execution adapters and evidence composition.

This boundary imports neither adapters nor orchestration. Completion and shape
are validated by the compositor before any observations become durable evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AlignedTranscript:
    words: list[dict[str, Any]]
    duration_seconds: float
    language: str | None
    asr_model: str
    alignment_model: str


@dataclass(frozen=True)
class SpeakerEvidence:
    regular: list[dict[str, Any]]
    exclusive: list[dict[str, Any]]
    model: str


@dataclass(frozen=True)
class EvidenceParts:
    transcript: AlignedTranscript
    speakers: SpeakerEvidence
    complete: bool


EvidenceCollector = Callable[..., EvidenceParts]
