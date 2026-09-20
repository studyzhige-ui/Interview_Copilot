"""Application-facing finite-clip Qwen speech client, without ML imports.

Original uploaded media stays local. ASR text and forced alignment are separate
operations. No speaker labels are invented; this is not yet the full uploaded
interview evidence pipeline, which additionally requires diarization.
"""

from __future__ import annotations

from app.core.config import settings
from .client import (
    Client,
    LocalInferenceNotStarted,
    LocalInferenceUnknown,
    make_audio_request,
)
from .config import binding_for
from .client import configured_socket_path
from .audio import AUDIO_OUTPUT_TOKENS


class SpeechClient:
    def __init__(self, *, model: str, alignment_model: str | None = None, client=None):
        self.model, self.alignment_model = model, alignment_model
        self.client = client or Client(
            configured_socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )

    def _binding(self, role, model):
        return binding_for(
            role,
            model,
            settings.MODEL_REVISIONS_JSON.get(model),
            1,
            AUDIO_OUTPUT_TOKENS,
        )

    async def transcribe(self, pcm: bytes, *, language=None, priority="background"):
        req = make_audio_request(
            "transcription",
            self._binding("transcription", self.model),
            pcm,
            language=None if language in ("auto", "") else language,
            priority=priority,
            timeout=self.client.timeout,
        )
        return await self.client.acall(req, dimension=1)

    async def align(
        self, pcm: bytes, text: str, *, language: str, priority="background"
    ):
        if not self.alignment_model:
            raise LocalInferenceNotStarted("alignment_model_not_configured")
        req = make_audio_request(
            "alignment",
            self._binding("alignment", self.alignment_model),
            pcm,
            text=text,
            language=language,
            priority=priority,
            timeout=self.client.timeout,
        )
        return await self.client.acall(req, dimension=1)


async def transcribe_file(
    file_path: str, *, model: str, language=None, priority="background"
) -> str:
    from app.media.application.pcm_stream import PCMStream

    client = SpeechClient(model=model)
    completed = 0
    texts = []
    total = 0
    try:
        async with PCMStream(
            file_path,
            max_bytes=settings.USAGE_AUDIO_MAX_BYTES,
            max_ms=settings.USAGE_AUDIO_MAX_MS,
        ) as audio:
            async for pcm in audio:
                value = await client.transcribe(
                    pcm, language=language, priority=priority
                )
                completed += 1
                text = value["text"].strip()
                total += len(text.encode())
                if total > 1_000_000:
                    raise ValueError("transcription_output_capacity")
                if text:
                    texts.append(text)
    except LocalInferenceNotStarted:
        if completed:
            # One aggregate operation cannot refund already-completed chunks.
            raise LocalInferenceUnknown("partial_local_transcription") from None
        raise
    # Chunk boundaries are explicit. No guessed overlap removal or synthetic
    # speaker attribution; evidence-grade long-audio stitching is a later stage.
    return "\n".join(texts)
