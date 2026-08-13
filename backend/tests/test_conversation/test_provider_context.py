from __future__ import annotations

from app.conversation.provider_context import (
    compose_provider_context,
    reconstruct_history_messages,
)
from app.services.chat.context_assembly_pipeline import AssembledContext, PromptRenderer


def test_provider_context_keeps_instructions_history_and_turn_data_partitioned():
    assembled = AssembledContext(
        debrief_reference="record-data",
        summary="lossy-summary",
        personalization_guidance="global then local guidance",
        memory_block="low-authority-memory",
        attachment_manifest="attachment-id",
        retrieved_context="retrieved-body",
        product_object_context="typed-owner-reread",
        recent_turns=[
            {"role": "User", "content": "earlier question"},
            {
                "role": "Agent",
                "content": "earlier answer",
                "blocks": [{"type": "text", "text": "earlier answer"}],
            },
        ],
        current_input="current admitted direction",
    )

    projection = compose_provider_context(
        assembled,
        renderer=PromptRenderer(),
        system_prompt="stable runtime rules",
    )

    assert projection.system == "stable runtime rules"
    assert all(
        value not in projection.system
        for value in (
            "record-data",
            "lossy-summary",
            "global then local guidance",
            "low-authority-memory",
            "retrieved-body",
            "current admitted direction",
        )
    )
    assert [message["role"] for message in projection.messages] == [
        "user",
        "user",
        "assistant",
        "user",
    ]
    assert "[Context Summary]" in projection.messages[0]["content"]
    assert projection.messages[1]["content"] == "earlier question"
    current = projection.messages[-1]["content"]
    assert "[Explicit Guidance]\nglobal then local guidance" in current
    assert "[Memory]\nlow-authority-memory" in current
    assert "[Retrieved Context]\nretrieved-body" in current
    assert current.endswith("[Current Query]\ncurrent admitted direction")


def test_provider_context_reconstructs_complete_tool_pair_by_call_identity():
    messages = reconstruct_history_messages(
        [
            {
                "role": "Agent",
                "content": "used tool",
                "blocks": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "read_owner",
                        "input": {"id": "owner-1"},
                    },
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": '{"ok":true}',
                    },
                    {"type": "text", "text": "done"},
                ],
            }
        ]
    )

    assert [message["role"] for message in messages] == [
        "assistant",
        "tool",
        "assistant",
    ]
    assert messages[0]["tool_calls"][0]["id"] == "call-1"
    assert messages[1]["tool_call_id"] == "call-1"
    assert messages[2]["content"] == "done"
