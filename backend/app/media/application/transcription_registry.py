"""ASR provider registry — pick a provider, pick any model name.

Same shape as embedding/reranker: small PROVIDERS dict + free-form
``TRANSCRIPTION_MODEL`` env. Hybrid local-Pyannote diarization is a
separate axis controlled by ``DIARIZATION_MODE`` (see
``whisperx_engine.py``).

User config (.env):

    TRANSCRIPTION_PROVIDER=siliconflow                  # any key from PROVIDERS
    TRANSCRIPTION_MODEL=FunAudioLLM/SenseVoiceSmall      # any model that provider hosts
    DIARIZATION_MODE=auto                                # auto | pyannote | none
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.core.config import settings
from app.core.model_policy import require_local_model
from app.media.application.workers import pool

logger = logging.getLogger(__name__)


ProviderKind = Literal["local_whisperx", "local_qwen_asr", "openai_compat"]


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
    "local_qwen_asr": TranscriptionProvider(
        kind="local_qwen_asr",
        label="本地 Qwen3-ASR（有限音频转写）",
        china_friendly=True,
    ),
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
        api_base=os.getenv(
            "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
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
        raise ValueError(f"Unknown TRANSCRIPTION_PROVIDER: {pid!r}")
    require_local_model(
        "transcription",
        is_local=PROVIDERS[pid].kind in {"local_whisperx", "local_qwen_asr"},
    )
    model = (
        settings.TRANSCRIPTION_MODEL or "deepdml/faster-whisper-large-v3-turbo-ct2"
    ).strip()
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
            "ready": p.kind == "local_whisperx"
            or (p.kind == "local_qwen_asr" and bool(settings.LOCAL_INFERENCE_SOCKET))
            or (
                settings.AUXILIARY_MODEL_POLICY != "local_only"
                and bool(os.getenv(p.api_key_env, "").strip())
            ),
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

    if p.kind == "local_qwen_asr":
        return await _transcribe_qwen(cfg, file_path, language)

    if p.kind == "local_whisperx":
        from app.media.application.whisperx_engine import _run_whisperx_sync

        # Forward the language hint to WhisperX. Forcing the language is
        # the single largest accuracy improvement on clean monolingual
        # audio because Whisper's auto-detect is noisy on short clips.
        from app.usage import media, runtime

        units = await pool("probe").run(media.audio_units, file_path)
        return await pool("local").run(
            runtime.invoke_sync,
            lambda: _run_whisperx_sync(file_path, language),
            observed=lambda _: units,
            **(
                await pool("probe").run(
                    media.descriptor, cfg, file_path, language, units
                )
            ),
        )

    if p.kind == "openai_compat":
        return await _transcribe_openai_compat(cfg, file_path, language)

    raise RuntimeError(f"Unknown provider kind: {p.kind!r}")


class LocalProviderOnly(RuntimeError):
    """Raised by transcribe_plain when the resolved provider is the local
    WhisperX kind — the caller owns the local fallback path."""


def _openai_compat_request_parts(
    cfg: ResolvedTranscription,
    file_path: str,
) -> tuple[str, dict[str, str], str]:
    """Shared request scaffolding for the OpenAI-compatible ASR calls:
    (url, headers, local file path). Raises RuntimeError when the provider's env key
    is missing."""
    p = cfg.provider
    api_key = os.getenv(p.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(
            f"TRANSCRIPTION_PROVIDER={cfg.provider_id} requires {p.api_key_env}"
            " to be set in .env"
        )
    url = f"{p.api_base.rstrip('/')}/audio/transcriptions"
    size = os.path.getsize(file_path)
    maximum = settings.USAGE_AUDIO_MAX_BYTES
    # Official OpenAI file-transcription endpoint caps a single file at 25 MB.
    if cfg.provider_id == "openai":
        maximum = min(maximum, 25_000_000)
    if not 0 < size <= maximum:
        raise ValueError("audio_input_size_invalid")
    return url, {"Authorization": f"Bearer {api_key}"}, file_path


async def _send_audio(client, url, headers, data, file_path):
    import httpx

    # Owned local uploads are immutable. The handle is opened only after ledger
    # admission and is closed on cancellation, HTTP errors and size overflow.
    with open(file_path, "rb") as handle:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            data=data,
            files={
                "file": (
                    os.path.basename(file_path),
                    handle,
                    "application/octet-stream",
                )
            },
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for block in response.aiter_bytes():
                body.extend(block)
                if len(body) > settings.MODEL_STREAM_MAX_BYTES:
                    raise ValueError("transcription_response_capacity")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(body),
                request=response.request,
            )


async def transcribe_plain(file_path: str, language: Optional[str] = "zh") -> str:
    """Short-clip ASR: plain text, no speaker labels, no diarization.

    Used by the mock-interview /transcribe endpoint (ANA-5): when
    TRANSCRIPTION_PROVIDER resolves to a remote provider, the API process
    never touches WhisperX (no 1.5GB model in the request path, no lock
    serialization). Raises ``LocalProviderOnly`` for the local kind — the
    endpoint then runs its own locked local path.
    """
    import httpx

    cfg = resolve_transcription()
    p = cfg.provider
    if p.kind == "local_qwen_asr":
        return await _transcribe_qwen(cfg, file_path, language, priority="interactive")
    if p.kind == "local_whisperx":
        raise LocalProviderOnly(cfg.provider_id)
    if p.kind != "openai_compat":
        raise RuntimeError(f"Unknown provider kind: {p.kind!r}")

    from app.usage import media, runtime

    # Resolve credentials before loading/probing potentially expensive media.
    if not os.getenv(cfg.provider.api_key_env, "").strip():
        raise RuntimeError(
            f"TRANSCRIPTION_PROVIDER={cfg.provider_id} requires {cfg.provider.api_key_env}"
        )
    units = await pool("probe").run(media.audio_units, file_path)
    url, headers, audio_path = await pool("probe").run(
        _openai_compat_request_parts, cfg, file_path
    )
    data: dict[str, Any] = {"model": cfg.model, "response_format": "text"}
    if language and language.lower() != "auto":
        data["language"] = language
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=False) as client:

        async def send():
            return await _send_audio(client, url, headers, data, audio_path)

        resp = await runtime.invoke_async(
            send,
            observed=lambda _: units,
            **(
                await pool("probe").run(
                    media.descriptor, cfg, file_path, language, units
                )
            ),
        )
        resp.raise_for_status()
        return resp.text.strip()


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

    from app.usage import media, runtime

    # Resolve credentials before loading/probing potentially expensive media.
    if not os.getenv(cfg.provider.api_key_env, "").strip():
        raise RuntimeError(
            f"TRANSCRIPTION_PROVIDER={cfg.provider_id} requires {cfg.provider.api_key_env}"
        )
    units = await pool("probe").run(media.audio_units, file_path)
    url, headers, audio_path = await pool("probe").run(
        _openai_compat_request_parts, cfg, file_path
    )

    want_hybrid = _hybrid_diarization_wanted()
    if want_hybrid:
        data: dict[str, Any] = {
            "model": cfg.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "word",
        }
    else:
        data = {"model": cfg.model, "response_format": "text"}
    if language and language.lower() != "auto":
        data["language"] = language

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:

        async def send():
            return await _send_audio(client, url, headers, data, audio_path)

        resp = await runtime.invoke_async(
            send,
            observed=lambda _: units,
            **(
                await pool("probe").run(
                    media.descriptor, cfg, file_path, language, units
                )
            ),
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
            "skipping local diarization.",
            cfg.provider_id,
        )
        return f"**[Speaker 1]**: {flat}" if flat else ""

    from app.media.application.whisperx_engine import (
        align_remote_words_with_local_diarization,
    )

    return await pool("local").run(
        runtime.invoke_sync,
        lambda: align_remote_words_with_local_diarization(file_path, segments_in),
        observed=lambda _: units,
        meter="diarization",
        provider="local_pyannote",
        model="configured-pipeline",
        content=media.descriptor(cfg, file_path, language, units)["content"],
        units=units,
    )


__all__ = [
    "TranscriptionProvider",
    "PROVIDERS",
    "ResolvedTranscription",
    "resolve_transcription",
    "list_providers",
    "transcribe",
]


async def _transcribe_qwen(cfg, file_path, language, *, priority="background"):
    from app.local_inference.speech import transcribe_file
    from app.usage import media, runtime

    units = await pool("probe").run(media.audio_units, file_path)
    desc = await pool("probe").run(media.descriptor, cfg, file_path, language, units)
    return await runtime.invoke_async(
        lambda: transcribe_file(
            file_path, model=cfg.model, language=language, priority=priority
        ),
        observed=lambda _: units,
        **desc,
    )
