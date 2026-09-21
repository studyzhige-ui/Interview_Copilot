"""Complete Qwen upload evidence using bounded broker-owned model operations.

The application owns windows, seams and recording-local speaker identities;
the existing broker owns models, IPC validation, admission and cancellation.
Only a fully exhausted decoder can produce complete EvidenceParts. Results
are still subject to the shared source/version and publication fences.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Protocol

from app.local_inference.audio import SAMPLE_RATE, validate_audio_result
from app.local_inference.speaker_audio import validate_diarization_result
from app.media.application.evidence_contracts import (
    AlignedTranscript,
    EvidenceParts,
    SpeakerEvidence,
)
from app.media.application.evidence_stitching import (
    restore_word_layout,
    stitch_boundary,
)
from app.media.application.evidence_windows import evidence_windows
from app.media.application.speaker_identity import SpeakerIdentity

# Staging budgets are deliberately no larger than the canonical compositor's
# publication budgets. Context is transient and not charged as source duration.
MAX_WORDS = 200_000
MAX_TEXT_BYTES = 1_000_000
MAX_TRACKS = 200_000


@dataclass(frozen=True)
class StageModels:
    asr: str
    alignment: str
    diarization: str


class EvidenceStages(Protocol):
    models: StageModels

    async def call(
        self, role: str, pcm: bytes, *, text: str = "", language: str | None = None
    ) -> dict: ...


async def collect_qwen_parts(
    blocks: AsyncIterable[bytes],
    stages: EvidenceStages,
    *,
    max_samples: int,
    language: str | None = None,
) -> EvidenceParts:
    """Compose complete observations; never yield or persist a partial graph."""
    models = stages.models
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (models.asr, models.alignment, models.diarization)
    ):
        raise ValueError("evidence_model_identity_missing")
    speakers = SpeakerIdentity()
    output: list[dict] = []
    pending: list[dict] = []
    tracks: dict[str, list[dict]] = {"regular": [], "exclusive": []}
    languages: set[str] = set()
    previous = None
    text_bytes = 0
    total_samples = 0

    def append_words(words):
        nonlocal text_bytes
        if output and words and words[0]["start"] < output[-1]["start"]:
            raise ValueError("longform_word_order_reversed")
        text_bytes += sum(len(word["text"].encode("utf-8")) for word in words)
        if len(output) + len(words) > MAX_WORDS or text_bytes > MAX_TEXT_BYTES:
            raise ValueError("longform_evidence_capacity")
        output.extend(words)

    async for window in evidence_windows(blocks, max_samples=max_samples):
        if stages.models != models:
            raise ValueError("evidence_model_identity_changed")
        task = {"audio": {"samples": len(window.pcm) // 2}}
        asr = validate_audio_result(
            {**task, "role": "transcription"},
            await stages.call("transcription", window.pcm, language=language),
        )
        diarization = validate_diarization_result(
            task, await stages.call("diarization", window.pcm)
        )
        mapping = speakers.assign(diarization["speakers"])
        offset = window.start / SAMPLE_RATE
        core_start = window.core_start / SAMPLE_RATE
        core_end = window.core_end / SAMPLE_RATE
        for name in tracks:
            for row in diarization[name]:
                start = max(core_start, offset + row["start"])
                end = min(core_end, offset + row["end"])
                if start < end:
                    if len(tracks[name]) >= MAX_TRACKS:
                        raise ValueError("longform_track_capacity")
                    tracks[name].append(
                        {
                            "start": start,
                            "end": end,
                            "speaker_id": mapping[row["speaker_id"]],
                        }
                    )
        if asr["text"].strip():
            if not asr["language"].strip():
                raise ValueError("longform_language_missing")
            if not diarization["speakers"]:
                raise ValueError("longform_text_without_speaker_observations")
            languages.add(asr["language"])
            aligned = validate_audio_result(
                {
                    **task,
                    "role": "alignment",
                    "text": asr["text"],
                    "language": asr["language"],
                },
                await stages.call(
                    "alignment", window.pcm, text=asr["text"], language=asr["language"]
                ),
            )
            words = restore_word_layout(asr["text"], aligned["words"], offset)
        else:
            if any(
                max(core_start, offset + row["start"])
                < min(core_end, offset + row["end"])
                for row in diarization["regular"]
            ):
                raise ValueError("longform_speech_without_text")
            words = []
        if previous is not None:
            finalized, pending = stitch_boundary(
                pending,
                words,
                boundary=core_start,
                overlap_start=window.start / SAMPLE_RATE,
                overlap_end=previous.end / SAMPLE_RATE,
            )
            append_words(finalized)
        else:
            pending = words
        if (
            len(output) + len(pending) > MAX_WORDS
            or text_bytes + sum(len(word["text"].encode("utf-8")) for word in pending)
            > MAX_TEXT_BYTES
        ):
            raise ValueError("longform_evidence_capacity")
        previous = window
        total_samples = window.core_end
    append_words(pending)
    if stages.models != models:
        raise ValueError("evidence_model_identity_changed")
    if not output:
        raise ValueError("recording_has_no_transcribed_speech")
    return EvidenceParts(
        transcript=AlignedTranscript(
            words=output,
            duration_seconds=total_samples / SAMPLE_RATE,
            language=next(iter(languages)) if len(languages) == 1 else None,
            asr_model=models.asr,
            alignment_model=models.alignment,
        ),
        speakers=SpeakerEvidence(
            regular=tracks["regular"],
            exclusive=tracks["exclusive"],
            model=models.diarization,
        ),
        complete=True,
    )


class _BrokerStages:
    """Freeze every model binding once, not once per model call or chunk."""

    def __init__(self, model: str):
        from app.core.config import settings
        from app.local_inference.audio import AUDIO_OUTPUT_TOKENS
        from app.local_inference.client import Client, configured_socket_path
        from app.local_inference.config import binding_for
        from app.local_inference.speaker_audio import DIARIZATION_BINDING_TOKENS

        selections = (
            ("transcription", model, AUDIO_OUTPUT_TOKENS),
            ("alignment", settings.TRANSCRIPTION_ALIGNMENT_MODEL, AUDIO_OUTPUT_TOKENS),
            ("diarization", settings.DIARIZATION_MODEL_ID, DIARIZATION_BINDING_TOKENS),
        )
        revisions = dict(settings.MODEL_REVISIONS_JSON)
        self.bindings = {
            role: binding_for(role, name, revisions.get(name), 1, tokens)
            for role, name, tokens in selections
        }
        self.models = StageModels(
            *(
                f"{name}@{revisions[name]}" if name in revisions else name
                for _, name, _ in selections
            )
        )
        self.client = Client(
            configured_socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )
        self.completed_calls = 0

    async def call(self, role, pcm, *, text="", language=None):
        from app.local_inference.client import make_audio_request

        task = make_audio_request(
            role,
            self.bindings[role],
            pcm,
            text=text,
            language=None if language in ("auto", "") else language,
            priority="background",
            timeout=self.client.timeout,
        )
        result = await self.client.acall(task, dimension=1)
        self.completed_calls += 1
        return result


async def _collect_file(path: str, stages, *, max_bytes: int, max_ms: int, language):
    from app.local_inference.client import LocalInferenceUnknown
    from app.media.application.pcm_stream import PCMStream

    try:
        async with PCMStream(path, max_bytes=max_bytes, max_ms=max_ms) as source:
            return await collect_qwen_parts(
                source,
                stages,
                max_samples=max_ms * SAMPLE_RATE // 1000,
                language=language,
            )
    except LocalInferenceUnknown:
        raise
    except Exception:
        if stages.completed_calls:
            # Completed subcalls cannot be refunded as "not started", and an
            # incomplete aggregate must never be automatically dispatched again.
            raise LocalInferenceUnknown(
                "longform_evidence_incomplete_after_inference"
            ) from None
        raise


def collect_qwen_evidence_sync(path: str, *, model: str, language: str | None):
    """Called by the existing snapshot-owning worker, never the API event loop."""
    from app.core.config import settings

    stages = _BrokerStages(model)
    return asyncio.run(
        _collect_file(
            path,
            stages,
            max_bytes=settings.USAGE_AUDIO_MAX_BYTES,
            max_ms=settings.USAGE_AUDIO_MAX_MS,
            language=language,
        )
    )
