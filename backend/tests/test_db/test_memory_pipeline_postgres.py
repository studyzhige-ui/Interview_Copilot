"""Real PostgreSQL fencing and non-empty upgrade, not SQLite lock simulations."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models.memory_pipeline import MemoryExtraction
from app.services import memory_pipeline as pipeline
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401
from tests.test_services.test_memory_pipeline import source


def test_retention_read_filter_on_postgres(fresh_pg_db, monkeypatch):  # noqa: F811
    from app.db.types import utc_now
    from app.models.long_term_memory import LongTermAgentMemory
    from app.services import memory_recall
    from tests.test_services.test_memory_pipeline import model

    command.upgrade(_make_alembic_config(fresh_pg_db), "head")
    engine = create_engine(fresh_pg_db)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(memory_recall, "SessionLocal", factory)
    monkeypatch.setattr(pipeline, "model_json", model)
    monkeypatch.setattr(pipeline.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True)
    try:
        with factory() as db:
            user, conversation, turn = source(db, suffix="pg-retention")
            user_id, conversation_id, turn_id = user.id, conversation.id, turn.id
        assert asyncio.run(pipeline.process_turn(turn_id)) == 1
        with factory() as db:
            db.get(MemoryExtraction, turn_id).generated_at = utc_now() - timedelta(
                days=100
            )
            db.commit()
        monkeypatch.setattr(pipeline.settings, "AGENT_MEMORY_PRODUCER_ENABLED", False)
        assert (
            asyncio.run(
                memory_recall.recall(
                    conversation_id=conversation_id,
                    user_pk=user_id,
                    current_query="比较两个方案",
                    turn_id=turn_id,
                )
            )
            == ""
        )
        with factory() as db:
            assert db.query(LongTermAgentMemory).one().status == "active"
            pipeline._forget_expired(db, user_id)
            db.commit()
            assert db.get(MemoryExtraction, turn_id).status == "forgotten"
    finally:
        engine.dispose()


def test_upgrade_preserves_legacy_rows_and_parallel_claim_is_fenced(
    fresh_pg_db,  # noqa: F811 - imported pytest fixture
    monkeypatch,
):
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "0043")
    engine = create_engine(fresh_pg_db)
    with engine.begin() as connection:
        user_id = connection.execute(
            text(
                "INSERT INTO users (username, hashed_password, created_at, updated_at, email_verified) "
                "VALUES ('legacy-memory-owner', 'x', now(), now(), false) RETURNING id"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO long_term_agent_memories "
                "(id,user_id,semantic_key,content,applicability,tags_json,valence,confidence,status,"
                "content_hash,version,formed_at,last_confirmed_at,recall_count,created_at,updated_at) "
                "VALUES ('legacy',:owner,'old-pattern','原有内容','原有条件','[]','effective',0.8,"
                "'active','hash',1,now(),now(),0,now(),now())"
            ),
            {"owner": user_id},
        )
    command.upgrade(cfg, "0044")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT content,origin,usage_count FROM long_term_agent_memories WHERE id='legacy'"
            )
        ).one()
        assert tuple(row) == ("原有内容", "legacy", 0)
    # The upgrade assertion above targets 0044; runtime concurrency below uses
    # today's ORM, including later Tool Call identity columns.
    command.upgrade(cfg, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", factory)
    monkeypatch.setattr(pipeline.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True)
    with factory() as db:
        _, _, turn = source(db, suffix="concurrency")
        turn_id = turn.id
    entered, release = Event(), Event()

    async def blocked_model(*_):
        entered.set()
        assert await asyncio.to_thread(release.wait, 15)
        return {"summary": "", "candidates": []}

    monkeypatch.setattr(pipeline, "model_json", blocked_model)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(asyncio.run, pipeline.extract_turn(turn_id))
            assert entered.wait(10)
            second = pool.submit(asyncio.run, pipeline.extract_turn(turn_id))
            assert second.result(timeout=10) is None
            release.set()
            assert first.result(timeout=10) is not None
        with factory() as db:
            job = db.get(MemoryExtraction, turn_id)
            assert job.attempts == 1 and job.status == "no_output"
    finally:
        release.set()
        engine.dispose()
