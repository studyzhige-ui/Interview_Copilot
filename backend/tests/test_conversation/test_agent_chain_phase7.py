"""Phase 7 agent-chain behaviors: profile-driven window (AGT-6), block-aware
turn weights (AGT-7), ctx-aware tool probes (AGT-9), mode persistence
(AGT-4)."""

from __future__ import annotations

from app.services.chat.context_assembly_pipeline import TokenBudget, _turn_tokens

# ── AGT-6: TokenBudget takes the model's real window ─────────────────────


def test_token_budget_accepts_model_window():
    assert TokenBudget().MODEL_CONTEXT_WINDOW == 128_000  # safe default
    assert TokenBudget(1_000_000).MODEL_CONTEXT_WINDOW == 1_000_000
    # Instances don't leak onto the class (tests/monkeypatching rely on it).
    assert TokenBudget.MODEL_CONTEXT_WINDOW == 128_000


# ── AGT-7: agent block traffic counts toward the threshold ───────────────


def test_turn_tokens_counts_agent_blocks():
    text_only = {
        "content": "hello world",
        "blocks": [{"type": "text", "text": "hello world"}],  # synthesized
    }
    agent_turn = {
        "content": "final answer",
        "blocks": [
            {
                "type": "tool_use",
                "id": "c1",
                "name": "web_search",
                "input": {"query": "x" * 500},
            },
            {"type": "tool_result", "tool_use_id": "c1", "content": "y" * 2000},
            {"type": "text", "text": "final answer"},
        ],
    }
    # The synthesized single text block must NOT be double-counted…
    assert _turn_tokens(text_only) == _turn_tokens({"content": "hello world"})
    # …but real agent block traffic must dominate the weight.
    assert _turn_tokens(agent_turn) > 10 * _turn_tokens(text_only)


# ── Real tools stay discoverable while connection facts are missing ──────


def test_registry_visibility_does_not_depend_on_connection_probe():
    from app.agent_runtime.tool_registry import ToolDefinition, ToolRegistry
    from pydantic import BaseModel

    class _Args(BaseModel):
        q: str = ""

    reg = ToolRegistry()
    reg._entries = {}
    reg._defaults_loaded = True

    async def _h(args, ctx):
        return {}

    reg.register(ToolDefinition("real_tool", "d", _Args, _h))

    names = {e.name for e in reg._iter_available(user_id="alice")}
    assert names == {"real_tool"}


def test_tavily_tool_reports_deployment_connector_unavailable_at_call_time(monkeypatch):
    import asyncio

    import app.agent_runtime.tools.web as web
    from app.agent_runtime.tool_registry import AgentToolContext

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(web, "_resolve_tavily_key", lambda _uid: "")
    result = asyncio.run(
        web._web_search_handler(
            web.WebSearchArgs(query="python"),
            AgentToolContext(user_id="alice", session_id="s1"),
        )
    )
    assert result == {
        "error": "connector_unavailable",
        "provider": "tavily",
        "reason": "deployment_credential_missing",
    }
