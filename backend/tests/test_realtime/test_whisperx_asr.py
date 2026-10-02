"""Finite PCM windows use the existing WhisperX worker and own their inputs."""

from pathlib import Path
import wave

import pytest

from app.core.config import settings
from app.media.realtime.asr import LiveASR


async def test_live_window_owns_pcm_file_until_worker_finishes(monkeypatch):
    from app.media.application import short_clip_transcription

    monkeypatch.setattr(settings, "TRANSCRIPTION_PROVIDER", "local_whisperx")
    paths = []
    pcm = b"\0\0" * 16000

    def local(path, language):
        paths.append(Path(path))
        assert language == "auto" and Path(path).is_file()
        with wave.open(path, "rb") as audio:
            assert (
                audio.getnchannels(),
                audio.getsampwidth(),
                audio.getframerate(),
            ) == (1, 2, 16000)
            assert audio.readframes(16000) == pcm
        return "synthetic transcript"

    monkeypatch.setattr(short_clip_transcription, "_local_clip", local)
    assert await LiveASR().window(pcm) == "synthetic transcript"
    assert len(paths) == 1 and not paths[0].exists()


async def test_live_asr_rejects_invalid_pcm_before_worker(monkeypatch):
    monkeypatch.setattr(settings, "TRANSCRIPTION_PROVIDER", "local_whisperx")
    for pcm in (b"", b"x", b"\0" * 960002):
        with pytest.raises(ValueError, match="invalid_pcm_size"):
            await LiveASR().window(pcm)
