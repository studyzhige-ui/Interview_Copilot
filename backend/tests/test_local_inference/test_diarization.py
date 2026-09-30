"""Wire/adapter/lifecycle regressions. No downloaded model or GPU is exercised."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from app.local_inference import child
from app.local_inference.broker import Broker
from app.local_inference.client import make_audio_request, checked_response
from app.local_inference.config import ModelSpec
from app.local_inference.process import environment
from app.local_inference.protocol import ProtocolError, request, validate_output
from app.local_inference.speaker_audio import validate_diarization_result


@pytest.fixture
def speaker_spec(tmp_path):
    return ModelSpec(
        "diarization",
        "pyannote/speaker-diarization-community-1",
        str(tmp_path),
        sys.executable,
        dimension=1,
        max_tokens=4096,
        reservation_mib=20,
    )


def observation():
    return {
        "regular": [
            {"start": 0.0, "end": 0.8, "speaker_id": "SPEAKER_00"},
            {"start": 0.6, "end": 1.0, "speaker_id": "SPEAKER_01"},
        ],
        "exclusive": [
            {"start": 0.0, "end": 0.7, "speaker_id": "SPEAKER_00"},
            {"start": 0.7, "end": 1.0, "speaker_id": "SPEAKER_01"},
        ],
        "speakers": [
            {"speaker_id": "SPEAKER_00", "embedding": [1.0, 0.0]},
            {"speaker_id": "SPEAKER_01", "embedding": [0.0, 1.0]},
        ],
    }


def task(spec):
    return make_audio_request(spec.role, spec.binding, b"\0\0" * 16000)


def test_diarization_is_a_distinct_finite_pcm_contract(speaker_spec):
    req = task(speaker_spec)
    assert req["operation"] == "diarize"
    assert request(req) == req
    assert speaker_spec.binding != replace(speaker_spec, role="alignment").binding
    assert speaker_spec.binding != replace(speaker_spec, revision="a" * 40).binding
    assert speaker_spec.binding == replace(speaker_spec, device="cuda").binding
    for change in (
        {"path": "/private/upload.wav"},
        {"text": "prompt"},
        {"language": "zh"},
        {"operation": "transcribe"},
        {"audio": "https://cloud/audio"},
    ):
        with pytest.raises(ProtocolError):
            request({**req, **change})
    result = observation()
    assert validate_output(req, result, dimension=1) is result
    assert (
        checked_response(
            req,
            dict(
                id=req["id"], binding=req["binding"], status="completed", values=result
            ),
            1,
        )
        is result
    )


@pytest.mark.parametrize(
    "kind",
    [
        "extra",
        "nan",
        "boolean",
        "zero",
        "oversize",
        "dimensions",
        "duplicate",
        "unknown",
        "bad_time",
        "exclusive_overlap",
        "missing_vector",
        "missing_track",
    ],
)
def test_bad_speaker_outputs_fail_closed(speaker_spec, kind):
    value = deepcopy(observation())
    if kind == "extra":
        value["provider_key"] = "forbidden"
    elif kind in ("nan", "boolean", "zero", "oversize", "dimensions"):
        value["speakers"][0]["embedding"] = {
            "nan": [float("nan"), 0],
            "boolean": [True, 0],
            "zero": [0, 0],
            "oversize": [1] * 1025,
            "dimensions": [1],
        }[kind]
    elif kind == "duplicate":
        value["speakers"].append(value["speakers"][0])
    elif kind == "unknown":
        value["regular"][0]["speaker_id"] = "other"
    elif kind == "bad_time":
        value["regular"][0]["end"] = 1.1
    elif kind == "exclusive_overlap":
        value["exclusive"][0]["end"] = 0.8
    elif kind == "missing_vector":
        value["speakers"].pop()
    elif kind == "missing_track":
        value["exclusive"] = []
    with pytest.raises(ProtocolError):
        validate_diarization_result(task(speaker_spec), value)


def test_silence_and_regular_only_overlap_label_are_not_fabricated(speaker_spec):
    value = dict(regular=[], exclusive=[], speakers=[])
    assert validate_diarization_result(task(speaker_spec), value) is value
    value = observation()
    value["exclusive"] = [dict(start=0.0, end=1.0, speaker_id="SPEAKER_00")]
    assert validate_diarization_result(task(speaker_spec), value) is value


@pytest.fixture
def fake_torch(monkeypatch):
    module = SimpleNamespace(
        inference_mode=nullcontext,
        set_num_threads=lambda _: None,
        device=lambda name: name,
        from_numpy=lambda array: SimpleNamespace(
            unsqueeze=lambda axis: np.expand_dims(array, axis)
        ),
        cuda=SimpleNamespace(is_available=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "torch", module)
    return module


def test_official_pyannote_load_is_local_isolated_and_cuda_explicit(
    speaker_spec, fake_torch, monkeypatch
):
    calls = []
    pipeline = SimpleNamespace(to=lambda device: calls.append(device))

    def load(path):
        calls.append(path)
        return pipeline

    monkeypatch.setitem(
        sys.modules,
        "pyannote.audio",
        SimpleNamespace(Pipeline=SimpleNamespace(from_pretrained=load)),
    )
    assert child.load_model(speaker_spec) is pipeline
    assert calls == [speaker_spec.model_path, "cpu"]
    assert pipeline.segmentation_batch_size == pipeline.embedding_batch_size == 1
    with pytest.raises(RuntimeError, match="cuda_unavailable"):
        child.load_model(replace(speaker_spec, device="cuda"))
    env = environment(Path(speaker_spec.model_path))
    assert env["PYANNOTE_METRICS_ENABLED"] == "0"
    assert env["HF_HUB_OFFLINE"] == "1"
    assert not any(
        "KEY" in key
        or "TOKEN" in key
        and key != "HF_HUB_DISABLE_IMPLICIT_TOKEN"
        and key != "TOKENIZERS_PARALLELISM"
        for key in env
    )


def test_official_output_label_order_maps_to_corresponding_vector(
    speaker_spec, fake_torch
):
    value = observation()

    class Annotation:
        def __init__(self, rows):
            self.rows = rows

        def labels(self):
            return ["SPEAKER_00", "SPEAKER_01"]

        def itertracks(self, *, yield_label):
            assert yield_label is True
            for row in reversed(self.rows):
                yield (
                    SimpleNamespace(start=row["start"], end=row["end"]),
                    0,
                    row["speaker_id"],
                )

    def pipeline(audio, **kwargs):
        assert audio["waveform"].shape == (1, 16000)
        assert audio["waveform"].dtype == np.float32
        assert audio["sample_rate"] == 16000
        assert kwargs == dict(min_speakers=1, max_speakers=32)
        return SimpleNamespace(
            speaker_diarization=Annotation(value["regular"]),
            exclusive_speaker_diarization=Annotation(value["exclusive"]),
            speaker_embeddings=np.array([[1.0, 0.0], [0.0, 1.0]]),
        )

    assert child.infer(pipeline, speaker_spec, task(speaker_spec)) == value


async def test_broker_routes_and_cancels_diarization_with_owned_cleanup(
    config, speaker_spec
):
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []

    class Process:
        def __init__(self, spec, _cache):
            assert spec.role == "diarization"

        async def start(self):
            pass

        async def run(self, req):
            entered.set()
            await release.wait()
            return dict(
                id=req["id"],
                binding=req["binding"],
                status="completed",
                values=observation(),
            )

        async def close(self):
            closed.append(True)

    broker = Broker(replace(config, models=(speaker_spec,)), factory=Process)
    broker.start()
    try:
        job = broker.submit(task(speaker_spec))
        await asyncio.wait_for(entered.wait(), 1)
        broker.cancel(job)
        assert (await job.future)["status"] == "unknown"
        assert closed == [True]
        release.set()
        assert (await broker.submit(task(speaker_spec)).future)[
            "values"
        ] == observation()
    finally:
        await broker.close()


async def test_lightweight_client_freezes_revision_and_keeps_vectors_off_receipts(
    speaker_spec, monkeypatch
):
    from app.local_inference.diarization import DiarizationClient
    from app.core.config import settings

    calls = []

    class Proxy:
        timeout = 5

        async def acall(self, req, *, dimension):
            calls.append(req)
            assert dimension == 1
            return observation()

    monkeypatch.setattr(settings, "MODEL_REVISIONS_JSON", {})
    proxy = DiarizationClient(model=speaker_spec.model_id, client=Proxy())
    monkeypatch.setattr(
        settings, "MODEL_REVISIONS_JSON", {speaker_spec.model_id: "b" * 40}
    )
    assert await proxy.diarize(b"\0\0" * 16000) == observation()
    assert calls[0]["binding"] == speaker_spec.binding
    assert set(calls[0]) == {
        "version",
        "id",
        "role",
        "binding",
        "operation",
        "audio",
        "text",
        "language",
        "priority",
        "timeout",
    }


def test_prepare_diarization_requires_explicit_interpreter_and_pipeline_assets(
    config, monkeypatch
):
    from scripts.prepare_local_inference import build_config
    from app.core.model_assets import ModelInspection

    def inspect(model_id, **kwargs):
        layout = "pipeline_bundle" if "pyannote/" in model_id else "transformers"
        return ModelInspection(
            model_id,
            config.models[0].model_path,
            "bundle_requires_loader"
            if layout == "pipeline_bundle"
            else "structurally_valid",
            layout,
        )

    monkeypatch.setattr("scripts.prepare_local_inference.inspect_model", inspect)
    options = dict(
        python=sys.executable,
        device="cpu",
        runtime_dir=Path(config.socket_path).parent,
        model_root=Path(config.models[0].model_path),
        cache_root=Path(config.cache_root),
    )
    assert [m.role for m in build_config(**options).models] == [
        "embedding",
        "reranking",
    ]
    result = build_config(**options, diarization_python=sys.executable)
    assert result.models[-1].role == "diarization"
    assert result.models[-1].python == sys.executable
    assert result.models[-1].dimension == 1
    with pytest.raises(ValueError, match="invalid_diarization_python"):
        build_config(**options, diarization_python="/not/an/interpreter")
