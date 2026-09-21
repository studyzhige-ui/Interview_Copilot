"""Lightweight broker client for local, finite-clip speaker observations."""

from __future__ import annotations

from app.core.config import settings
from .client import Client, configured_socket_path, make_audio_request
from .config import binding_for
from .speaker_audio import DIARIZATION_BINDING_TOKENS


class DiarizationClient:
    def __init__(self, *, model: str, client=None, revision: str | None = None):
        self.model = model
        self.binding = binding_for(
            "diarization",
            model,
            revision
            if revision is not None
            else settings.MODEL_REVISIONS_JSON.get(model),
            1,
            DIARIZATION_BINDING_TOKENS,
        )
        self.client = client or Client(
            configured_socket_path(), timeout=settings.LOCAL_INFERENCE_TIMEOUT_SECONDS
        )

    async def diarize(self, pcm: bytes, *, priority="background"):
        task = make_audio_request(
            "diarization",
            self.binding,
            pcm,
            priority=priority,
            timeout=self.client.timeout,
        )
        return await self.client.acall(task, dimension=1)
