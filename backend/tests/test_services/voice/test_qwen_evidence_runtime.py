"""Broker binding and aggregate usage semantics; no model weights required."""

from types import SimpleNamespace

import pytest

from app.media.application import qwen_evidence as pipeline


@pytest.mark.asyncio
async def test_all_three_broker_bindings_are_frozen_before_inference(monkeypatch):
    from app.core.config import settings
    from app.local_inference import client

    calls = []

    class FakeClient:
        def __init__(self, socket_path, *, timeout):
            self.timeout = timeout

        async def acall(self, task, *, dimension):
            calls.append((task, dimension))
            return {}

    monkeypatch.setattr(client, "Client", FakeClient)
    monkeypatch.setattr(settings, "TRANSCRIPTION_ALIGNMENT_MODEL", "test-align")
    monkeypatch.setattr(settings, "DIARIZATION_MODEL_ID", "test-diarization")
    monkeypatch.setattr(settings, "MODEL_REVISIONS_JSON", {"test-asr": "revision-1"})
    stages = pipeline._BrokerStages("test-asr")
    bindings = dict(stages.bindings)
    monkeypatch.setattr(settings, "TRANSCRIPTION_ALIGNMENT_MODEL", "changed-align")
    monkeypatch.setattr(settings, "DIARIZATION_MODEL_ID", "changed-diarization")
    monkeypatch.setattr(settings, "MODEL_REVISIONS_JSON", {"test-asr": "revision-2"})
    pcm = b"\x00\x00" * 160
    await stages.call("transcription", pcm, language="zh")
    await stages.call("alignment", pcm, text="hello", language="English")
    await stages.call("diarization", pcm)
    assert stages.models == pipeline.StageModels(
        "test-asr@revision-1", "test-align", "test-diarization"
    )
    assert [task["role"] for task, _ in calls] == ["transcription", "alignment", "diarization"]
    assert all(task["binding"] == bindings[task["role"]] for task, _ in calls)
    assert all(task["priority"] == "background" and dimension == 1 for task, dimension in calls)
    assert stages.completed_calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("completed,failure", [(0, "not_started"), (1, "not_started"), (1, "decode"), (0, "unknown")])
async def test_partial_inference_cannot_be_refunded_or_automatically_retried(monkeypatch, completed, failure):
    from app.local_inference.client import LocalInferenceNotStarted, LocalInferenceUnknown
    from app.media.application import pcm_stream

    closed = []

    class Source:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            closed.append(True)

    errors = {
        "not_started": LocalInferenceNotStarted("not_available"),
        "decode": ValueError("decode_incomplete"),
        "unknown": LocalInferenceUnknown("unknown_response"),
    }
    calls = []

    async def fail(*args, **kwargs):
        calls.append(True)
        raise errors[failure]

    monkeypatch.setattr(pcm_stream, "PCMStream", Source)
    monkeypatch.setattr(pipeline, "collect_qwen_parts", fail)
    expected = LocalInferenceUnknown if completed or failure == "unknown" else LocalInferenceNotStarted
    with pytest.raises(expected):
        await pipeline._collect_file(
            "snapshot.audio", SimpleNamespace(completed_calls=completed),
            max_bytes=100, max_ms=1_000, language="zh",
        )
    assert len(calls) == 1 and closed == [True]


def test_sync_adapter_uses_the_existing_worker_entry_contract(monkeypatch):
    from app.core.config import settings

    stages = object()
    calls = []
    monkeypatch.setattr(pipeline, "_BrokerStages", lambda model: stages)

    async def collect(path, actual, **kwargs):
        calls.append((path, actual, kwargs))
        return "complete-parts"

    monkeypatch.setattr(pipeline, "_collect_file", collect)
    assert pipeline.collect_qwen_evidence_sync(
        "snapshot.audio", model="asr", language="zh"
    ) == "complete-parts"
    assert calls == [("snapshot.audio", stages, {
        "max_bytes": settings.USAGE_AUDIO_MAX_BYTES,
        "max_ms": settings.USAGE_AUDIO_MAX_MS,
        "language": "zh",
    })]
