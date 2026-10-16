"""Actual SDK SSE decoding against synthetic HTTP, without provider credentials."""

import json
import pytest
from app.core.model_catalog import ModelProfile
from app.core.model_provider_adapter import ModelProviderAdapter, ProviderRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_installed_sdk_stream_matches_the_native_adapter(provider):
    if provider == "openai":
        import httpx as wire
        from openai import AsyncOpenAI as SDK

        events = [
            {
                "id": "probe",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "probe",
                "choices": [
                    {"index": 0, "delta": {"content": "hello"}, "finish_reason": None}
                ],
            },
            {
                "id": "probe",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "probe",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                },
            },
        ]
        body = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        body += "data: [DONE]\n\n"
    else:
        import httpx2 as wire
        from anthropic import AsyncAnthropic as SDK

        events = [
            {
                "type": "message_start",
                "message": {
                    "id": "msg_probe",
                    "type": "message",
                    "role": "assistant",
                    "model": "probe",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 0},
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "hello"},
            },
            {"type": "content_block_stop", "index": 0},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 2},
            },
            {"type": "message_stop"},
        ]
        body = "".join(
            "event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n"
            for event in events
        )

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return wire.Response(
            200, headers={"content-type": "text/event-stream"}, text=body
        )

    async with SDK(
        api_key="synthetic-test-only",
        base_url="https://sdk.invalid/v1",
        http_client=wire.AsyncClient(transport=wire.MockTransport(respond)),
        max_retries=0,
    ) as client:
        profile = ModelProfile(
            id=provider + "/probe",
            provider=provider,
            display_name="probe",
            model="probe",
            api_base="https://sdk.invalid/v1",
            api_key_env="unused",
        )
        adapter = ModelProviderAdapter(client=client, profile=profile)
        stream = await adapter._open_stream(
            ProviderRequest(
                system="Synthetic system",
                messages=[{"role": "user", "content": "probe"}],
                max_tokens=16,
            )
        )
        decoded = [event async for event in stream]
    assert "".join(event.text_delta for event in decoded) == "hello"
    assert any(event.usage and event.usage.prompt_tokens == 5 for event in decoded)
    assert any(event.usage and event.usage.completion_tokens == 2 for event in decoded)
    assert decoded[-1].stop_reason == ("stop" if provider == "openai" else "end_turn")
    assert len(requests) == 1 and requests[0]["model"] == "probe"
    assert requests[0]["stream"] is True
