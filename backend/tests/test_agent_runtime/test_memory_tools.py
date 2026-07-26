"""recall_memory / save_memory tool handlers (privacy gate + v3 routing)."""


def test_recall_memory_returns_v3_bundle_keys(monkeypatch):
    """``recall_memory`` must surface the v3 return shape: user_profile +
    ability_states + learning_strategy_description + active_learning_strategy
    + ability_count. When ``load_strategy`` is set it pulls the full strategy
    body via ``attach_active_bodies``."""
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler
    from app.services.memory.v3_context_loader import V3MemoryContext

    # Privacy gate open.
    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )

    bundle = V3MemoryContext(
        user_profile_body="- 目标：后端岗位",
        ability_states=[
            {
                "topic": "Redis",
                "skill_type": "knowledge_topic",
                "mastery_level": "weak",
                "summary": "穿透没搞懂",
            },
        ],
        learning_strategy_description="先分析根因",
    )
    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.load_universal",
        lambda user_id: bundle,
    )

    async def fake_attach(ctx, *, user_id, load_strategy=False):
        if load_strategy:
            ctx.active_learning_strategy_body = "- 先分析根因\n- 再给方案"
        return ctx

    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.attach_active_bodies",
        fake_attach,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(_recall_memory_handler(RecallMemoryArgs(load_strategy=True), ctx))

    assert out["user_profile"] == "- 目标：后端岗位"
    assert out["ability_states"][0]["topic"] == "Redis"
    assert out["learning_strategy_description"] == "先分析根因"
    assert "再给方案" in out["active_learning_strategy"]
    assert out["ability_count"] == 1
    # No old keys leak.
    assert "knowledge_topics" not in out
    assert "strategy_body" not in out


def test_recall_memory_disabled_when_global_memory_off(monkeypatch):
    """Privacy gate: when the global toggle is OFF the handler returns the
    disabled bundle and reads NO cross-session memory."""
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: False,
    )

    def _boom(*a, **k):  # load_universal must NOT be called when disabled
        raise AssertionError("load_universal called despite memory toggle OFF")

    monkeypatch.setattr(
        "app.services.memory.v3_context_loader.load_universal",
        _boom,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(_recall_memory_handler(RecallMemoryArgs(), ctx))
    assert out["disabled"] is True
    assert out["ability_count"] == 0


def test_save_memory_routes_target_to_v3_services(monkeypatch):
    """``save_memory`` dispatches by ``target``:
    * ability_state → memory_ability_state_service.upsert (topic/skill/level)
    * user_profile / learning_strategy → memory_document_service.apply_patches
    """
    import asyncio
    from dataclasses import dataclass

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import SaveMemoryArgs, _save_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )
    # The handler holds ``user_memory_lock`` — neutralise Redis dependence.
    import contextlib

    @contextlib.asynccontextmanager
    async def _noop_lock(user_id, **k):
        yield

    monkeypatch.setattr(
        "app.services.memory._user_memory_lock.user_memory_lock",
        _noop_lock,
    )

    ability_calls: list[dict] = []

    def fake_upsert(user_id, **kwargs):
        ability_calls.append({"user_id": user_id, **kwargs})
        return object()

    monkeypatch.setattr(
        "app.services.memory.memory_ability_state_service.upsert",
        fake_upsert,
    )

    @dataclass
    class _PR:
        applied: int = 1
        dropped: int = 0
        skipped: int = 0

    doc_calls: list[dict] = []

    def fake_apply(user_id, doc_type, patches, **kwargs):
        doc_calls.append({"user_id": user_id, "doc_type": doc_type, "patches": patches})
        return _PR()

    monkeypatch.setattr(
        "app.services.memory.memory_document_service.apply_patches",
        fake_apply,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")

    # ── ability_state target ──
    out = asyncio.run(
        _save_memory_handler(
            SaveMemoryArgs(
                target="ability_state",
                topic="Redis 缓存穿透",
                skill_type="knowledge_topic",
                mastery_level="weak",
                summary="不懂布隆过滤器",
            ),
            ctx,
        )
    )
    assert out["target"] == "ability_state"
    assert ability_calls and ability_calls[0]["topic"] == "Redis 缓存穿透"
    assert ability_calls[0]["skill_type"] == "knowledge_topic"
    assert ability_calls[0]["mastery_level"] == "weak"

    # ── learning_strategy target → doc apply_patches ──
    out = asyncio.run(
        _save_memory_handler(
            SaveMemoryArgs(target="learning_strategy", fact="先分析根因再给方案"),
            ctx,
        )
    )
    assert out["target"] == "learning_strategy"
    assert out["applied"] == 1
    assert doc_calls and doc_calls[-1]["doc_type"] == "learning_strategy"
    # The fact line is normalised into a markdown bullet patch.
    assert doc_calls[-1]["patches"][0]["new_line"].startswith("- 先分析根因")


def test_save_memory_rejects_unknown_target(monkeypatch):
    import asyncio

    from app.agent_runtime.tool_registry import AgentToolContext
    from app.agent_runtime.tools.memory import SaveMemoryArgs, _save_memory_handler

    monkeypatch.setattr(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        lambda session_id, user_id: True,
    )
    import contextlib

    @contextlib.asynccontextmanager
    async def _noop_lock(user_id, **k):
        yield

    monkeypatch.setattr(
        "app.services.memory._user_memory_lock.user_memory_lock",
        _noop_lock,
    )

    ctx = AgentToolContext(user_id="alice", session_id="s1")
    out = asyncio.run(
        _save_memory_handler(
            SaveMemoryArgs(target="habit", fact="x"),
            ctx,
        )
    )
    assert "error" in out
    assert "ability_state" in out["valid"]
