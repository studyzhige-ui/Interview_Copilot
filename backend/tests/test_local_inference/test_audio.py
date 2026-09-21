"""Contract and official-adapter tests; no model weights or GPU are claimed."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest

from app.local_inference.audio import (
    MAX_PCM_BYTES,
    decode_pcm,
    pcm_payload,
    validate_audio_result,
)
from app.local_inference.client import make_audio_request, checked_response
from app.local_inference.config import ModelSpec, binding_for
from app.local_inference.protocol import ProtocolError, request, validate_output
from app.local_inference import child, qwen_audio


@pytest.fixture
def audio_spec(tmp_path):
    return ModelSpec(
        "transcription",
        "Qwen/Qwen3-ASR-1.7B",
        str(tmp_path),
        sys.executable,
        dimension=1,
        max_tokens=4096,
    )


def audio_task(spec, pcm=b"\0\0" * 16000, **kwargs):
    return make_audio_request(spec.role, spec.binding, pcm, **kwargs)


@pytest.mark.parametrize("pcm", [b"", b"x", b"x" * (MAX_PCM_BYTES + 2), "text"])
def test_invalid_pcm(pcm):
    with pytest.raises(ProtocolError):
        pcm_payload(pcm)


def test_pcm_roundtrip_and_hash_binding():
    pcm = b"\0\0\xff\x7f\0\x80"
    envelope = pcm_payload(pcm)
    assert decode_pcm(envelope) == pcm
    with pytest.raises(ProtocolError):
        decode_pcm({**envelope, "sha256": "a" * 64})


@pytest.mark.parametrize(
    "key,value",
    [
        ("sample_rate", True),
        ("sample_rate", 44100),
        ("samples", -1),
        ("samples", True),
        ("data", "https://audio"),
        ("data", "€"),
        ("data", "AA=="),
        ("encoding", "wav"),
    ],
)
def test_bad_audio_envelope(key, value):
    with pytest.raises(ProtocolError):
        decode_pcm({**pcm_payload(b"\0\0"), key: value})


def test_request_rejects_paths_and_alignment_without_text(audio_spec):
    req = audio_task(audio_spec)
    assert request(req) == req
    for edit in (
        {"path": "/private/audio"},
        {"language": True},
        {"text": "extra prompt"},
        {"role": []},
    ):
        with pytest.raises(ProtocolError):
            request({**req, **edit})
    spec = replace(audio_spec, role="alignment")
    with pytest.raises(ProtocolError):
        audio_task(spec, text="你好", language=None)


def test_no_asr_timestamps_or_speaker_invention(audio_spec):
    req = audio_task(audio_spec)
    result = dict(text="hello", language="English", words=[])
    assert validate_output(req, result, dimension=1) is result
    with pytest.raises(ProtocolError):
        validate_audio_result(
            req, {**result, "words": [{"text": "hello", "start": 0, "end": 1}]}
        )
    with pytest.raises(ProtocolError):
        validate_audio_result(req, {**result, "speaker": "candidate"})


@pytest.mark.parametrize(
    "start,end", [(0, 2), (-1, 1), (1, 1), (0, float("nan")), (True, 1), (None, 1)]
)
def test_alignment_bounds(audio_spec, start, end):
    req = audio_task(replace(audio_spec, role="alignment"), text="你好", language="zh")
    with pytest.raises(ProtocolError):
        validate_audio_result(
            req,
            dict(
                text="你好",
                language="zh",
                words=[dict(text="你好", start=start, end=end)],
            ),
        )


def test_alignment_keeps_missing_words_and_rejects_omission(audio_spec):
    req = audio_task(
        replace(audio_spec, role="alignment"), text="你好，world!", language="zh"
    )
    valid = dict(
        text=req["text"],
        language="zh",
        words=[
            dict(text="你好", start=0, end=0.5),
            dict(text="world", start=None, end=None),
        ],
    )
    assert validate_audio_result(req, valid) is valid
    with pytest.raises(ProtocolError):
        validate_audio_result(req, {**valid, "words": valid["words"][:1]})


def test_audio_binding_is_separate_and_rag_identity_unchanged(audio_spec):
    assert audio_spec.binding != replace(audio_spec, role="alignment").binding
    assert audio_spec.binding == replace(audio_spec, device="cuda").binding
    import hashlib
    import json

    expected = hashlib.sha256(
        json.dumps(
            [
                "sentence-transformer-explicit-prompts-v1",
                "embedding",
                "test",
                None,
                3,
                32,
                "",
                "",
            ],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert binding_for("embedding", "test", None, 3, 32) == expected


@pytest.fixture
def fake_torch(monkeypatch):
    module = SimpleNamespace(
        inference_mode=nullcontext,
        set_num_threads=lambda n: None,
        float32="float32",
        bfloat16="bfloat16",
        cuda=SimpleNamespace(is_available=lambda: False),
    )
    monkeypatch.setitem(sys.modules, "torch", module)
    return module


def test_qwen_local_load_uses_separate_adapters(audio_spec, fake_torch, monkeypatch):
    calls = []

    class Loader:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            calls.append((args, kwargs))
            return cls

    monkeypatch.setitem(
        sys.modules,
        "qwen_asr",
        SimpleNamespace(Qwen3ASRModel=Loader, Qwen3ForcedAligner=Loader),
    )
    assert child.load_model(audio_spec) is Loader
    assert calls[0][0] == (audio_spec.model_path,)
    assert calls[0][1]["local_files_only"] is True
    assert calls[0][1]["trust_remote_code"] is False
    assert calls[0][1]["max_inference_batch_size"] == 1
    assert child.load_model(replace(audio_spec, role="alignment")) is Loader
    assert "max_new_tokens" not in calls[1][1]
    with pytest.raises(RuntimeError, match="cuda_unavailable"):
        child.load_model(replace(audio_spec, device="cuda"))


def test_official_qwen_asr_call_shape(audio_spec, fake_torch):
    def transcribe(*, audio, language, return_time_stamps):
        waveform, sr = audio
        assert (
            sr == 16000
            and waveform.shape == (16000,)
            and waveform.dtype.name == "float32"
        )
        assert language == "Chinese" and return_time_stamps is False
        return [SimpleNamespace(text="事务边界", language="Chinese")]

    req = audio_task(audio_spec, language="zh")
    result = child.infer(SimpleNamespace(transcribe=transcribe), audio_spec, req)
    assert result == dict(text="事务边界", language="Chinese", words=[])
    response = dict(
        id=req["id"], binding=req["binding"], status="completed", values=result
    )
    assert checked_response(req, response, 1) == result


def test_official_aligner_call_preserves_unaligned_token(audio_spec, fake_torch):
    spec = replace(audio_spec, role="alignment")
    req = audio_task(spec, language="en", text="one two")

    def align(**kw):
        assert kw["language"] == "English" and kw["text"] == "one two"
        return [
            [
                SimpleNamespace(text="one", start_time=0.0, end_time=0.5),
                SimpleNamespace(text="two", start_time=0.5, end_time=0.5),
            ]
        ]

    result = qwen_audio.infer(SimpleNamespace(align=align), spec, req)
    assert result["words"][1] == dict(text="two", start=None, end=None)


async def test_speech_proxy_uses_frozen_binding_without_ml_import(
    audio_spec, monkeypatch
):
    from app.local_inference.speech import SpeechClient
    from app.core.config import settings

    monkeypatch.setattr(settings, "MODEL_REVISIONS_JSON", {})
    calls = []

    class Proxy:
        timeout = 5

        async def acall(self, task, *, dimension):
            calls.append(task)
            assert dimension == 1
            return dict(text="hello", language="English", words=[])

    proxy = SpeechClient(
        model=audio_spec.model_id, alignment_model="Qwen/aligner", client=Proxy()
    )
    assert (await proxy.transcribe(b"\0\0", language="auto"))["text"] == "hello"
    assert calls[0]["binding"] == audio_spec.binding and calls[0]["language"] is None
    await proxy.align(b"\0\0", "hello", language="en")
    assert calls[1]["role"] == "alignment"


def test_setup_audio_is_explicit_and_uses_selected_interpreter(config, monkeypatch):
    from pathlib import Path
    from scripts.prepare_local_inference import build_config
    from app.core.model_assets import ModelInspection

    monkeypatch.setattr(
        "scripts.prepare_local_inference.inspect_model",
        lambda model_id, **_: ModelInspection(
            model_id, config.models[0].model_path, "structurally_valid", "transformers"
        ),
    )
    result = build_config(
        python=sys.executable,
        audio_python=sys.executable,
        device="cpu",
        runtime_dir=Path(config.socket_path).parent,
        model_root=Path(config.models[0].model_path),
        cache_root=Path(config.cache_root),
    )
    assert [s.role for s in result.models] == [
        "embedding",
        "reranking",
        "transcription",
        "alignment",
    ]
    assert result.models[2].max_tokens == 4096
