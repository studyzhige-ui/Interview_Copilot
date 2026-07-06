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
            {"type": "tool_use", "id": "c1", "name": "web_search",
             "input": {"query": "x" * 500}},
            {"type": "tool_result", "tool_use_id": "c1",
             "content": "y" * 2000},
            {"type": "text", "text": "final answer"},
        ],
    }
    # The synthesized single text block must NOT be double-counted…
    assert _turn_tokens(text_only) == _turn_tokens({"content": "hello world"})
    # …but real agent block traffic must dominate the weight.
    assert _turn_tokens(agent_turn) > 10 * _turn_tokens(text_only)


# ── AGT-9: check_fn receives the calling user when it can ────────────────


def test_registry_passes_user_id_to_capable_check_fns():
    from pydantic import BaseModel

    from app.agent_runtime.tool_registry import ToolEntry, ToolRegistry

    class _Args(BaseModel):
        q: str = ""

    seen: dict = {}

    def ctx_probe(user_id=None):
        seen["user_id"] = user_id
        return user_id == "alice"

    def env_probe():
        seen["env_called"] = True
        return True

    reg = ToolRegistry()
    reg._entries = {}
    reg._defaults_loaded = True
    async def _h(args, ctx):
        return {}

    reg.register(ToolEntry(name="ctx_tool", description="d", args_model=_Args,
                           handler=_h, check_fn=ctx_probe))
    reg.register(ToolEntry(name="env_tool", description="d", args_model=_Args,
                           handler=_h, check_fn=env_probe))

    names = {e.name for e in reg._iter_available(user_id="alice")}
    assert names == {"ctx_tool", "env_tool"}
    assert seen["user_id"] == "alice" and seen["env_called"]

    names = {e.name for e in reg._iter_available(user_id="bob")}
    assert names == {"env_tool"}  # ctx probe rejected bob


def test_tavily_probe_accepts_user_key(monkeypatch):
    import app.agent_runtime.tools.web as web

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert web._tavily_available() is False
    monkeypatch.setattr(web, "_resolve_tavily_key", lambda uid: "tvly-x" if uid == "alice" else "")
    assert web._tavily_available(user_id="alice") is True
    assert web._tavily_available(user_id="bob") is False
