"""Real SDK/HTTP adapters with isolated transport and a real local ledger.

No provider endpoints, API keys, or paid models are used. Only the wire transport
is substituted; scope, admission, usage parsing, and settlement are production.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import OpenAI, AsyncOpenAI
from sqlalchemy import select

from app.core.config import settings
from app.core.execution_errors import ModelOutcomeUnknownError
from app.models.model_budget import ModelBudgetReservation
from app.usage import runtime
from app.usage.embedding import AccountOpenAIEmbedding
from app.rag.parsing import cloud


def rows(factory):
    with factory() as db:
        return db.scalars(
            select(ModelBudgetReservation).order_by(ModelBudgetReservation.created_at)
        ).all()


def test_embedding_sdk_sync_batches_are_individually_admitted(usage_scope):
    calls = []

    def handle(request):
        payload = json.loads(request.content)
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "text-embedding-3-small",
                "data": [
                    {"object": "embedding", "index": i, "embedding": [float(i), 0.5]}
                    for i in range(len(payload["input"]))
                ],
                "usage": {"prompt_tokens": 7, "total_tokens": 7},
            },
        )

    native = OpenAI(
        api_key="fixture",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    try:
        model = AccountOpenAIEmbedding(
            model="text-embedding-3-small",
            api_key="fixture",
            embed_batch_size=2,
            max_retries=0,
        )
        model._client = native
        result = model.get_text_embedding_batch(["one", "two", "three"])
        assert len(result) == 3 and len(calls) == 2
        stored = rows(usage_scope)
        assert [r.meter for r in stored] == ["embedding", "embedding"]
        assert [r.status for r in stored] == ["settled", "settled"]
        assert sum(r.observed_tokens for r in stored) == 14
        assert sum(r.observed_units_json["documents"] for r in stored) == 3
    finally:
        native.close()


@pytest.mark.asyncio
async def test_embedding_sdk_async_scope_and_missing_usage(usage_scope):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 2.0]}],
                "object": "list",
                "model": "text-embedding-3-small",
            },
        )

    async with AsyncOpenAI(
        api_key="fixture",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as native:
        model = AccountOpenAIEmbedding(
            model="text-embedding-3-small", api_key="fixture", max_retries=0
        )
        model._aclient = native
        assert await model.aget_query_embedding("question") == [1.0, 2.0]
    row = rows(usage_scope)[0]
    assert len(calls) == 1 and row.status == "estimated" and row.observed_tokens > 0


@pytest.mark.asyncio
async def test_budget_stops_real_embedding_transport_before_send(
    usage_scope, monkeypatch
):
    monkeypatch.setattr(settings, "MODEL_DAILY_CALL_LIMIT", 1)
    runtime.begin(
        meter="speech",
        provider="fixture",
        model="fixture",
        content="first",
        units={"requests": 1},
    )
    calls = []

    def handle(request):
        calls.append(request)
        raise AssertionError("must not send when account has no remaining request")

    async with AsyncOpenAI(
        api_key="fixture",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    ) as native:
        model = AccountOpenAIEmbedding(
            model="text-embedding-3-small", api_key="fixture", max_retries=0
        )
        model._aclient = native
        from app.usage.service import ModelBudgetExceededError

        with pytest.raises(ModelBudgetExceededError):
            await model.aget_query_embedding("question")
    assert not calls and len(rows(usage_scope)) == 1


@pytest.mark.asyncio
async def test_missing_owner_is_not_an_unmetered_embedding_fallback(usage_database):
    calls = []
    endpoint = SimpleNamespace(
        create=AsyncMock(side_effect=lambda **kw: calls.append(kw))
    )
    from app.usage.embedding import _EmbeddingCalls

    with pytest.raises(RuntimeError, match="consumption_owner_missing"):
        await _EmbeddingCalls(endpoint, "fixture", "fixture", True).create(
            model="fixture", input=["x"]
        )
    assert not calls and not rows(usage_database)


def test_cloud_v2_paid_job_has_one_receipt_and_preserves_job_identity(
    usage_scope, monkeypatch, tmp_path
):
    path = tmp_path / "input.docx"
    path.write_bytes(b"synthetic input, not an actual private file")
    monkeypatch.setattr(settings, "LLAMA_CLOUD_API_KEY", "fixture")
    monkeypatch.setattr(settings, "CLOUD_PARSE_TIER", "cost_effective")
    native_client = httpx.Client
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            assert request.url.path == "/api/v2/parse/upload"
            assert b'name="configuration"' in request.content
            assert b'"page_ranges"' in request.content
            return httpx.Response(200, json={"id": "pjb-fixture", "status": "PENDING"})
        assert request.url.params["expand"] == "markdown,usage"
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": "pjb-fixture",
                    "status": "COMPLETED",
                    "usage": {"credits": None},
                },
                "markdown": {
                    "pages": [{"page_number": 1, "markdown": "# Test", "success": True}]
                },
            },
        )

    monkeypatch.setattr(
        cloud.httpx,
        "Client",
        lambda **kw: native_client(transport=httpx.MockTransport(handle), **kw),
    )
    result = cloud.parse(str(path))
    assert result.pages[0].text == "# Test" and len(seen) == 2
    row = rows(usage_scope)[0]
    assert row.meter == "document_parsing" and row.provider_request_id == "pjb-fixture"
    assert row.status == "settled" and row.observed_units_json["pages"] == 1
    # Provider credits=None is not an invoice of zero, even on a completed job.
    assert row.invoice_cost_micros is None and row.cost_observed_micros is None


@pytest.mark.parametrize(
    "kind", ["rejected", "lost_create", "failed_job", "partial_page", "duplicate_page"]
)
def test_cloud_failure_semantics_without_paid_retry(
    usage_scope, monkeypatch, tmp_path, kind
):
    path = tmp_path / "input.docx"
    path.write_bytes(b"fixture")
    monkeypatch.setattr(settings, "LLAMA_CLOUD_API_KEY", "fixture")
    native_client = httpx.Client
    posts = []

    def handle(request):
        if request.method == "POST":
            posts.append(request)
            if kind == "rejected":
                return httpx.Response(422, json={"detail": "invalid"})
            if kind == "lost_create":
                raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(200, json={"id": "pjb-fixture", "status": "PENDING"})
        pages = [
            {"page_number": 1, "markdown": "data", "success": kind != "partial_page"}
        ]
        if kind == "duplicate_page":
            pages *= 2
        return httpx.Response(
            200,
            json={
                "job": {
                    "id": "pjb-fixture",
                    "status": "FAILED" if kind == "failed_job" else "COMPLETED",
                },
                "markdown": {"pages": pages},
            },
        )

    monkeypatch.setattr(
        cloud.httpx,
        "Client",
        lambda **kw: native_client(transport=httpx.MockTransport(handle), **kw),
    )
    with pytest.raises((ValueError, ModelOutcomeUnknownError, httpx.HTTPStatusError)):
        cloud.parse(str(path))
    row = rows(usage_scope)[0]
    assert len(posts) == 1
    assert row.status == (
        "rejected"
        if kind == "rejected"
        else "unknown"
        if kind in {"lost_create", "failed_job"}
        else "estimated"
    )
    if row.status == "unknown":
        assert row.reserved_units_json["pages"] > 0


@pytest.mark.asyncio
async def test_asr_streamed_request_and_resource_receipt(
    usage_scope, monkeypatch, tmp_path
):
    from app.media.application import transcription_registry as reg
    from app.usage import media

    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"synthetic audio transport")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(
        reg,
        "resolve_transcription",
        lambda: reg.ResolvedTranscription(
            "openai", reg.PROVIDERS["openai"], "whisper-1"
        ),
    )
    monkeypatch.setattr(
        media,
        "audio_units",
        lambda _: {"requests": 1, "audio_ms": 1250, "bytes": clip.stat().st_size},
    )
    client = httpx.AsyncClient
    seen = []

    def handle(request):
        seen.append(request)
        assert b"synthetic audio transport" in request.content
        return httpx.Response(200, text="fixture transcription")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: client(transport=httpx.MockTransport(handle), **kw),
    )
    assert await reg.transcribe_plain(str(clip)) == "fixture transcription"
    row = rows(usage_scope)[0]
    assert len(seen) == 1 and row.meter == "transcription"
    assert row.status == "settled" and row.observed_units_json["audio_ms"] == 1250


@pytest.mark.asyncio
async def test_analysis_never_retries_an_unreceived_model_response():
    from app.interviews.application.analysis.service import (
        _request_batch_result,
        _request_synthesis_payload,
    )

    for helper, args in [
        (_request_batch_result, ("fixture", [0])),
        (_request_synthesis_payload, ("fixture",)),
    ]:
        llm = SimpleNamespace(
            acomplete=AsyncMock(side_effect=ModelOutcomeUnknownError("lost"))
        )
        with pytest.raises(ModelOutcomeUnknownError):
            await helper(llm, *args)
        assert llm.acomplete.await_count == 1


@pytest.mark.asyncio
async def test_native_anthropic_completion_uses_messages_wire_and_disjoint_usage(
    usage_scope,
):
    from anthropic import Anthropic, AsyncAnthropic
    from app.core.anthropic_completion import AnthropicCompletion

    seen = []
    profile = SimpleNamespace(
        provider="anthropic",
        model="claude-fixture",
        context_window=128000,
        max_output_tokens=1000,
    )

    def handle(request):
        assert request.url.path == "/v1/messages"
        body = json.loads(request.content)
        assert "response_format" not in body
        assert body["system"].endswith("Return one valid JSON object only.")
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "claude-fixture",
                "content": [{"type": "text", "text": '{"ok":true}'}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 7,
                    "output_tokens": 3,
                    "cache_read_input_tokens": 11,
                    "cache_creation_input_tokens": 13,
                },
            },
        )

    with Anthropic(
        api_key="fixture",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    ) as sync:
        async with AsyncAnthropic(
            api_key="fixture",
            max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        ) as asynchronous:
            native = AnthropicCompletion(
                profile=profile,
                sync_client=sync,
                async_client=asynchronous,
                temperature=0.2,
            )
            llm = runtime.MeteredLLM(
                native, profile, "model_completion", username="alice"
            )
            result = await llm.acomplete(
                "fixture", response_format={"type": "json_object"}, system="owned"
            )
            assert json.loads(result.text) == {"ok": True}
    row = rows(usage_scope)[0]
    assert len(seen) == 1 and row.status == "settled"
    assert row.observed_tokens == 34  # 7 + 3 + 11 + 13, without duplicate cache counts
    assert row.observed_units_json["input_tokens"] == 7
    assert row.observed_units_json["cache_write_tokens"] == 13


def test_anthropic_schema_and_system_are_in_preflight_allowance():
    from app.core.anthropic_completion import AnthropicCompletion

    profile = SimpleNamespace(
        provider="anthropic",
        model="fixture",
        context_window=128000,
        max_output_tokens=100,
    )
    native = AnthropicCompletion(
        profile=profile, sync_client=None, async_client=None, temperature=0.2
    )
    options = {
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                }
            },
        },
        "system": "a" * 9000,
    }
    payload = native._payload("x", options)
    assert payload["output_config"]["format"]["type"] == "json_schema"
    llm = runtime.MeteredLLM(native, profile, "model_completion")
    assert llm._descriptor("x", options)["units"]["input_tokens"] >= 9000
    with pytest.raises(AttributeError, match="unmetered_completion_method_forbidden"):
        getattr(llm, "astream_chat")


def test_canonical_owner_scope_never_switches_an_existing_account(usage_scope):
    actor = runtime.current()
    with runtime.for_owner(1, operation="canonical", username="alice"):
        assert runtime.current() is actor
    with pytest.raises(ValueError, match="owner_mismatch"):
        with runtime.for_owner(2, operation="canonical"):
            raise AssertionError("must not enter foreign scope")
    assert runtime.current() is actor


def test_readonly_account_api_scopes_receipts_and_serializes_money(usage_scope):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.usage import router
    from app.core.security import get_current_user
    from app.db.database import get_db
    from app.models.user import User
    from app.usage import service

    owned = runtime.begin(
        meter="speech",
        provider="fixture",
        model="fixture",
        content="secret prompt not a ledger field",
        units={"requests": 1},
    )
    runtime.finish(owned, "completed", {"requests": 1})
    with usage_scope() as db:
        foreign = service.reserve(
            db,
            user_id=2,
            turn_id="foreign",
            call_id="1",
            token_allowance=0,
            meter="speech",
            provider="fixture",
            model="fixture",
            units={"requests": 1},
        )
        db.commit()
    app = FastAPI()
    app.include_router(router)

    def session():
        with usage_scope() as db:
            yield db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_user] = lambda: User(id=1, username="alice")
    with TestClient(app) as client:
        summary = client.get("/usage")
        assert summary.status_code == 200
        assert isinstance(summary.json()["rated_cost_reserved_micros"], str)
        history = client.get("/usage/receipts").json()
        assert [item["id"] for item in history["items"]] == [owned.identity]
        assert "secret prompt" not in json.dumps(history)
        assert (
            client.get("/usage/receipts", params={"before": foreign}).status_code == 400
        )
        assert client.get(f"/usage/receipts/{foreign}/corrections").json() == {
            "items": []
        }
        assert client.get("/usage/receipts", params={"limit": 1000}).status_code == 422
        assert client.post("/usage", json={"refund": True}).status_code == 405
