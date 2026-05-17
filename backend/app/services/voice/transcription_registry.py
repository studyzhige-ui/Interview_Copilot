"""ASR provider registry — pick a provider, pick any model name.

Same shape as embedding/reranker: small PROVIDERS dict + free-form
``TRANSCRIPTION_MODEL`` env. Hybrid local-Pyannote diarization is a
separate axis controlled by ``DIARIZATION_MODE`` (see
``audio_transcription_service.py``).

User config (.env):

    TRANSCRIPTION_PROVIDER=siliconflow                  # any key from PROVIDERS
    TRANSCRIPTION_MODEL=FunAudioLLM/SenseVoiceSmall      # any model that provider hosts
    DIARIZATION_MODE=auto                                # auto | pyannote | none
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


ProviderKind = Literal["local_whisperx", "openai_compat"]


@dataclass(frozen=True)
class TranscriptionProvider:
    kind: ProviderKind
    api_base: str = ""
    api_key_env: str = ""
    label: str = ""
    china_friendly: bool = False
    # True if the provider supports OpenAI's `timestamp_granularities[]=word`
    # for word-level timing (needed for hybrid Pyannote diarization).
    supports_word_timestamps: bool = False


PROVIDERS: dict[str, TranscriptionProvider] = {
    "local_whisperx": TranscriptionProvider(
        kind="local_whisperx",
        label="本地 WhisperX (含 Pyannote)",
        china_friendly=True,
        supports_word_timestamps=True,
    ),
    "openai": TranscriptionProvider(
        kind="openai_compat",
        api_base=os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        api_key_env="OPENAI_API_KEY",
        label="OpenAI",
        supports_word_timestamps=True,
    ),
    "siliconflow": TranscriptionProvider(
        kind="openai_compat",
        api_base=os.getenv("SILICONFLOW_API_BASE", "https://api.siliconflow.cn/v1"),
        api_key_env="SILICONFLOW_API_KEY",
        label="硅基流动",
        china_friendly=True,
        supports_word_timestamps=False,  # SenseVoice/whisper-v3 — varies, treat as no
    ),
    "dashscope": TranscriptionProvider(
        kind="openai_compat",
        api_base=os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key_env="DASHSCOPE_API_KEY",
        label="阿里通义",
        china_friendly=True,
    ),
}


@dataclass(frozen=True)
class ResolvedTranscription:
    provider_id: str
    provider: TranscriptionProvider
    model: str


def resolve_transcription() -> ResolvedTranscription:
    pid = (settings.TRANSCRIPTION_PROVIDER or "local_whisperx").strip().lower()
    if pid not in PROVIDERS:
        logger.warning(
            "Unknown TRANSCRIPTION_PROVIDER=%r, falling back to 'local_whisperx'", pid,
        )
        pid = "local_whisperx"
    model = (settings.TRANSCRIPTION_MODEL or "Systran/faster-whisper-large-v3").strip()
    return ResolvedTranscription(provider_id=pid, provider=PROVIDERS[pid], model=model)


def list_providers() -> list[dict[str, Any]]:
    return [
        {
            "id": pid,
            "kind": p.kind,
            "label": p.label,
            "china_friendly": p.china_friendly,
            "supports_word_timestamps": p.supports_word_timestamps,
            "api_key_env": p.api_key_env,
            "ready": p.kind == "local_whisperx" or bool(os.getenv(p.api_key_env, "").strip()),
        }
        for pid, p in PROVIDERS.items()
    ]


# ── Dispatch ───────────────────────────────────────────────────────────


def _hybrid_diarization_wanted() -> bool:
    """True when DIARIZATION_MODE asks for local Pyannote on top of remote ASR.

    ``auto`` reserves Pyannote for the pure-local path; ``pyannote`` forces it.
    """
    mode = (settings.DIARIZATION_MODE or "auto").strip().lower()
    return mode == "pyannote"


async def transcribe(file_path: str, language: Optional[str] = "zh") -> str:
    """Run ASR on ``file_path`` and return markdown-formatted text.

    Local WhisperX returns ``**[Speaker N]**: text`` per turn (Pyannote
    bundled). Remote providers return single-speaker text wrapped under
    one synthetic ``**[Speaker 1]**:`` label — UNLESS hybrid mode is on,
    in which case word-level timestamps + local Pyannote produce real
    speaker labels.
    """
    cfg = resolve_transcription()
    p = cfg.provider

    if p.kind == "local_whisperx":
        from app.services.voice.audio_transcription_service import _run_whisperx_sync
        # Forward the language hint to WhisperX. Forcing the language is
        # the single largest accuracy improvement on clean monolingual
        # audio because Whisper's auto-detect is noisy on short clips.
        return await asyncio.to_thread(_run_whisperx_sync, file_path, language)

    if p.kind == "openai_compat":
        return await _transcribe_openai_compat(cfg, file_path, language)

    raise RuntimeError(f"Unknown provider kind: {p.kind!r}")


async def _transcribe_openai_compat(
    cfg: ResolvedTranscription,
    file_path: str,
    language: Optional[str],
) -> str:
    """POST audio to an OpenAI-compatible /v1/audio/transcriptions endpoint.

    Two response shapes depending on whether hybrid diarization is needed:

      * **single-speaker mode** (``DIARIZATION_MODE`` ∈ {auto, none}):
        ``response_format=text`` — provider returns plain transcript, we
        wrap in a single ``**[Speaker 1]**:`` line.

      * **hybrid mode** (``DIARIZATION_MODE=pyannote``):
        ``response_format=verbose_json`` + ``timestamp_granularities[]=word``
        — provider returns segments with word-level timing, we feed them
        to local Pyannote and align via ``whisperx.assign_word_speakers``.
        Falls back to single-speaker text if the provider can't produce
        word-level timestamps.
    """
    import httpx

    p = cfg.provider
    api_key = os.getenv(p.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            f"TRANSCRIPTION_PROVIDER={cfg.provider_id} requires {p.api_key_env}"
            " to be set in .env"
        )
    url = f"{p.api_base.rstrip('/')}/audio/transcriptions"

    with open(file_path, "rb") as f:
        body = f.read()
    file_name = os.path.basename(file_path)

    want_hybrid = _hybrid_diarization_wanted()
    if want_hybrid:
        data: dict[str, Any] = {
            "model": cfg.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
    else:
        data = {"model": cfg.model, "response_format": "text"}
    if language:
        data["language"] = language
    files = {"file": (file_name, body, "application/octet-stream")}

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files=files,
        )
        resp.raise_for_status()
        if want_hybrid:
            try:
                payload = resp.json()
            except ValueError:
                logger.warning(
                    "Hybrid mode: provider %s returned non-JSON; degrading to single-speaker.",
                    cfg.provider_id,
                )
                text = resp.text.strip()
                return f"**[Speaker 1]**: {text}" if text else ""
        else:
            text = resp.text.strip()
            return f"**[Speaker 1]**: {text}" if text else ""

    segments_in = payload.get("segments") or []
    has_word_ts = any(seg.get("words") for seg in segments_in)
    if not has_word_ts:
        flat = payload.get("text") or " ".join(
            (s.get("text") or "").strip() for s in segments_in
        )
        flat = flat.strip()
        logger.info(
            "Hybrid mode: provider %s did not return word timestamps; "
            "skipping local diarization.", cfg.provider_id,
        )
        return f"**[Speaker 1]**: {flat}" if flat else ""

    from app.services.voice.audio_transcription_service import (
        align_remote_words_with_local_diarization,
    )
    return await asyncio.to_thread(
        align_remote_words_with_local_diarization,
        file_path,
        segments_in,
    )


__all__ = [
    "TranscriptionProvider",
    "PROVIDERS",
    "ResolvedTranscription",
    "resolve_transcription",
    "list_providers",
    "transcribe",
]
