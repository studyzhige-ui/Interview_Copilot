"""HarnessEvent factories — SSE wire-format contracts for tool events."""

import json


def test_tool_start_and_tool_done_carry_tool_call_id():
    """Both ``tool_start`` and ``tool_done`` SSE events must surface
    the LLM-assigned ``tool_call_id`` so the frontend can pair live-
    stream tool_use/tool_result blocks by id rather than FIFO order.
    The empty-default keeps the wire backwards-compatible with any
    older client that ignores the field.
    """
    from app.agent_runtime.harness_events import HarnessEvent

    start = HarnessEvent.tool_start(
        "search_jobs",
        "keywords=AI Agent",
        step=1,
        elapsed_ms=10.0,
        tool_call_id="call_AbC123",
    )
    assert start.to_dict()["data"]["tool_call_id"] == "call_AbC123"
    assert start.to_dict()["data"]["tool"] == "search_jobs"

    done = HarnessEvent.tool_done(
        "search_jobs",
        "返回 5 条结果",
        step=1,
        elapsed_ms=120.0,
        tool_latency_ms=80.0,
        is_error=False,
        result_content='{"count":5}',
        tool_call_id="call_AbC123",
    )
    assert done.to_dict()["data"]["tool_call_id"] == "call_AbC123"
    # Pairs with the start event by id.
    assert (
        done.to_dict()["data"]["tool_call_id"]
        == start.to_dict()["data"]["tool_call_id"]
    )

    # Back-compat: omitting tool_call_id yields the empty string, not
    # a missing key. The FE's ``String(data.tool_call_id ?? '')``
    # coerce always lands on a defined value.
    start_compat = HarnessEvent.tool_start(
        "x",
        "y",
        step=0,
        elapsed_ms=0.0,
    )
    assert start_compat.to_dict()["data"]["tool_call_id"] == ""
    done_compat = HarnessEvent.tool_done(
        "x",
        "y",
        step=0,
        elapsed_ms=0.0,
        tool_latency_ms=0.0,
        is_error=False,
    )
    assert done_compat.to_dict()["data"]["tool_call_id"] == ""


def test_tool_done_event_carries_full_result_content():
    """``tool_done`` SSE event must include ``result_content`` so the
    live tool card renders the expanded view without a refresh.

    Pre-fix the wire format only carried ``result_summary`` and the
    frontend showed "(刷新会话以加载完整输出)" until reload.
    """
    from app.agent_runtime.harness_events import HarnessEvent

    ev = HarnessEvent.tool_done(
        "search_jobs",
        "返回 5 条结果",
        step=1,
        elapsed_ms=120.0,
        tool_latency_ms=80.0,
        is_error=False,
        result_content='{"source":"lever","count":5,"jobs":[...]}',
    )
    payload = ev.to_dict()
    assert payload["type"] == "tool_done"
    assert payload["data"]["result_summary"] == "返回 5 条结果"
    assert payload["data"]["result_content"].startswith("{")
    assert payload["data"]["tool_latency_ms"] == 80.0
    assert payload["data"]["is_error"] is False

    # Backwards-compat: omitting ``result_content`` produces an empty
    # string, not a missing key — so the frontend's String(...) coerce
    # always lands on a defined value.
    ev2 = HarnessEvent.tool_done(
        "search_jobs",
        "返回 0 条结果",
        step=1,
        elapsed_ms=120.0,
        tool_latency_ms=80.0,
        is_error=False,
    )
    assert ev2.to_dict()["data"]["result_content"] == ""


def test_tool_sse_redacts_nested_credentials_and_obvious_values():
    from app.agent_runtime.harness_events import HarnessEvent

    sentinel = "sk-proj-NESTED_SENTINEL_123456789"
    start = HarnessEvent.tool_start(
        "credential_probe",
        f"api_key={sentinel}",
        step=1,
        elapsed_ms=1.0,
        input={
            "safe": "keep-me",
            "headers": {"Authorization": f"Bearer {sentinel}"},
            "nested": [{"client_secret": sentinel}],
        },
    )
    done = HarnessEvent.tool_done(
        "credential_probe",
        f"provider returned Bearer {sentinel}",
        step=1,
        elapsed_ms=2.0,
        tool_latency_ms=1.0,
        is_error=True,
        result_content=json.dumps(
            {
                "error": f"Authorization: Bearer {sentinel}",
                "nested": [{"refresh_token": sentinel}],
                "safe": "still-here",
            }
        ),
    )

    start_payload = start.to_dict()["data"]
    done_payload = done.to_dict()["data"]
    wire_payload = json.dumps([start_payload, done_payload], ensure_ascii=False)
    assert sentinel not in wire_payload
    assert start_payload["args_summary"] == "api_key=[REDACTED]"
    assert start_payload["input"]["safe"] == "keep-me"
    assert start_payload["input"]["headers"]["Authorization"] == "[REDACTED]"
    assert start_payload["input"]["nested"][0]["client_secret"] == "[REDACTED]"
    decoded_result = json.loads(done_payload["result_content"])
    assert decoded_result["nested"][0]["refresh_token"] == "[REDACTED]"
    assert decoded_result["safe"] == "still-here"
