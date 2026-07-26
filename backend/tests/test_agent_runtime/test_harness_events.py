"""HarnessEvent factories — SSE wire-format contracts for tool events."""


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
