"""Lossless PCM ownership, stable speakers and strict wire validation."""

import struct
import pytest
from app.media.application.evidence_windows import evidence_windows
from app.media.application.recording_speakers import RecordingSpeakers
from app.local_inference.audio import pcm_payload, decode_pcm
from app.local_inference.client import make_audio_request
from app.local_inference.errors import ProtocolError
from app.local_inference.speaker_audio import (
    validate_clustering_request,
    validate_clustering_result,
    encode_embeddings,
    decode_embeddings,
    MAX_RECORDING_OBSERVATIONS,
)


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


@pytest.mark.asyncio
async def test_all_window_observations_reach_the_single_global_clusterer():
    identities = RecordingSpeakers()
    identities.observe([[1.0, 0.0], [0.0, 1.0]])
    identities.observe([[1.0, 0.0], [0.0, 1.0]])

    class Cluster:
        async def cluster(self, embeddings, **kwargs):
            assert embeddings == [[1.0, 0.0], [0.0, 1.0]] * 2
            return [[1.0, 0.0], [0.0, 1.0]]

    assert await identities.resolve(Cluster(), min_speakers=1, max_speakers=8) == [
        [1.0, 0.0],
        [0.0, 1.0],
    ]
    assert not identities.embeddings


def test_pcm_payload_cannot_be_substituted_or_exceed_model_window():
    pcm = struct.pack("<hhh", -32768, 0, 32767)
    payload = pcm_payload(pcm)
    assert decode_pcm(payload) == pcm
    with pytest.raises(ProtocolError):
        decode_pcm({**payload, "sha256": "0" * 64})
    with pytest.raises(ProtocolError):
        pcm_payload(bytes(30 * 16000 * 2 + 2))


def test_global_speaker_clustering_bounds_and_output_shape():
    task = {
        "embeddings": encode_embeddings([[1.0, 0.0], [0.0, 1.0]]),
        "min_speakers": 1,
        "max_speakers": 2,
    }
    assert validate_clustering_request(task) is task
    assert validate_clustering_result(task, [[1.0, 0.0]]) == [[1.0, 0.0]]
    for vectors in (
        [[float("nan")]],
        [[0.0]],
        [[1.0], [1.0, 2.0]],
        [[1.0]] * (MAX_RECORDING_OBSERVATIONS + 1),
    ):
        with pytest.raises(ProtocolError):
            encode_embeddings(vectors)
    for labels in ([[1.0]], [[0.0, 0.0]], [[1.0, 0.0]] * 3):
        with pytest.raises(ProtocolError):
            validate_clustering_result(task, labels)


def test_recording_observations_preserve_float32_values_within_wire_capacity():
    from app.local_inference.protocol import frame

    vectors = [[0.25, -0.5] * 128] * MAX_RECORDING_OBSERVATIONS
    payload = encode_embeddings(vectors)
    assert decode_embeddings(payload) == vectors
    frame(payload)
    for corrupted in (
        {**payload, "dimension": 0},
        {**payload, "data": "%%%"},
        {**payload, "data": "AAAA"},
        {"dimension": 1, "data": "AADAfw=="},  # float32 NaN
    ):
        with pytest.raises(ProtocolError):
            decode_embeddings(corrupted)


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
        async def cluster(self, embeddings, **kwargs):
            return [[1.0, 0.0]]

        async def diarize(self, pcm, *, max_speakers, centroids=None):
            duration = len(pcm) / 32000
            calls.append(duration)
            label = "speaker_001" if centroids else f"window_{len(calls)}"
            return {
                "regular": [{"start": 0.0, "end": duration, "speaker_id": label}],
                "exclusive": [{"start": 0.0, "end": duration, "speaker_id": label}],
                "embeddings": [] if centroids else [[1.0, 0.0]],
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
    # Configured cluster bounds are model inputs, not proof of observed roles.
    result = await engine._diarization_frame(np.zeros(16000, dtype=np.float32))
    assert set(result["speaker"]) == {"speaker_001"}


@pytest.mark.parametrize("minimum, maximum", [(0, 2), (1, 33), (3, 2)])
def test_invalid_speaker_bounds_fail_at_configuration(minimum, maximum):
    from pydantic import ValidationError
    from app.core.config import Settings

    with pytest.raises(ValidationError, match="DIARIZATION"):
        Settings(
            _env_file=None,
            DIARIZATION_MIN_SPEAKERS=minimum,
            DIARIZATION_MAX_SPEAKERS=maximum,
        )


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
