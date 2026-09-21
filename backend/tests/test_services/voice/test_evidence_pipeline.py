"""Capabilities and evidence invariants independent of the ASR implementation."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.media.application import evidence_pipeline as pipeline
from app.media.application.evidence_contracts import (
    AlignedTranscript,
    EvidenceParts,
    SpeakerEvidence,
)
from app.media.application.evidence_pipeline import (
    EvidenceProviderUnsupported,
    compose_transcript_evidence,
    resolve_evidence_collector,
)
from app.media.application.evidence_source import EvidenceSource


@pytest.fixture
def parts():
    return EvidenceParts(
        transcript=AlignedTranscript(
            words=[
                {"text": "Hello", "start": 0.0, "end": 0.4},
                {"text": " world!", "start": 0.5, "end": 1.0},
            ],
            duration_seconds=2.0,
            language="en",
            asr_model="test-asr",
            alignment_model="test-aligner",
        ),
        speakers=SpeakerEvidence(
            regular=[{"start": 0.0, "end": 2.0, "speaker_id": "speaker_A"}],
            exclusive=[{"start": 0.0, "end": 2.0, "speaker_id": "speaker_A"}],
            model="test-diarizer",
        ),
        complete=True,
    )


def compose(parts):
    return compose_transcript_evidence(
        EvidenceSource("unused", "fa_test", "v1", "0" * 64, 123),
        parts,
        max_duration_ms=10_000,
    )


def test_complete_components_produce_stable_provider_neutral_evidence(parts):
    evidence = compose(parts)
    assert [word.word_id for word in evidence.words] == ["w000001", "w000002"]
    assert "".join(word.text for word in evidence.words) == "Hello world!"
    assert evidence.models.model_dump() == {
        "asr": "test-asr",
        "alignment": "test-aligner",
        "diarization": "test-diarizer",
    }
    assert evidence.audio.file_asset_id == "fa_test"
    assert evidence.words[0].speaker_id == "speaker_A"
    assert compose(parts).model_dump() == evidence.model_dump()


@pytest.mark.parametrize("kind", ["local_qwen_asr", "openai_compat", "unknown"])
def test_asr_only_or_remote_provider_cannot_claim_complete_evidence(kind):
    with pytest.raises(EvidenceProviderUnsupported, match="provider_unsupported"):
        resolve_evidence_collector(kind)


def test_partial_output_is_never_publishable(parts):
    with pytest.raises(ValueError, match="evidence_incomplete"):
        compose(replace(parts, complete=False))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "0", -1, 3])
def test_invalid_word_timing_is_not_coerced_or_clipped(parts, value):
    parts.transcript.words[0]["start"] = value
    with pytest.raises(ValueError, match="word_time"):
        compose(parts)


def test_missing_alignment_cannot_hide_backwards_time(parts):
    parts.transcript.words[:] = [
        {"text": "late", "start": 1.0, "end": 1.1},
        {"text": "unknown", "start": None, "end": None},
        {"text": "early", "start": 0.5, "end": 0.6},
    ]
    with pytest.raises(ValueError, match="word_time"):
        compose(parts)


def test_unknown_alignment_is_preserved_not_fabricated(parts):
    parts.transcript.words.append({"text": " unknown", "start": None, "end": None})
    word = compose(parts).words[-1]
    assert word.start is None and word.end is None
    assert word.alignment_status == "missing" and word.speaker_id is None


@pytest.mark.parametrize("track", ["regular", "exclusive"])
def test_missing_speaker_tracks_are_not_single_speaker_success(parts, track):
    getattr(parts.speakers, track).clear()
    with pytest.raises(ValueError, match="diarization_missing"):
        compose(parts)


def test_exclusive_track_must_really_be_exclusive(parts):
    parts.speakers.exclusive.append(
        {"start": 1.0, "end": 1.5, "speaker_id": "speaker_A"}
    )
    with pytest.raises(ValueError, match="diarization_time"):
        compose(parts)


def test_exclusive_track_cannot_invent_a_new_speaker(parts):
    parts.speakers.exclusive[0]["speaker_id"] = "invented"
    with pytest.raises(ValueError, match="exclusive_speaker_unknown"):
        compose(parts)


def test_output_and_duration_budgets_are_enforced(monkeypatch, parts):
    monkeypatch.setattr(pipeline, "MAX_EVIDENCE_TEXT_BYTES", 5)
    with pytest.raises(ValueError, match="text_capacity"):
        compose(parts)
    with pytest.raises(ValueError, match="evidence_duration"):
        compose(
            replace(parts, transcript=replace(parts.transcript, duration_seconds=11))
        )


async def test_entrypoint_passes_frozen_config_without_resolving_again(monkeypatch):
    from app.media.application import audio_transcription_service as service

    config = SimpleNamespace(
        provider=SimpleNamespace(kind="test_complete"),
        model="fixed",
        provider_id="test",
    )
    collector = object()
    monkeypatch.setitem(pipeline._EVIDENCE_COLLECTORS, "test_complete", collector)
    monkeypatch.setattr(
        service, "resolve_transcription", lambda: pytest.fail("resolved twice")
    )
    calls = []

    def run(path, **kwargs):
        calls.append((path, kwargs))
        return "test-evidence"

    monkeypatch.setattr(service, "_collect_evidence", run)
    result = await service.transcribe_interview_evidence(
        "owned.wav", file_asset_id="fa_test", file_asset_version="v1", config=config
    )
    assert result == "test-evidence"
    assert len(calls) == 1
    assert calls[0][1]["config"] is config
    assert calls[0][1]["collector"] is collector


async def test_unsupported_provider_fails_before_file_or_worker_admission(monkeypatch):
    from app.media.application import audio_transcription_service as service
    from app.media.application import workers

    monkeypatch.setattr(
        workers, "pool", lambda _: pytest.fail("admitted unsupported work")
    )
    config = SimpleNamespace(provider=SimpleNamespace(kind="local_qwen_asr"))
    with pytest.raises(EvidenceProviderUnsupported):
        await service.transcribe_interview_evidence(
            "missing.wav",
            file_asset_id="fa_test",
            file_asset_version="v1",
            config=config,
        )


@pytest.mark.parametrize("value", [True, "0.9", float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_confidence_is_not_a_valid_observation(parts, value):
    parts.transcript.words[0]["score"] = value
    with pytest.raises(ValueError, match="word_confidence"):
        compose(parts)


def test_whisperx_adapter_reports_loaded_models_not_current_setting_labels(monkeypatch):
    import sys
    import numpy as np
    from app.media.application import whisperx_engine as engine

    monkeypatch.setattr(
        engine,
        "whisper_model",
        SimpleNamespace(
            transcribe=lambda *a, **k: {"language": "en", "segments": [{"text": "Hi"}]}
        ),
    )
    monkeypatch.setattr(engine, "_whisper_model_id", "loaded-asr")
    monkeypatch.setattr(engine, "_diarization_model_id", "loaded-diarizer")
    monkeypatch.setattr(engine, "_ensure_ffmpeg_available", lambda: "ffmpeg")
    monkeypatch.setattr(engine, "_local_device", lambda: "cpu")
    monkeypatch.setattr(
        engine, "_get_alignment_model", lambda _: (object(), {}, "loaded-aligner")
    )
    tracks = [{"start": 0.0, "end": 1.0, "speaker_id": "S0"}]
    monkeypatch.setattr(engine, "_run_diarization_tracks", lambda _: (tracks, tracks))
    monkeypatch.setitem(
        sys.modules,
        "whisperx",
        SimpleNamespace(
            load_audio=lambda _: np.zeros(16_000),
            align=lambda *a, **k: {
                "word_segments": [{"word": "Hi", "start": 0.0, "end": 0.5}]
            },
        ),
    )
    result = engine.collect_interview_evidence_sync(
        "captured.audio", model="loaded-asr"
    )
    assert result.complete is True
    assert result.transcript.asr_model == "loaded-asr"
    assert result.transcript.alignment_model == "loaded-aligner"
    assert result.speakers.model == "loaded-diarizer"
    assert result.transcript.duration_seconds == 1.0
    with pytest.raises(RuntimeError, match="model_identity_changed"):
        engine.collect_interview_evidence_sync(
            "never-read.audio", model="different-asr"
        )
