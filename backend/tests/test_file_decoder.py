"""Actual FFmpeg input/output, including failure after reading source bytes."""

import os
import wave
import pytest
from app.media.application.pcm_stream import PCMStream

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="decoder requires Linux/WSL2"
)


@pytest.mark.asyncio
async def test_fractional_recording_decodes_completely_in_bounded_blocks(tmp_path):
    path = tmp_path / "fractional.wav"
    samples = 31 * 16000 + 137
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x01\x00" * samples)
    async with PCMStream(str(path), max_bytes=2_000_000, max_ms=40_000) as source:
        blocks = [part async for part in source]
    assert sum(len(part) for part in blocks) == samples * 2
    assert all(0 < len(part) <= 960000 for part in blocks)


@pytest.mark.asyncio
async def test_broken_audio_is_not_successful_empty_transcription(tmp_path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"not an audio container")
    with pytest.raises((ValueError, RuntimeError)):
        async with PCMStream(str(path), max_bytes=1000, max_ms=1000) as source:
            async for _ in source:
                pass
