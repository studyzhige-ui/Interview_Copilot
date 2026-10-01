"""Finite synthesis protocol, offline adapter and cancellation: no real weights."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
import io
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import numpy as np
import pytest

from app.local_inference.config import ModelSpec
from app.local_inference.client import checked_response, LocalInferenceUnknown
from app.local_inference.protocol import (
    ProtocolError,
    frame,
    MAX_FRAME,
    request,
    validate_output,
)
from app.local_inference.synthesis import SynthesisClient, make_synthesis_request
from app.local_inference.synthesis_audio import (
    MAX_PCM_BYTES,
    SYNTHESIS_TOKENS,
    SAMPLE_RATE,
    decode_synthesis_result,
    encode_synthesis_result,
)
from app.local_inference import qwen_synthesis


@pytest.fixture
def spec(tmp_path):
    return ModelSpec(
        "synthesis",
        "test-custom-voice",
        str(tmp_path),
        sys.executable,
        dimension=1,
        max_tokens=SYNTHESIS_TOKENS,
        reservation_mib=10,
    )


def task(spec):
    return make_synthesis_request(spec.binding, "你好，面试开始。", "Vivian", "Auto")


def test_synthesis_has_separate_frozen_binding_and_fits_wire(spec):
    req = task(spec)
    assert request(req) == req
    assert spec.binding == replace(spec, device="cuda").binding
    assert spec.binding != replace(spec, revision="a" * 40).binding
    for change in ({"dimension": 2}, {"max_tokens": 2048}, {"query_prefix": "prompt"}):
        with pytest.raises(ValueError):
            replace(spec, **change)
    result = encode_synthesis_result(req, b"\0\0" * (MAX_PCM_BYTES // 2))
    assert len(frame({"values": result})) <= MAX_FRAME + 4
    assert len(decode_synthesis_result(req, result)) == MAX_PCM_BYTES
    assert validate_output(req, result, dimension=1) is result


@pytest.mark.parametrize(
    "change",
    [
        {"text": ""},
        {"text": "x" * 601},
        {"text": True},
        {"voice": "https://voice"},
        {"language": "zh"},
        {"path": "/secret"},
        {"audio": "remote"},
        {"operation": "transcribe"},
    ],
)
def test_untrusted_synthesis_requests_are_rejected(spec, change):
    with pytest.raises(ProtocolError):
        request({**task(spec), **change})


@pytest.mark.parametrize(
    "change",
    [
        {"samples": True},
        {"samples": 0},
        {"sample_rate": 16000},
        {"sha256": "0" * 64},
        {"text_sha256": "0" * 64},
        {"voice": "Ryan"},
        {"language": "English"},
        {"data": "@!"},
        {"data": "AA=="},
        {"extra": "no"},
    ],
)
def test_malformed_or_cross_request_audio_is_rejected(spec, change):
    req = task(spec)
    value = encode_synthesis_result(req, b"\0\0" * 5)
    with pytest.raises(ProtocolError):
        decode_synthesis_result(req, {**value, **change})


def test_audio_capacity_no_truncation(spec):
    for data in (b"", b"x", b"x" * (MAX_PCM_BYTES + 2)):
        with pytest.raises(ProtocolError):
            encode_synthesis_result(task(spec), data)
    with pytest.raises(LocalInferenceUnknown):
        checked_response(task(spec), {"status": "completed"}, 1)


async def test_synthesis_client_produces_real_wav_without_ml_imports(spec):
    calls = []

    async def call(req, *, dimension):
        calls.append((deepcopy(req), dimension))
        return encode_synthesis_result(req, b"\x01\0" * 12)

    client = SynthesisClient(
        model=spec.model_id, client=SimpleNamespace(timeout=20, acall=call)
    )
    audio = await client.synthesize("hello", "Ryan", "English")
    with wave.open(io.BytesIO(audio)) as wav:
        assert (
            wav.getnframes(),
            wav.getframerate(),
            wav.getnchannels(),
            wav.getsampwidth(),
        ) == (12, SAMPLE_RATE, 1, 2)
    assert calls[0][0]["priority"] == "interactive"
    assert calls[0][1] == 1


@pytest.fixture
def fake_torch(monkeypatch):
    torch = SimpleNamespace(
        inference_mode=nullcontext,
        set_num_threads=Mock(),
        float32="float32",
        bfloat16="bfloat16",
        cuda=SimpleNamespace(is_available=lambda: False, synchronize=Mock()),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    return torch


def fake_model(*, codes=3, values=None, rate=SAMPLE_RATE):
    decoder = Mock(
        return_value=(
            [np.array([0, 0.5, -0.5], dtype=np.float32) if values is None else values],
            rate,
        )
    )
    return SimpleNamespace(
        get_supported_speakers=lambda: ["vivian"],
        get_supported_languages=lambda: ["Chinese", "English"],
        _tokenize_texts=Mock(return_value=["tokens"]),
        _build_assistant_text=lambda text: text,
        _merge_generate_kwargs=lambda **kwargs: kwargs,
        model=SimpleNamespace(
            generate=Mock(return_value=([np.zeros((codes, 16), dtype=np.int64)], [])),
            speech_tokenizer=SimpleNamespace(decode=decoder),
        ),
    )


def test_codec_adapter_checks_budget_before_decode_and_preserves_voice(
    spec, fake_torch
):
    model = fake_model()
    req = task(spec)
    value = qwen_synthesis.infer(model, spec, req)
    assert len(decode_synthesis_result(req, value)) == 6
    args = model.model.generate.call_args.kwargs
    assert args["speakers"] == ["Vivian"] and args["languages"] == ["Auto"]
    assert (
        args["max_new_tokens"] == SYNTHESIS_TOKENS
        and args["non_streaming_mode"] is True
    )
    exhausted = fake_model(codes=SYNTHESIS_TOKENS - 2)
    with pytest.raises(ValueError, match="incomplete"):
        qwen_synthesis.infer(exhausted, spec, req)
    exhausted.model.speech_tokenizer.decode.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        np.array([]),
        np.array([float("nan")]),
        np.array([float("inf")]),
        np.array([1.01]),
        np.zeros((2, 2)),
        np.array([1], dtype=np.int16),
        np.zeros(MAX_PCM_BYTES // 2 + 1),
    ],
)
def test_bad_waveforms_never_become_successful_audio(spec, fake_torch, values):
    with pytest.raises(ValueError, match="waveform"):
        qwen_synthesis.infer(fake_model(values=values), spec, task(spec))


def test_loader_requires_exact_adapter_and_local_customvoice(
    spec, fake_torch, monkeypatch
):
    load = Mock(
        return_value=SimpleNamespace(
            model=SimpleNamespace(tts_model_type="custom_voice")
        )
    )
    monkeypatch.setattr(qwen_synthesis, "version", lambda _: "0.1.1")
    monkeypatch.setitem(
        sys.modules,
        "qwen_tts",
        SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=load)),
    )
    assert qwen_synthesis.load(spec).model.tts_model_type == "custom_voice"
    assert load.call_args.args == (spec.model_path,)
    assert load.call_args.kwargs["local_files_only"] is True
    assert load.call_args.kwargs["trust_remote_code"] is False
    with pytest.raises(RuntimeError, match="cuda"):
        qwen_synthesis.load(replace(spec, device="cuda"))
    monkeypatch.setattr(qwen_synthesis, "version", lambda _: "next")
    with pytest.raises(RuntimeError, match="version"):
        qwen_synthesis.load(spec)


async def test_broker_cancellation_reaps_synthesis_before_following_request(
    spec, tmp_path
):
    from app.local_inference.broker import Broker
    from app.local_inference.config import BrokerConfig

    entered = asyncio.Event()
    instances = []

    class Process:
        def __init__(self, *_):
            self.closed = False
            instances.append(self)

        async def start(self):
            pass

        async def run(self, req):
            entered.set()
            await asyncio.Event().wait()

        async def close(self):
            self.closed = True

    config = BrokerConfig(
        str(tmp_path / "socket"), str(tmp_path.parent / "synthesis-cache"), (spec,)
    )
    broker = Broker(config, factory=Process)
    broker.start()
    try:
        job = broker.submit(task(spec))
        await asyncio.wait_for(entered.wait(), 2)
        broker.cancel(job)
        assert (await asyncio.wait_for(job.future, 2))["status"] == "unknown"
        assert instances[0].closed
        assert not broker.resident
    finally:
        await broker.close()


def test_preparation_requires_verified_codec_assets_not_just_a_directory(
    tmp_path, monkeypatch
):
    from scripts.prepare_local_inference import build_config

    codec = tmp_path / "tts" / "speech_tokenizer"
    codec.mkdir(parents=True)
    (codec / "config.json").write_text("{}")
    (codec / "model.safetensors").write_bytes(b"synthetic weights")
    verified = ["speech_tokenizer/config.json", "speech_tokenizer/model.safetensors"]
    calls = []

    def inspect(model, **kwargs):
        calls.append((model, kwargs))
        return SimpleNamespace(
            loadable_candidate=True,
            layout="transformers",
            path=str(tmp_path / "tts"),
            checked_files=tuple(verified),
        )

    monkeypatch.setattr("scripts.prepare_local_inference.inspect_model", inspect)
    options = dict(
        python=sys.executable,
        device="cpu",
        runtime_dir=tmp_path / "run",
        model_root=tmp_path,
        cache_root=tmp_path / "cache",
    )
    assert "synthesis" not in {m.role for m in build_config(**options).models}
    configured = build_config(**options, tts_python=sys.executable)
    tts = configured.models[-1]
    assert (tts.role, tts.max_tokens, tts.dimension) == (
        "synthesis",
        SYNTHESIS_TOKENS,
        1,
    )
    assert calls[-1][1]["verify_hashes"] is True
    verified.clear()
    with pytest.raises(ValueError, match="verified_speech_tokenizer"):
        build_config(**options, tts_python=sys.executable)
    with pytest.raises(ValueError, match="invalid_tts_python"):
        build_config(**options, tts_python="/missing/python")


def test_checkpoint_specific_voice_and_language_are_not_substituted(spec, fake_torch):
    model = fake_model()
    for update in ({"voice": "Ryan"}, {"language": "Italian"}):
        with pytest.raises(ValueError, match="checkpoint_voice_or_language"):
            qwen_synthesis.infer(model, spec, {**task(spec), **update})
    model.model.generate.assert_not_called()
