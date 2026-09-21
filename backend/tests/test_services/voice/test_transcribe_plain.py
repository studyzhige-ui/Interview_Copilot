"""ANA-5: transcribe_plain provider dispatch (remote-first short clips)."""

from __future__ import annotations

import asyncio

import pytest
from app.media.application import transcription_registry as reg


def test_local_provider_raises_localprovideronly(monkeypatch):
    monkeypatch.setattr(
        reg,
        "resolve_transcription",
        lambda: reg.ResolvedTranscription(
            provider_id="local_whisperx",
            provider=reg.PROVIDERS["local_whisperx"],
            model="",
        ),
    )
    with pytest.raises(reg.LocalProviderOnly):
        asyncio.run(reg.transcribe_plain("clip.webm"))


def test_remote_provider_without_key_raises_runtime_error(monkeypatch, tmp_path):
    remote_id = next(
        pid for pid, p in reg.PROVIDERS.items() if p.kind == "openai_compat"
    )
    provider = reg.PROVIDERS[remote_id]
    monkeypatch.setattr(
        reg,
        "resolve_transcription",
        lambda: reg.ResolvedTranscription(
            provider_id=remote_id,
            provider=provider,
            model="whisper-x",
        ),
    )
    monkeypatch.delenv(provider.api_key_env, raising=False)
    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"\x1a\x45\xdf\xa3fake")
    with pytest.raises(RuntimeError, match=provider.api_key_env):
        asyncio.run(reg.transcribe_plain(str(clip)))


async def test_qwen_short_clip_calls_broker_not_whisper_or_cloud(monkeypatch):
    calls = []
    monkeypatch.setattr(
        reg,
        "resolve_transcription",
        lambda: reg.ResolvedTranscription(
            provider_id="local_qwen_asr",
            provider=reg.PROVIDERS["local_qwen_asr"],
            model="Qwen/Qwen3-ASR-1.7B",
        ),
    )

    async def transcribe(cfg, path, lang, *, priority="background"):
        calls.append((path, lang, priority))
        return "local text"

    monkeypatch.setattr(reg, "_transcribe_qwen", transcribe)
    assert await reg.transcribe_plain("owned.webm", "zh") == "local text"
    assert await reg.transcribe("owned.wav", "en") == "local text"
    assert calls == [
        ("owned.webm", "zh", "interactive"),
        ("owned.wav", "en", "background"),
    ]


async def test_qwen_call_is_wrapped_once_by_owner_accounting(monkeypatch):
    from app.local_inference import speech
    from app.usage import media, runtime

    cfg = reg.ResolvedTranscription(
        "local_qwen_asr", reg.PROVIDERS["local_qwen_asr"], "Qwen/test"
    )
    monkeypatch.setattr(
        media, "audio_units", lambda _: {"requests": 1, "audio_ms": 1000, "bytes": 4000}
    )
    monkeypatch.setattr(
        media,
        "descriptor",
        lambda c, p, lang, u: dict(
            meter="transcription",
            provider=c.provider_id,
            model=c.model,
            units=u,
            content={},
        ),
    )
    calls = []

    async def invoke(call, *, observed, **desc):
        calls.append(desc)
        result = await call()
        assert observed(result)["audio_ms"] == 1000
        return result

    async def local(path, **kw):
        assert path == "owned.webm" and kw["model"] == "Qwen/test"
        return "answer"

    monkeypatch.setattr(runtime, "invoke_async", invoke)
    monkeypatch.setattr(speech, "transcribe_file", local)
    assert await reg._transcribe_qwen(cfg, "owned.webm", "zh") == "answer"
    assert len(calls) == 1 and calls[0]["provider"] == "local_qwen_asr"


async def test_short_clip_unknown_is_not_retryable_unavailability(monkeypatch):
    from app.media.application.short_clip_transcription import transcribe_short_clip
    from app.core.execution_errors import ConsumptionSettlementUnconfirmedError

    async def unknown(*args, **kw):
        raise ConsumptionSettlementUnconfirmedError("commit acknowledgement lost")

    monkeypatch.setattr(reg, "transcribe_plain", unknown)
    with pytest.raises(ConsumptionSettlementUnconfirmedError):
        await transcribe_short_clip("owned.webm")
