"""Real FFmpeg / file lifecycle tests, no network or ASR weights."""

import asyncio
import hashlib
import os
import shutil
import wave

import pytest

from app.media.application.pcm_stream import PCMStream
from app.local_inference.audio import MAX_PCM_BYTES

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or os.name != "posix",
    reason="requires local FFmpeg on POSIX",
)


def make_wave(path, seconds=1):
    pcm = b"\x01\x00" * int(16000 * seconds)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(pcm)
    return pcm


async def test_real_decode_bounded_and_exact(tmp_path):
    path = tmp_path / "audio.wav"
    pcm = make_wave(path, 31)
    async with PCMStream(str(path), max_bytes=2_000_000, max_ms=60000) as stream:
        parts = [part async for part in stream]
        pid = stream.process.pid
        assert [len(v) for v in parts] == [MAX_PCM_BYTES, 32000]
        assert hashlib.sha256(b"".join(parts)).digest() == hashlib.sha256(pcm).digest()
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_early_exit_reaps_ffmpeg(tmp_path):
    path = tmp_path / "long.wav"
    make_wave(path, 100)
    async with PCMStream(str(path), max_bytes=4_000_000, max_ms=120000) as stream:
        await anext(stream)
        pid = stream.process.pid
    assert stream.process.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


async def test_decode_error_and_limit_are_not_partial_success(tmp_path):
    path = tmp_path / "audio.wav"
    make_wave(path, 2)
    with pytest.raises(ValueError, match="duration"):
        async with PCMStream(str(path), max_bytes=200000, max_ms=1000) as stream:
            [part async for part in stream]
    path.write_bytes(b"not an audio file")
    with pytest.raises(ValueError, match="decode_incomplete"):
        async with PCMStream(str(path), max_bytes=200000, max_ms=1000) as stream:
            [part async for part in stream]


async def test_decoder_pins_source_and_rejects_changed_file(tmp_path):
    path = tmp_path / "audio.wav"
    make_wave(path, 31)
    async with PCMStream(str(path), max_bytes=2_000_000, max_ms=60000) as stream:
        await anext(stream)
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
        with pytest.raises(ValueError, match="source_changed"):
            await anext(stream)


async def test_partial_local_transcription_rejection_is_unknown(monkeypatch, tmp_path):
    from app.local_inference import speech
    from app.local_inference.client import (
        LocalInferenceNotStarted,
        LocalInferenceUnknown,
    )

    path = tmp_path / "audio.wav"
    make_wave(path, 31)
    seen = []

    async def transcribe(self, pcm, **kw):
        seen.append(pcm)
        if len(seen) == 2:
            raise LocalInferenceNotStarted("capacity")
        return {"text": "first part"}

    monkeypatch.setattr(speech.SpeechClient, "transcribe", transcribe)
    with pytest.raises(LocalInferenceUnknown, match="partial"):
        await speech.transcribe_file(str(path), model="test")
    assert len(seen) == 2


async def test_first_chunk_rejection_stays_not_started(monkeypatch, tmp_path):
    from app.local_inference import speech
    from app.local_inference.client import LocalInferenceNotStarted

    path = tmp_path / "audio.wav"
    make_wave(path)

    async def rejected(self, pcm, **kw):
        raise LocalInferenceNotStarted("capacity")

    monkeypatch.setattr(speech.SpeechClient, "transcribe", rejected)
    with pytest.raises(LocalInferenceNotStarted):
        await speech.transcribe_file(str(path), model="test")


async def test_decoder_repeated_cancel_reaps(tmp_path):
    path = tmp_path / "audio.wav"
    make_wave(path, 90)
    entered = asyncio.Event()
    stream = PCMStream(str(path), max_bytes=4000000, max_ms=100000)

    async def consume():
        async with stream:
            await anext(stream)
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(consume())
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.fd is None and stream.process.returncode is not None


@pytest.mark.parametrize("timeout", [True, float("nan"), float("inf"), "3", 0, -1])
def test_decoder_rejects_invalid_wait_limits(timeout):
    with pytest.raises(ValueError, match="invalid_decoder_limits"):
        PCMStream("never-opened", max_bytes=1000, max_ms=1000, read_timeout=timeout)


@pytest.mark.parametrize(
    "content",
    [
        "ffconcat version 1.0\nfile '/etc/passwd'\n",
        "#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n",
    ],
)
async def test_decoder_rejects_playlists_not_just_network_protocols(tmp_path, content):
    path = tmp_path / "recording.wav"
    path.write_text(content)
    async with PCMStream(str(path), max_bytes=10000, max_ms=10000) as decoder:
        with pytest.raises(ValueError, match="audio_decode_incomplete"):
            await anext(decoder)
    assert decoder.process.returncode is not None
