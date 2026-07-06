"""ANA-5: transcribe_plain provider dispatch (remote-first short clips)."""
from __future__ import annotations

import asyncio

import pytest

from app.services.voice import transcription_registry as reg


def test_local_provider_raises_localprovideronly(monkeypatch):
    monkeypatch.setattr(
        reg, "resolve_transcription",
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
        reg, "resolve_transcription",
        lambda: reg.ResolvedTranscription(
            provider_id=remote_id, provider=provider, model="whisper-x",
        ),
    )
    monkeypatch.delenv(provider.api_key_env, raising=False)
    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"\x1a\x45\xdf\xa3fake")
    with pytest.raises(RuntimeError, match=provider.api_key_env):
        asyncio.run(reg.transcribe_plain(str(clip)))
