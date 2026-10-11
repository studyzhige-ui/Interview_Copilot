"""Recovery-safe model projection must leave canonical results intact."""

import copy
import pytest
from app.conversation.context_reduction import (
    reduce_tool_results,
    tool_message,
    split_recent,
)
from app.core.config import settings


def test_large_tool_batch_can_be_read_back_after_projection(monkeypatch):
    monkeypatch.setattr(settings, "CONTEXT_TOOL_BATCH_TOKENS", 500)
    monkeypatch.setattr(settings, "CONTEXT_TOOL_PREVIEW_TOKENS", 20)
    source = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }
            ],
        },
        tool_message("call-1", "完整资料。" * 6000, "turn-1"),
    ]
    original = copy.deepcopy(source)
    projected, report = reduce_tool_results(source, input_limit=8000)
    assert source == original and report["saved_tokens"] > 0
    assert '"source_turn_id": "turn-1"' in projected[1]["content"]
    assert '"tool_call_id": "call-1"' in projected[1]["content"]
    assert reduce_tool_results(projected, input_limit=8000)[0] == projected


@pytest.mark.parametrize("tool", ["read_file", "read_interaction_history"])
def test_a_requested_page_is_not_immediately_projected_away(tool):
    messages = [
        {"role": "assistant", "tool_calls": [{"id": "c", "function": {"name": tool}}]},
        tool_message("c", "保留内容" * 4000, "t"),
    ]
    assert reduce_tool_results(messages, input_limit=1000)[0] == messages


def test_history_split_never_orphans_a_tool_result():
    messages = [
        {"role": "user", "content": "older" * 500},
        {
            "role": "assistant",
            "tool_calls": [{"id": "c", "function": {"name": "read_file"}}],
        },
        tool_message("c", "answer", "t"),
        {"role": "user", "content": "continue"},
    ]
    prefix, suffix = split_recent(messages, token_limit=30)
    assert prefix + suffix == messages
    assert not suffix or suffix[0]["role"] != "tool"
