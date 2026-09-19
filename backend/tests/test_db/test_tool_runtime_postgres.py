"""Verify non-empty upgrade and exact call admission against PostgreSQL."""

import asyncio

from sqlalchemy import MetaData, Table, create_engine
from uuid import uuid4

from app.db.types import utc_now
from sqlalchemy.orm import sessionmaker
from alembic import command
from app.agent_runtime import tool_call_executor as runtime
from app.agent_runtime.tool_policy import ToolEffect
from app.models.agent_execution import AgentToolCall
from app.models.chat import Conversation
from app.models.user import User
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401


def test_tool_identity_upgrade_preserves_audit_and_fences_concurrent_execution(
    fresh_pg_db,  # noqa: F811 - imported pytest fixture
    monkeypatch,
):
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "0045")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with factory() as db:
            user = User(username="tool-runtime-pg", hashed_password="x")
            db.add(user)
            db.flush()
            conversation = Conversation(user_id=user.id)
            db.add(conversation)
            db.flush()
            # Seed the actual historical schema. Current ORM defaults/columns
            # (e.g. dispatch_requested_at introduced after 0045) cannot be used
            # to manufacture pre-upgrade data. Reflection keeps this fixture
            # independent of future model additions without weakening the gate.
            metadata = MetaData()
            turns = Table("conversation_turns", metadata, autoload_with=db.connection())
            calls = Table("agent_tool_calls", metadata, autoload_with=db.connection())
            turn_id = str(uuid4())
            db.execute(
                turns.insert().values(
                    id=turn_id,
                    conversation_id=conversation.id,
                    user_id=user.id,
                    mode="agent",
                    execution_mode="standard",
                    message="run",
                    question_indexes_json=[],
                    attachments_json=[],
                    object_references_json=[],
                    status="pending",
                    dispatch_generation=1,
                    tool_snapshot_json={},
                    loaded_tool_schemas_json=[],
                    budget_json={},
                    created_at=utc_now(),
                )
            )
            db.execute(
                calls.insert().values(
                    call_id="legacy",
                    turn_id=turn_id,
                    session_id=conversation.id,
                    user_id=user.id,
                    tool_name="read",
                    arguments_json={"value": "原有记录"},
                    timeout_seconds=1,
                    status="completed",
                    result_json={"ok": True},
                    effect="read",
                    dispatch_generation=1,
                    policy_decision="allow",
                    policy_reason="test_read",
                    timeline_json=[],
                    receipt_refs_json=[],
                    resource_identities_json=[],
                    started_at=utc_now(),
                )
            )
            db.commit()
        command.upgrade(cfg, "head")
        with factory() as db:
            legacy = db.query(AgentToolCall).filter_by(call_id="legacy").one()
            assert legacy.arguments_json == {"value": "原有记录"}
            assert legacy.arguments_digest is None
        monkeypatch.setattr(runtime, "SessionLocal", factory)

        async def run():
            entered, release = asyncio.Event(), asyncio.Event()
            calls = []

            async def dispatch():
                calls.append(True)
                entered.set()
                await release.wait()
                return {"ok": True}

            args = dict(
                call_id="concurrent",
                turn_id=turn_id,
                session_id=conversation.id,
                user_id=user.id,
                tool_name="read",
                arguments={"password": "never-store-raw"},
                timeout_seconds=10,
                dispatch=dispatch,
                effect=ToolEffect.READ,
            )
            first = asyncio.create_task(runtime.execute_tool_call(**args))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                assert (await runtime.execute_tool_call(**args))[
                    "error"
                ] == "tool_call_in_progress"
            finally:
                release.set()
                await first
            assert await runtime.execute_tool_call(**args) == {"ok": True}
            assert (
                await runtime.execute_tool_call(
                    **{**args, "arguments": {"password": "different"}}
                )
            )["error"] == "tool_call_identity_conflict"
            assert len(calls) == 1

        asyncio.run(run())
        with factory() as db:
            row = db.query(AgentToolCall).filter_by(call_id="concurrent").one()
            assert row.arguments_json == {"password": "[REDACTED]"}
            assert len(row.arguments_digest) == 64
    finally:
        engine.dispose()
