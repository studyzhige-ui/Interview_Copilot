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


def test_tts_returns_actual_mp3_format_and_releases_auth_db_before_model(
    http, monkeypatch
):
    client, db = http

    async def synthesize(**_):
        db.close.assert_called_once()
        return SynthesizedAudio(
            b"ID3test", "audio/mpeg", "edge", "zh-CN-XiaoxiaoNeural"
        )

    monkeypatch.setattr(tts_service, "synthesize", synthesize)
    response = client.post("/mock-interviews/tts", json={"text": "hello"})
    assert response.status_code == 200 and response.content == b"ID3test"
    assert response.headers["content-type"] == "audio/mpeg"
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


async def test_disabled_synthesis_never_dispatches_network_or_usage(monkeypatch):
    import edge_tts
    from app.usage import runtime

    monkeypatch.setattr(settings, "TTS_PROVIDER", "disabled")
    edge = Mock()
    admission = AsyncMock()
    monkeypatch.setattr(edge_tts, "Communicate", edge)
    monkeypatch.setattr(runtime, "invoke_async", admission)
    with pytest.raises(ValueError, match="tts_disabled"):
        await TTSService().synthesize("interview text")
    edge.assert_not_called()
    admission.assert_not_called()


async def test_explicit_edge_preserves_format_identity_accounting_and_closure(
    monkeypatch,
):
    import edge_tts
    from app.usage import runtime

    monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
    monkeypatch.setattr(settings, "AUXILIARY_MODEL_POLICY", "configured")
    monkeypatch.setattr(settings, "TTS_DEFAULT_VOICE", "zh-CN-XiaoxiaoNeural")
    closed = []

    async def stream():
        try:
            yield {"type": "audio", "data": b"ID3"}
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"audio"}
        finally:
            closed.append(True)

    edge = Mock(return_value=SimpleNamespace(stream=stream))
    monkeypatch.setattr(edge_tts, "Communicate", edge)
    descriptors = []

    async def invoke(work, **desc):
        descriptors.append(desc)
        monkeypatch.setattr(settings, "TTS_DEFAULT_VOICE", "zh-CN-YunxiNeural")
        return await work()

    monkeypatch.setattr(runtime, "invoke_async", invoke)
    result = await TTSService().synthesize("  hello  ")
    assert result.data == b"ID3audio" and result.media_type == "audio/mpeg"
    assert result.model == "zh-CN-XiaoxiaoNeural"
    assert descriptors[0]["units"] == {"requests": 1, "characters": 5}
    edge.assert_called_once_with("hello", "zh-CN-XiaoxiaoNeural")
    assert closed == [True]


async def test_invalid_voice_fails_before_admission(monkeypatch):
    from app.usage import runtime

    monkeypatch.setattr(settings, "TTS_PROVIDER", "edge")
    admission = AsyncMock()
    monkeypatch.setattr(runtime, "invoke_async", admission)
    with pytest.raises(ValueError, match="invalid_tts_voice"):
        await TTSService().synthesize("hello", "retired_voice")
    admission.assert_not_called()
