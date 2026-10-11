"""Real bounded decoding and the production WhisperX/Pyannote adapter contract.

Deterministic model observations test orchestration, not speech model quality.
"""

import asyncio
from contextlib import nullcontext
import hashlib
import os
import shutil
import sys
from types import SimpleNamespace
import wave

import numpy as np
import pytest

from app.media.application import whisperx_engine as engine
from app.media.application import pcm_stream
from app.media.application.evidence_pipeline import compose_transcript_evidence
from app.media.application.evidence_source import EvidenceSource

pytestmark = pytest.mark.skipif(
    os.name != "posix" or shutil.which("ffmpeg") is None,
    reason="real bounded decoder requires FFmpeg on POSIX",
)


class Annotation:
    def __init__(self, rows):
        self.rows = rows

    def labels(self):
        return sorted({row[2] for row in self.rows})

    def itertracks(self, yield_label):
        assert yield_label
        for start, end, label in self.rows:
            yield SimpleNamespace(start=start, end=end), 0, label


@pytest.fixture
def recording(monkeypatch, tmp_path):
    path = tmp_path / "recording.wav"
    duration = 80.125
    samples = (np.arange(int(duration * 16000)) // 16000 + 1).astype("<i2")
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(samples.tobytes())
    state = SimpleNamespace(
        path=str(path),
        duration=duration,
        calls=[],
        processes=[],
        fault=None,
        rows=[
            ("Hello,", 1, 1.5, "A"),
            ("go", 25, 25.2, "A"),
            ("go!", 26, 26.2, "B"),
            ("again", 50.5, 50.8, "A"),
            ("done.", 53, 53.4, "B"),
            ("last", 79, 79.4, "A"),
        ],
    )

    def rows_for(audio):
        start = int(round(float(audio[0]) * 32768)) - 1
        duration = len(audio) / 16000
        assert 0 < duration <= 30
        return start, [
            r for r in state.rows if start <= r[1] and r[2] <= start + duration
        ]

    def transcribe(audio, **kwargs):
        start, rows = rows_for(audio)
        state.calls.append(start)
        if state.fault == "cancel":
            asyncio.current_task().cancel()
        if state.fault == "model" and start:
            raise RuntimeError("model_failed_after_first_window")
        if state.fault == "identity" and start:
            monkeypatch.setattr(engine, "_whisper_model_id", "changed")
        text = " ".join(r[0] for r in rows)
        if state.fault == "missing_text" and start:
            text = ""
        return {"language": "en", "segments": [{"text": text}] if text else []}

    def align(segments, model, metadata, audio, device, **kwargs):
        start, rows = rows_for(audio)
        words = [
            {
                "word": r[0],
                "start": np.float64(r[1] - start),
                "end": np.float64(r[2] - start),
                "score": np.float64(0.9),
            }
            for r in rows
        ]
        if state.fault == "seam" and start:
            for word in words[:2]:
                word["start"] += 3
                word["end"] += 3
        if state.fault == "time" and start and words:
            words[0]["start"] = -1
        if state.fault == "unaligned" and not start:
            words[0]["start"] = words[0]["end"] = None
        return {"word_segments": words}

    def diarize(data, **kwargs):
        assert kwargs == {"min_speakers": 1, "max_speakers": 2}
        start, rows = rows_for(data["waveform"][0])
        labels = (
            {"A": "local_0", "B": "local_1"}
            if start == 0
            else {"A": "local_1", "B": "local_0"}
        )
        tracks = Annotation([(r[1] - start, r[2] - start, labels[r[3]]) for r in rows])
        inverse = {v: k for k, v in labels.items()}
        vectors = np.array(
            [
                [1.0, 0.0] if inverse[label] == "A" else [0.0, 1.0]
                for label in tracks.labels()
            ]
        )
        if state.fault == "speaker" and start:
            vectors[:] = [0.7, 0.7]
        return SimpleNamespace(
            speaker_diarization=Annotation(
                tracks.rows + [(25.8 - start, 26.3 - start, labels["A"])]
            )
            if state.fault == "overlap"
            and start <= 25.8
            and 26.3 <= start + len(data["waveform"][0]) / 16000
            else tracks,
            exclusive_speaker_diarization=tracks,
            speaker_embeddings=vectors,
        )

    class ObservedPCM(pcm_stream.PCMStream):
        async def __aenter__(self):
            await super().__aenter__()
            state.processes.append(self)
            return self

        async def __anext__(self):
            if state.fault == "decoder" and self.consumed:
                raise ValueError("late_decoder_failure")
            return await super().__anext__()

    monkeypatch.setattr(pcm_stream, "PCMStream", ObservedPCM)
    monkeypatch.setattr(engine, "whisper_model", SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(engine, "diarize_model", SimpleNamespace(model=diarize))
    monkeypatch.setattr(engine, "_whisper_model_id", "whisperx-test")
    monkeypatch.setattr(engine, "_diarization_model_id", "community-test")
    monkeypatch.setattr(
        engine, "_get_alignment_model", lambda _: (object(), {}, "align-test")
    )
    monkeypatch.setattr(engine, "_local_device", lambda: "cpu")
    monkeypatch.setattr(engine.settings, "DIARIZATION_MIN_SPEAKERS", 2)
    monkeypatch.setattr(engine.settings, "DIARIZATION_MAX_SPEAKERS", 2)
    monkeypatch.setitem(sys.modules, "whisperx", SimpleNamespace(align=align))
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(inference_mode=nullcontext, from_numpy=lambda x: x),
    )
    return state


def collect(state):
    return engine.collect_interview_evidence_sync(
        state.path, model="whisperx-test", language="auto"
    )


def assert_closed(state):
    assert len(state.processes) == 1
    assert state.processes[0].fd is None
    assert state.processes[0].process.returncode is not None


def test_production_collector_preserves_words_duration_speakers_and_source(recording):
    parts = collect(recording)
    assert parts.complete
    assert parts.transcript.duration_seconds == recording.duration
    assert recording.calls == [0, 24, 50, 76]
    assert [w["text"].strip() for w in parts.transcript.words] == [
        r[0] for r in recording.rows
    ]
    assert all(w["score"] == 0.9 for w in parts.transcript.words)
    source = EvidenceSource(recording.path, "asset", "v1", "a" * 64, 100)
    evidence = compose_transcript_evidence(source, parts, max_duration_ms=81_000)
    assert [w.speaker_id for w in evidence.words] == [
        "speaker_001",
        "speaker_001",
        "speaker_002",
        "speaker_001",
        "speaker_002",
        "speaker_001",
    ]
    assert evidence.words[-1].end == 79.4
    assert_closed(recording)


@pytest.mark.parametrize(
    "fault, error",
    [
        ("model", "model_failed"),
        ("identity", "identity_changed"),
        ("speaker", "speaker_identity_ambiguous"),
        ("decoder", "late_decoder_failure"),
        ("missing_text", "speech_without_text"),
        ("time", "word_time"),
        ("seam", "boundary_ambiguous"),
    ],
)
def test_failed_later_window_never_returns_partial_evidence_or_retries(
    recording, fault, error
):
    recording.fault = fault
    with pytest.raises((ValueError, RuntimeError), match=error):
        collect(recording)
    assert recording.calls in ([0], [0, 24])
    assert_closed(recording)


def test_duration_overflow_is_not_truncated_success(recording, monkeypatch):
    monkeypatch.setattr(engine.settings, "USAGE_AUDIO_MAX_MS", 30_000)
    with pytest.raises(ValueError, match="duration_exceeds_limit"):
        collect(recording)
    assert_closed(recording)


def test_silence_windows_and_speaker_return_after_gap(recording):
    recording.rows = [
        ("first", 1, 1.5, "A"),
        ("second", 60, 60.5, "B"),
        ("back", 79, 79.4, "A"),
    ]
    result = collect(recording)
    assert [w["text"].strip() for w in result.transcript.words] == [
        "first",
        "second",
        "back",
    ]
    assert {r["speaker_id"] for r in result.speakers.regular} == {
        "speaker_001",
        "speaker_002",
    }
    assert_closed(recording)


def test_entrypoint_uses_snapshot_and_only_publishes_complete_graph(
    recording, monkeypatch
):
    from app.media.application import audio_transcription_service as service
    from app.media.application.evidence_pipeline import resolve_evidence_collector
    from app.usage import media, runtime
    from pathlib import Path

    checksum = hashlib.sha256(Path(recording.path).read_bytes()).hexdigest()
    monkeypatch.setattr(media, "audio_units", lambda _: {"audio_ms": 80_125})
    monkeypatch.setattr(media, "descriptor", lambda *args: {})
    monkeypatch.setattr(runtime, "invoke_sync", lambda call, **kwargs: call())
    result = service._collect_evidence(
        recording.path,
        file_asset_id="asset",
        file_asset_version=f"sha256:{checksum}",
        language="en",
        config=SimpleNamespace(model="whisperx-test"),
        collector=resolve_evidence_collector("local_whisperx"),
    )
    assert result.audio.sha256 == checksum
    assert result.audio.duration_seconds == recording.duration
    assert len(result.words) == len(recording.rows)
    assert_closed(recording)


@pytest.mark.asyncio
async def test_cancellation_between_windows_stops_models_and_reaps_decoder(recording):
    recording.fault = "cancel"
    task = asyncio.create_task(
        engine._collect_windowed_evidence(
            recording.path, model="whisperx-test", language="en"
        )
    )
    with pytest.raises(asyncio.CancelledError):
        await task
    assert recording.calls == [0]
    assert_closed(recording)


def test_missing_alignment_stays_unknown_when_seam_has_a_real_anchor(recording):
    recording.fault = "unaligned"
    result = collect(recording)
    assert result.transcript.words[0]["text"] == "Hello, "
    assert result.transcript.words[0]["start"] is None
    assert result.transcript.words[0]["end"] is None
    assert len(result.transcript.words) == len(recording.rows)
    assert_closed(recording)


def test_recording_capacity_failure_is_not_partial_success(recording, monkeypatch):
    from app.media.application import evidence_contracts

    monkeypatch.setattr(evidence_contracts, "MAX_EVIDENCE_WORDS", 3)
    with pytest.raises(ValueError, match="evidence_capacity"):
        collect(recording)
    assert_closed(recording)


def test_overlapping_speech_survives_core_clipping(recording):
    recording.fault = "overlap"
    parts = collect(recording)
    evidence = compose_transcript_evidence(
        EvidenceSource(recording.path, "asset", "v1", "a" * 64, 100),
        parts,
        max_duration_ms=81_000,
    )
    assert evidence.words[2].overlap is True
    assert evidence.words[2].speaker_id == "speaker_002"
    assert_closed(recording)


def test_partial_model_work_keeps_unknown_usage_not_refunded(recording, monkeypatch):
    from app.media.application import audio_transcription_service as service
    from app.media.application.evidence_pipeline import resolve_evidence_collector
    from app.usage import media, runtime
    from app.core.execution_errors import ModelOutcomeUnknownError

    outcomes = []
    recording.fault = "model"
    monkeypatch.setattr(media, "audio_units", lambda _: {"audio_ms": 80_125})
    monkeypatch.setattr(media, "descriptor", lambda *args: {})
    monkeypatch.setattr(runtime, "begin", lambda **kwargs: object())
    monkeypatch.setattr(
        runtime, "finish", lambda receipt, outcome, *args: outcomes.append(outcome)
    )
    with pytest.raises(ModelOutcomeUnknownError, match="consumption_outcome_unknown"):
        service._collect_evidence(
            recording.path,
            file_asset_id="asset",
            file_asset_version="legacy-version",
            language="en",
            config=SimpleNamespace(model="whisperx-test"),
            collector=resolve_evidence_collector("local_whisperx"),
        )
    assert recording.calls == [0, 24]
    assert outcomes == ["unknown"]
    assert_closed(recording)
