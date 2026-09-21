from unittest.mock import Mock

import pytest

from app.core.config import Settings, settings
from app.core.model_policy import LocalModelPolicyError, require_local_model


@pytest.fixture
def local_only(monkeypatch):
    monkeypatch.setattr(settings, "AUXILIARY_MODEL_POLICY", "local_only")
    return settings


@pytest.mark.parametrize(
    "role", ["embedding", "reranking", "transcription", "tts", "document_parsing"]
)
def test_online_credentials_do_not_override_local_policy(local_only, role, monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "fixture-present-but-not-permission")
    with pytest.raises(LocalModelPolicyError, match="local_model_required"):
        require_local_model(role, is_local=False)
    require_local_model(role, is_local=True)


@pytest.mark.parametrize(
    "module,setting,resolve",
    [
        ("app.rag.embedding_registry", "EMBEDDING_PROVIDER", "resolve_embedding"),
        ("app.rag.reranker_registry", "RERANKER_PROVIDER", "resolve_reranker"),
        (
            "app.media.application.transcription_registry",
            "TRANSCRIPTION_PROVIDER",
            "resolve_transcription",
        ),
    ],
)
def test_registries_reject_remote_and_do_not_advertise_it_ready(
    local_only, module, setting, resolve, monkeypatch
):
    import importlib

    registry = importlib.import_module(module)
    monkeypatch.setattr(settings, setting, "siliconflow")
    monkeypatch.setenv("SILICONFLOW_API_KEY", "test")
    with pytest.raises(LocalModelPolicyError):
        getattr(registry, resolve)()
    assert not next(
        row for row in registry.list_providers() if row["id"] == "siliconflow"
    )["ready"]


def test_cloud_parse_blocked_before_reading_source_or_fallback(local_only, monkeypatch):
    from app.rag.parsing import cloud, registry

    monkeypatch.setattr(settings, "PARSER_PROVIDER", "llamaparse")
    monkeypatch.setattr(
        registry, "_docling_available", Mock(side_effect=AssertionError("fallback"))
    )
    with pytest.raises(LocalModelPolicyError):
        cloud.parse("source-must-not-be-read.pdf")
    with pytest.raises(LocalModelPolicyError):
        registry._candidates(".pdf")
    parser = Mock()
    parser.parse.side_effect = LocalModelPolicyError("stop")
    fallback = Mock()
    with pytest.raises(LocalModelPolicyError):
        registry._run_candidates("a.pdf", [parser, fallback])
    fallback.parse.assert_not_called()


@pytest.mark.asyncio
async def test_edge_tts_blocked_before_client_construction(local_only, monkeypatch):
    from app.media.application import tts_service

    connect = Mock(side_effect=AssertionError("online TTS must not start"))
    monkeypatch.setattr(tts_service.edge_tts, "Communicate", connect)
    with pytest.raises(LocalModelPolicyError):
        await tts_service.TTSService().synthesize("这是一段本地语音测试。")
    connect.assert_not_called()
    assert await tts_service.TTSService().synthesize(" ") == b""


def test_legacy_configured_deployment_still_allowed(monkeypatch):
    monkeypatch.setattr(settings, "AUXILIARY_MODEL_POLICY", "configured")
    require_local_model("tts", is_local=False)
    assert Settings(_env_file=None).AUXILIARY_MODEL_POLICY == "configured"


def test_offline_environment_is_set_before_model_library_import(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = """
import json, os, sys
from app.core.config import settings
print(json.dumps({"offline": os.environ.get("HF_HUB_OFFLINE"),
"transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE"),
"torch_imported": "torch" in sys.modules,
"transformers_imported": "transformers" in sys.modules}))
"""
    env = {
        **os.environ,
        "LOCAL_MODELS_OFFLINE": "true",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "offline": "1",
        "transformers_offline": "1",
        "torch_imported": False,
        "transformers_imported": False,
    }
