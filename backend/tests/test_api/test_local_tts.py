"""Authenticated speech HTTP format and provider-selection contracts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.interviews.mock import router
from app.core.config import settings
from app.core.execution_errors import (
    ModelOutcomeUnknownError,
    ConsumptionSettlementUnconfirmedError,
)
from app.core.security import get_current_user
from app.db.database import get_db
from app.local_inference.client import LocalInferenceNotStarted, LocalInferenceUnknown
from app.media.application.tts_service import SynthesizedAudio, TTSService, tts_service


@pytest.fixture
def http():
    db = Mock()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, username="a"
    )
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client, db


def test_tts_returns_actual_wav_format_and_releases_auth_db_before_model(
    http, monkeypatch
):
    client, db = http

    async def synthesize(**_):
        db.close.assert_called_once()
        return SynthesizedAudio(
            b"RIFFtestWAVE", "audio/wav", "local_qwen3_tts", "local"
        )

    monkeypatch.setattr(tts_service, "synthesize", synthesize)
    response = client.post("/mock-interviews/tts", json={"text": "hello"})
    assert response.status_code == 200 and response.content == b"RIFFtestWAVE"
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "failure",
    [
        LocalInferenceNotStarted("missing"),
        LocalInferenceUnknown("private"),
        ModelOutcomeUnknownError("private"),
        ConsumptionSettlementUnconfirmedError("private"),
    ],
)
def test_tts_unavailable_is_explicit_without_exception_disclosure_or_retry(
    http, monkeypatch, failure
):
    client, _ = http
    call = AsyncMock(side_effect=failure)
    monkeypatch.setattr(tts_service, "synthesize", call)
    response = client.post("/mock-interviews/tts", json={"text": "hello"})
    assert response.status_code == 503 and "private" not in response.text
    assert call.await_count == 1


def test_http_capacity_and_unknown_fields_fail_before_model(http, monkeypatch):
    client, _ = http
    call = AsyncMock()
    monkeypatch.setattr(tts_service, "synthesize", call)
    for body in ({"text": "x" * 601}, {"text": "ok", "model": "cloud"}, {"text": ""}):
        assert client.post("/mock-interviews/tts", json=body).status_code == 422
    call.assert_not_called()


async def test_local_service_freezes_identity_and_never_constructs_edge(monkeypatch):
    from app.local_inference import synthesis
    from app.usage import runtime
    import edge_tts

    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_qwen3_tts")
    monkeypatch.setattr(settings, "TTS_DEFAULT_VOICE", "Vivian")
    monkeypatch.setattr(settings, "TTS_LANGUAGE", "Auto")
    edge = Mock(side_effect=AssertionError("cloud fallback"))
    monkeypatch.setattr(edge_tts, "Communicate", edge)
    local = AsyncMock(return_value=b"RIFFwave")
    monkeypatch.setattr(synthesis.SynthesisClient, "synthesize", local)
    descriptors = []

    async def invoke(work, **kwargs):
        descriptors.append(kwargs)
        monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
        return await work()

    monkeypatch.setattr(runtime, "invoke_async", invoke)
    result = await TTSService().synthesize("  你好  ")
    assert result.media_type == "audio/wav" and result.provider == "local_qwen3_tts"
    assert descriptors[0]["meter"] == "speech"
    assert descriptors[0]["units"] == {"requests": 1, "characters": 2}
    assert descriptors[0]["content"]["voice"] == "Vivian"
    local.assert_awaited_once_with("你好", "Vivian", "Auto")
    edge.assert_not_called()


async def test_local_failure_and_empty_input_do_not_fall_back_or_retry(monkeypatch):
    from app.local_inference import synthesis
    from app.usage import runtime
    import edge_tts

    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_qwen3_tts")
    monkeypatch.setattr(settings, "TTS_DEFAULT_VOICE", "Vivian")
    monkeypatch.setattr(settings, "TTS_LANGUAGE", "Auto")
    local = AsyncMock(side_effect=LocalInferenceUnknown("unconfirmed"))
    monkeypatch.setattr(synthesis.SynthesisClient, "synthesize", local)
    edge = Mock()
    monkeypatch.setattr(edge_tts, "Communicate", edge)

    async def invoke(work, **_):
        return await work()

    monkeypatch.setattr(runtime, "invoke_async", invoke)
    with pytest.raises(LocalInferenceUnknown):
        await TTSService().synthesize("hello")
    assert (await TTSService().synthesize(" ")).data == b""
    assert local.await_count == 1
    edge.assert_not_called()


async def test_real_usage_boundary_preserves_unknown_outcome_on_local_response_loss(
    monkeypatch,
):
    from app.local_inference import synthesis
    from app.usage import runtime

    monkeypatch.setattr(settings, "TTS_PROVIDER", "local_qwen3_tts")
    monkeypatch.setattr(settings, "TTS_DEFAULT_VOICE", "Vivian")
    monkeypatch.setattr(settings, "TTS_LANGUAGE", "Auto")
    receipt = object()
    begin = AsyncMock(return_value=receipt)
    finish = AsyncMock()
    monkeypatch.setattr(runtime, "begin_async", begin)
    monkeypatch.setattr(runtime, "finish_async", finish)
    local = AsyncMock(side_effect=LocalInferenceUnknown("response lost"))
    monkeypatch.setattr(synthesis.SynthesisClient, "synthesize", local)
    with pytest.raises(ModelOutcomeUnknownError):
        await TTSService().synthesize("hello")
    assert local.await_count == 1
    finish.assert_awaited_once_with(receipt, "unknown")


async def test_edge_is_explicit_and_rejects_local_voice_before_network(monkeypatch):
    import edge_tts
    from app.usage import runtime

    monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(settings, "AUXILIARY_MODEL_POLICY", "configured")
    edge = Mock()
    monkeypatch.setattr(edge_tts, "Communicate", edge)
    invoke = AsyncMock()
    monkeypatch.setattr(runtime, "invoke_async", invoke)
    with pytest.raises(ValueError, match="invalid_tts_voice"):
        await TTSService().synthesize("hello", "Vivian")
    invoke.assert_not_called()
    edge.assert_not_called()
