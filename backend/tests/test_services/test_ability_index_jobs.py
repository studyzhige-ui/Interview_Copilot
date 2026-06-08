"""MEM-JOBS-MILVUS: ability-index outbox handlers + durable drain + recall query.

The Milvus ability collection (``ability_index``) is exercised only through
mocks here — these tests verify the *wiring* (payload → handler → index call,
the enqueue→drain durable path, and the recall tool's semantic-search branch),
not Milvus itself.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _job(payload: dict, job_type: str = "upsert_memory_ability_index"):
    from app.models.outbox_job import OutboxJob

    return OutboxJob(id="job_x", user_id=1, job_type=job_type, payload_json=json.dumps(payload))


# ── handlers (no DB needed — they read the payload) ──────────────────────


def test_upsert_handler_calls_index_from_payload():
    from app.services.memory import ability_outbox

    payload = {
        "state_id": "mas_1", "user_id": "alice", "search_text": "Redis\n穿透",
        "topic": "Redis", "skill_type": "knowledge_topic", "mastery_level": "weak",
        "summary": "s",
    }
    with patch("app.services.memory.ability_index.upsert_ability") as up:
        ability_outbox._handle_upsert(None, _job(payload))
    up.assert_called_once()
    assert up.call_args.args[0] == "mas_1"
    assert up.call_args.kwargs["user_id"] == "alice"
    assert up.call_args.kwargs["topic"] == "Redis"


def test_upsert_handler_skips_bad_payload():
    from app.services.memory import ability_outbox

    # Missing user_id → must not index a node no tenant-filtered search can reach.
    with patch("app.services.memory.ability_index.upsert_ability") as up:
        ability_outbox._handle_upsert(None, _job({"state_id": "mas_1"}))
    up.assert_not_called()


def test_delete_handler_calls_index():
    from app.services.memory import ability_outbox

    with patch("app.services.memory.ability_index.delete_ability") as dl:
        ability_outbox._handle_delete(None, _job({"state_id": "mas_9"}, "delete_memory_ability_index"))
    dl.assert_called_once_with("mas_9")


def test_search_abilities_degrades_to_empty_on_error():
    """The read path must never break a turn — a Milvus/init failure degrades to
    an empty list, not an exception."""
    from app.services.memory import ability_index

    with patch.object(ability_index, "_init", side_effect=RuntimeError("milvus down")):
        assert ability_index.search_abilities("alice", "redis 穿透", top_k=3) == []


# ── end-to-end durable path ──────────────────────────────────────────────


@pytest.fixture
def seeded(monkeypatch):
    from app.db.database import Base
    import app.models.memory_ability_state  # noqa: F401
    import app.models.memory_audit_logs     # noqa: F401
    import app.models.outbox_job            # noqa: F401
    import app.models.user                  # noqa: F401

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    import app.services.memory._db_helpers as helpers_mod
    import app.services.memory._memory_audit as audit_mod
    import app.services.memory.memory_ability_state_service as ability_mod
    import app.services.uploads.outbox_service as outbox_mod
    for mod in (helpers_mod, audit_mod, ability_mod, outbox_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)

    from app.models.user import User
    s = Session()
    s.add(User(username="alice", hashed_password="x"))
    s.commit()
    s.close()
    yield Session
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_enqueue_then_drain_invokes_index(seeded):
    """service.upsert enqueues a job → the outbox drain runs the registered
    handler → ability_index.upsert_ability is invoked. Proves the durable path
    end-to-end (handlers registered at import, Milvus mocked)."""
    import app.services.memory.ability_outbox  # noqa: F401 — registers handlers
    from app.services.memory import memory_ability_state_service as svc
    from app.services.uploads.outbox_service import run_due_outbox_jobs

    svc.upsert("alice", topic="Redis", skill_type="knowledge_topic",
               mastery_level="weak", summary="缓存穿透", change_type="patch_realtime")

    with patch("app.services.memory.ability_index.upsert_ability") as up:
        processed = run_due_outbox_jobs(seeded())

    assert processed >= 1
    up.assert_called_once()
    assert up.call_args.args[0]  # the state_id was threaded through


# ── recall tool's semantic-search branch ─────────────────────────────────


@pytest.mark.asyncio
async def test_recall_memory_query_returns_relevant_abilities():
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler
    from app.services.memory.v3_context_loader import V3MemoryContext

    ctx = SimpleNamespace(user_id="alice", session_id="sess1")
    hits = [{"topic": "Redis", "skill_type": "knowledge_topic",
             "mastery_level": "weak", "summary": "穿透不熟", "score": 0.9}]

    with patch(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        return_value=True,
    ), patch(
        "app.services.memory.v3_context_loader.load_universal",
        return_value=V3MemoryContext(user_profile_body="- 卷卷"),
    ), patch(
        "app.services.memory.ability_index.search_abilities", return_value=hits,
    ):
        out = await _recall_memory_handler(RecallMemoryArgs(query="redis 穿透"), ctx)

    assert out["relevant_abilities"] == hits
    assert out["user_profile"] == "- 卷卷"


@pytest.mark.asyncio
async def test_recall_memory_no_query_skips_search():
    from app.agent_runtime.tools.memory import RecallMemoryArgs, _recall_memory_handler
    from app.services.memory.v3_context_loader import V3MemoryContext

    ctx = SimpleNamespace(user_id="alice", session_id="sess1")
    with patch(
        "app.services.memory.recall_policy.is_global_memory_enabled_for_session",
        return_value=True,
    ), patch(
        "app.services.memory.v3_context_loader.load_universal",
        return_value=V3MemoryContext(),
    ), patch(
        "app.services.memory.ability_index.search_abilities",
    ) as search:
        out = await _recall_memory_handler(RecallMemoryArgs(), ctx)

    search.assert_not_called()
    assert out["relevant_abilities"] == []
