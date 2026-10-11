"""Lossless PCM ownership, stable speakers and strict wire validation."""

import struct
import pytest
from app.media.application.evidence_windows import evidence_windows
from app.media.application.speaker_identity import SpeakerIdentity
from app.local_inference.audio import pcm_payload, decode_pcm
from app.local_inference.client import make_audio_request
from app.local_inference.errors import ProtocolError


@pytest.mark.asyncio
@pytest.mark.parametrize("samples", [1, 16000, 26 * 16000, 30 * 16000 + 7, 1945878])
async def test_each_pcm_sample_belongs_to_exactly_one_core(samples):
    raw = b"\x23\x01" * samples

    async def blocks():
        for offset in range(0, len(raw), 14002):
            yield raw[offset : offset + 14002]

    windows = [
        w
        async for w in evidence_windows(
            blocks(), max_samples=samples, choose_end=lambda pcm, start, end: end
        )
    ]
    assert all(len(w.pcm) <= 30 * 16000 * 2 for w in windows)
    assert windows[0].core_start == 0 and windows[-1].core_end == samples
    assert all(
        left.core_end == right.core_start for left, right in zip(windows, windows[1:])
    )
    assert (
        b"".join(
            w.pcm[2 * (w.core_start - w.start) : 2 * (w.core_end - w.start)]
            for w in windows
        )
        == raw
    )


def test_swapped_local_labels_do_not_swap_recording_speakers():
    identities = SpeakerIdentity(max_speakers=2)
    first = identities.assign(
        [
            {"speaker_id": "a", "embedding": [1.0, 0.0]},
            {"speaker_id": "b", "embedding": [0.0, 1.0]},
        ]
    )
    second = identities.assign(
        [
            {"speaker_id": "b", "embedding": [1.0, 0.0]},
            {"speaker_id": "a", "embedding": [0.0, 1.0]},
        ]
    )
    assert first["a"] == second["b"] and first["b"] == second["a"]


def test_pcm_payload_cannot_be_substituted_or_exceed_model_window():
    pcm = struct.pack("<hhh", -32768, 0, 32767)
    payload = pcm_payload(pcm)
    assert decode_pcm(payload) == pcm
    with pytest.raises(ProtocolError):
        decode_pcm({**payload, "sha256": "0" * 64})
    with pytest.raises(ProtocolError):
        pcm_payload(bytes(30 * 16000 * 2 + 2))


@pytest.mark.parametrize("count", [0, 33, True, 1.5])
def test_speaker_request_rejects_unbounded_configuration(count):
    with pytest.raises(ProtocolError):
        make_audio_request("diarization", "a" * 64, bytes(20), max_speakers=count)


@pytest.mark.asyncio
async def test_generic_and_remote_asr_share_bounded_broker_speaker_identity(
    monkeypatch,
):
    import numpy as np
    from app.media.application import whisperx_engine as engine

    calls = []

    class Observations:
        async def diarize(self, pcm, *, max_speakers):
            duration = len(pcm) / 32000
            calls.append(duration)
            label = f"window_{len(calls)}"
            return {
                "regular": [{"start": 0.0, "end": duration, "speaker_id": label}],
                "exclusive": [{"start": 0.0, "end": duration, "speaker_id": label}],
                "speakers": [{"speaker_id": label, "embedding": [1.0, 0.0]}],
            }

    monkeypatch.setattr(engine, "diarize_model", Observations())
    monkeypatch.setattr(engine.settings, "DIARIZATION_MIN_SPEAKERS", 1)
    duration = 61.25
    result = await engine._diarization_frame(
        np.zeros(int(duration * 16000), dtype=np.float32)
    )
    assert len(calls) > 1 and max(calls) <= 30
    assert result["start"].iloc[0] == 0 and result["end"].iloc[-1] == duration
    assert list(result["start"].iloc[1:]) == list(result["end"].iloc[:-1])
    assert set(result["speaker"]) == {"speaker_001"}
    previous = len(calls)
    with pytest.raises(ValueError, match="invalid_diarization_audio"):
        await engine._diarization_frame(np.array([float("nan")]))
    assert len(calls) == previous
    monkeypatch.setattr(engine.settings, "DIARIZATION_MIN_SPEAKERS", 2)
    with pytest.raises(ValueError, match="recording_speaker_count_below_minimum"):
        await engine._diarization_frame(np.zeros(16000, dtype=np.float32))


def test_configured_hybrid_never_silently_becomes_single_speaker(monkeypatch):
    from app.media.application import whisperx_engine as engine

    monkeypatch.setattr(engine, "diarize_model", None)
    monkeypatch.setattr(engine.settings, "TRANSCRIPTION_PROVIDER", "openai")
    monkeypatch.setattr(engine.settings, "DIARIZATION_MODE", "pyannote")
    with pytest.raises(RuntimeError, match="configured_diarization_client_unavailable"):
        engine.align_remote_words_with_local_diarization(
            "unused.wav", [{"text": "hello"}]
        )
    monkeypatch.setattr(engine.settings, "DIARIZATION_MODE", "none")
    assert (
        engine.align_remote_words_with_local_diarization(
            "unused.wav", [{"text": "hello"}]
        )
        == "**[Speaker 1]**: hello"
    )
