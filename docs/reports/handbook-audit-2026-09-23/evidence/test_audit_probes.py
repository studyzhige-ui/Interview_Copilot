"""Isolated reproductions: no real credentials, providers or business DB writes."""
import asyncio
import inspect
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_refresh_token_can_be_consumed_twice(monkeypatch):
    from app.api import auth
    from app.schemas.auth import RefreshRequest

    arrivals = 0
    both_checked = asyncio.Event()
    writes = []

    async def is_revoked(jti):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_checked.set()
        await both_checked.wait()
        return False

    async def revoke(jti, exp=None):
        writes.append(jti)

    monkeypatch.setattr(auth, 'decode_token', lambda _: {'sub': '1', 'type': 'refresh', 'jti': 'same-jti', 'token_version': 0, 'exp': 9999999999})
    monkeypatch.setattr(auth, 'is_revoked', is_revoked)
    monkeypatch.setattr(auth, 'revoke', revoke)
    monkeypatch.setattr(auth.user_account_service, 'get_by_id', lambda *args: SimpleNamespace(id=1, token_version=0))
    monkeypatch.setattr(auth, 'token_claims_for', lambda _: {'sub': '1', 'token_version': 0})
    monkeypatch.setattr(auth, 'create_access_token', lambda **_: 'new-access')
    monkeypatch.setattr(auth, 'create_refresh_token', lambda **_: 'new-refresh')
    endpoint = inspect.unwrap(auth.refresh_access_token)
    async def call():
        return await endpoint(request=None, response=None, body=RefreshRequest(refresh_token='old-refresh'), db=None)
    results = await asyncio.wait_for(asyncio.gather(call(), call()), 3)
    assert len(results) == 2 and len(writes) == 2
    assert all(result['access_token'] == 'new-access' for result in results)


@pytest.mark.asyncio
async def test_sse_redis_failure_bypasses_db_recovery(monkeypatch):
    from app.api.chat import streaming
    from app.services.chat.turn_event_buffer import turn_event_buffer

    monkeypatch.setattr(streaming, 'resolve_user_pk', lambda *args: 1)
    db = SimpleNamespace(get=lambda *args: SimpleNamespace(conversation_id='conv', user_id=1))
    calls = []
    monkeypatch.setattr(streaming, '_turn_terminal_state', lambda *args: calls.append('db') or ('completed', None))
    async def broken_read(*args):
        raise ConnectionError('isolated redis outage')
    monkeypatch.setattr(turn_event_buffer, 'read', broken_read)
    response = await streaming.stream_chat_turn_events('conv', 'turn', after=None, last_event_id=None, current_user=SimpleNamespace(username='audit'), db=db)
    with pytest.raises(ConnectionError, match='isolated redis outage'):
        await anext(response.body_iterator)
    assert calls == []


@pytest.mark.asyncio
async def test_revoke_returns_success_after_write_failure(monkeypatch):
    from app.core import token_blacklist
    async def fail(*args, **kwargs):
        raise ConnectionError('isolated redis outage')
    monkeypatch.setattr(token_blacklist, 'redis_client', SimpleNamespace(set=fail))
    assert await token_blacklist.revoke('audit-jti', exp=9999999999) is None


def test_async_client_cache_returns_same_object_to_distinct_loops(monkeypatch):
    from collections import OrderedDict
    from app.core import llm_client_factory as factory

    monkeypatch.setattr(factory, '_async_openai_cache', OrderedDict())
    monkeypatch.setattr(factory, 'resolve_api_key', lambda *a, **k: 'fake-key')
    monkeypatch.setattr(factory, '_load_user_provider_overrides', lambda *a: factory._NO_OVERRIDES)
    monkeypatch.setattr(factory, 'AsyncOpenAI', lambda **kwargs: object())
    profile = SimpleNamespace(id='audit-profile', api_base='https://example.invalid')
    async def acquire():
        return asyncio.get_running_loop(), factory.get_async_openai_client(profile, 'audit-user')
    loop1, loop2 = asyncio.new_event_loop(), asyncio.new_event_loop()
    try:
        first = loop1.run_until_complete(acquire())
        second = loop2.run_until_complete(acquire())
        assert first[0] is not second[0]
        assert first[1] is second[1]
    finally:
        loop1.close()
        loop2.close()


@pytest.mark.asyncio
async def test_unstarted_pending_turn_is_failed_after_queue_delay(monkeypatch):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.models
    from app.db.database import Base
    from app.db.types import utc_now
    from app.models.user import User
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.services.chat import turn_executor as executor

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        user = User(username='audit-only', hashed_password='x')
        db.add(user)
        db.flush()
        conv = Conversation(id='audit-conv', user_id=user.id, title='audit', type='general', active_turn_id='audit-turn')
        turn = ConversationTurn(id='audit-turn', conversation_id=conv.id, user_id=user.id, mode='agent', message='queued', status='pending', created_at=utc_now() - timedelta(seconds=61))
        db.add_all([conv, turn])
        db.commit()
    monkeypatch.setattr(executor, 'SessionLocal', sessions)
    monkeypatch.setattr(executor.settings, 'TURN_STALE_SECONDS', 60)
    monkeypatch.setattr(executor, '_admit_persistent_task_after_user_terminal', lambda *a, **k: None)
    monkeypatch.setattr(executor.transcript_service, 'complete_background_turn', lambda **k: 2)
    async def append(*args):
        return '1-0'
    monkeypatch.setattr(executor.turn_event_buffer, 'append', append)
    try:
        assert await executor.fail_orphaned_turns() == 1
        with sessions() as db:
            turn = db.get(ConversationTurn, 'audit-turn')
            assert turn.status == 'failed' and turn.started_at is None
    finally:
        engine.dispose()


def test_expired_outbox_owner_overwrites_new_owner_success(monkeypatch):
    from datetime import timedelta
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    import app.models
    from app.db.database import Base
    from app.db.types import utc_now
    from app.models.outbox_job import OutboxJob
    from app.services import outbox

    engine = create_engine('sqlite://', poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    initial = utc_now()
    clock = [initial]
    monkeypatch.setattr(outbox, 'utc_now', lambda: clock[0])
    attempts = []
    def handler(db, job):
        attempts.append(job.locked_by)
        if len(attempts) == 1:
            clock[0] = initial + timedelta(minutes=21)
            with sessions() as newer:
                assert outbox.run_due_outbox_jobs(newer, limit=1) == 1
                assert newer.get(OutboxJob, 'audit-job').status == 'succeeded'
            raise TimeoutError('old worker returns after lease was reassigned')
    monkeypatch.setattr(outbox, '_HANDLERS', {'audit_probe': handler})
    try:
        with sessions() as db:
            db.add(OutboxJob(id='audit-job', user_id=1, job_type='audit_probe', status='pending', attempts=0, max_attempts=5, next_run_at=initial))
            db.commit()
            assert outbox.run_due_outbox_jobs(db, limit=1) == 1
        with sessions() as db:
            assert len(attempts) == 2
            assert db.get(OutboxJob, 'audit-job').status == 'failed'
    finally:
        engine.dispose()
