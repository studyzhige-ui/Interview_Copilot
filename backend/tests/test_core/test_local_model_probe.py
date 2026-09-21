from __future__ import annotations

import contextlib
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from app.core import model_probe_child
from app.core.isolated_process import run_isolated, ProcessResult
from scripts import probe_local_model as probe


def request(tmp_path, role="embedding"):
    return {
        "protocol_version": 1,
        "request_id": "a" * 32,
        "role": role,
        "model_path": str(tmp_path),
        "device": "cpu",
    }


def response(req, **changes):
    value = {
        **req,
        "status": "passed",
        "quality_validated": False,
        "audio_evidence_validated": False,
        "details": {"backend": "sentence_transformers", "dimension": 1024},
        "packages": {},
    }
    value.pop("model_path")
    value.update(changes)
    return json.dumps(value).encode()


def test_environment_is_allowlisted_and_offline(tmp_path, monkeypatch):
    for key in (
        "DEEPSEEK_API_KEY",
        "HF_TOKEN",
        "DATABASE_URL",
        "PYTHONPATH",
        "HTTP_PROXY",
        "AWS_SECRET_ACCESS_KEY",
    ):
        monkeypatch.setenv(key, "secret-sentinel")
    env = probe.probe_environment(tmp_path)
    assert "secret-sentinel" not in str(env)
    assert env["HOME"] == str(tmp_path)
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["HF_HUB_DISABLE_IMPLICIT_TOKEN"] == "1"


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "b" * 32},
        {"protocol_version": True},
        {"role": "alignment"},
        {"device": "cuda"},
        {"quality_validated": True},
        {"status": "skipped"},
        {"details": {"backend": "sentence_transformers", "dimension": True}},
        {"details": {"backend": "sentence_transformers", "dimension": 0}},
        {"packages": {"torch": "raw error with secret"}},
    ],
)
def test_response_must_match_request_and_not_overclaim(tmp_path, changes):
    req = request(tmp_path)
    with pytest.raises(ValueError):
        probe.decode_result(response(req, **changes), req, 0)


def test_zero_exit_required_and_logs_not_forwarded(tmp_path):
    req = request(tmp_path)
    with pytest.raises(ValueError):
        probe.decode_result(response(req), req, 7)
    result = probe.decode_result(response(req, arbitrary_log="secret-sentinel"), req, 0)
    assert "secret-sentinel" not in str(result)


def test_duplicate_response_identity_rejected(tmp_path):
    req = request(tmp_path)
    value = (
        response(req)
        .decode()
        .replace(
            '"protocol_version": 1', '"protocol_version": 1, "protocol_version": 1'
        )
    )
    with pytest.raises(ValueError, match="duplicate"):
        probe.decode_result(value.encode(), req, 0)


def test_child_request_disallows_arbitrary_loader(tmp_path):
    with pytest.raises(ValueError):
        model_probe_child._request(
            json.dumps(request(tmp_path, "custom.module.run")).encode()
        )
    assert (
        model_probe_child._request(json.dumps(request(tmp_path)).encode())["role"]
        == "embedding"
    )


def test_embedding_adapter_uses_only_local_weights(tmp_path, monkeypatch):
    torch = SimpleNamespace(inference_mode=contextlib.nullcontext)
    ctor = Mock()
    ctor.return_value.encode.return_value = np.ones((1, 1024))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=ctor)
    )
    result = model_probe_child._probe(request(tmp_path))
    assert result["dimension"] == 1024
    assert ctor.call_args.kwargs == {
        "device": "cpu",
        "local_files_only": True,
        "trust_remote_code": False,
    }


def test_transcription_generator_is_actually_consumed(tmp_path, monkeypatch):
    calls = []

    def lazy():
        calls.append("inference")
        yield object()

    ctor = Mock()
    ctor.return_value.transcribe.return_value = (lazy(), None)
    monkeypatch.setitem(
        sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=ctor)
    )
    result = model_probe_child._probe(request(tmp_path, "transcription"))
    assert result["segments"] == 1 and calls == ["inference"]
    assert ctor.call_args.kwargs["local_files_only"] is True


def test_cuda_failure_does_not_switch_to_cpu(tmp_path, monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)),
    )
    with pytest.raises(RuntimeError, match="cuda_unavailable"):
        model_probe_child._probe({**request(tmp_path), "device": "cuda"})


async def test_incomplete_assets_do_not_start_child_or_create_cache(
    tmp_path, monkeypatch
):
    runner = Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr(probe, "run_isolated", runner)
    args = SimpleNamespace(
        cache_dir=str(tmp_path / "cache"),
        model_root=str(tmp_path / "models"),
        model="BAAI/bge-m3",
        role="embedding",
        verify_hashes=False,
    )
    result = await probe.probe(args)
    assert result["status"] == "blocked"
    assert not (tmp_path / "cache").exists()
    runner.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="Linux/WSL child contract")
async def test_real_child_rejects_invalid_input_without_secret_output(tmp_path):
    req = request(tmp_path, "unknown")
    result = await run_isolated(
        [sys.executable, "-I", "-B", str(probe.CHILD)],
        env=probe.probe_environment(tmp_path),
        cwd=tmp_path,
        input_data=json.dumps(req).encode(),
        timeout_seconds=5,
    )
    value = json.loads(result.stdout)
    assert result.returncode == 2 and value["status"] == "failed"
    assert (
        value["quality_validated"] is False
        and "Traceback" not in result.stdout.decode()
    )


@pytest.mark.skipif(os.name != "posix", reason="Linux/WSL child contract")
async def test_python_network_guard_in_real_child(tmp_path):
    code = (
        "import importlib.util,sys,socket; "
        f"s=importlib.util.spec_from_file_location('probe_child',{str(probe.CHILD)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); sys.addaudithook(m._no_network); "
        "\ntry: socket.getaddrinfo('should-not-resolve.invalid',443)\n"
        "except RuntimeError: print('blocked')\nelse: raise AssertionError('not blocked')"
    )
    result = await run_isolated(
        [sys.executable, "-I", "-c", code],
        env=probe.probe_environment(tmp_path),
        cwd=tmp_path,
    )
    assert result.returncode == 0 and result.stdout.strip() == b"blocked"


async def test_parent_discards_stderr_cleans_temp_and_keeps_weights(
    tmp_path, monkeypatch
):
    model = tmp_path / "weights"
    model.mkdir()
    (model / "untouched").write_text("weights")
    inspection = SimpleNamespace(
        loadable_candidate=True,
        layout="transformers",
        path=str(model),
        as_dict=lambda: {"status": "structurally_valid"},
    )
    monkeypatch.setattr(probe, "inspect_model", lambda *a, **kw: inspection)

    async def fake_runner(argv, **kw):
        assert "-I" in argv
        req = json.loads(kw["input_data"])
        assert not kw["env"].get("DEEPSEEK_API_KEY")
        return ProcessResult(0, response(req), b"secret-sentinel", 0.01)

    monkeypatch.setattr(probe, "run_isolated", fake_runner)
    args = SimpleNamespace(
        cache_dir=str(tmp_path / "cache"),
        model_root=str(tmp_path),
        model="BAAI/bge-m3",
        role="embedding",
        verify_hashes=False,
        python=sys.executable,
        device="cpu",
        timeout=5,
    )
    result = await probe.probe(args)
    assert result["status"] == "passed" and result["process_reaped"] is True
    assert "secret-sentinel" not in str(result)
    assert not list((tmp_path / "cache/probe-runs").iterdir())
    assert (model / "untouched").read_text() == "weights"
