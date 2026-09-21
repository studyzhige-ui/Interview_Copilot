"""Required CI PostgreSQL concurrency and migration checks for live media."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import inspect
from app.models.user import User
from app.models.mock_media_session import MockMediaSession, MockMediaPlayback
from app.interviews.application import live_media_turns as media
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)
from tests.test_services.interview.test_mock_flow_phase5 import _make_run

database = database_fixture


def test_postgres_single_media_owner_receipts_and_safe_migration(database, monkeypatch):
    _, cfg, factory = database
    with factory() as db:
        actor = User(username="alice", hashed_password="x")
        db.add(actor)
        db.commit()
        record, runtime, _ = _make_run(db)
        record_id, user_pk = record.id, actor.id
        question_id = runtime.current_question_message_id
        assert {"mock_media_sessions", "mock_media_playback"} <= set(
            inspect(db.bind).get_table_names()
        )
    monkeypatch.setattr(media, "SessionLocal", factory)
    barrier = Barrier(2)
    clients = [str(uuid4()), str(uuid4())]

    def claim(client_id):
        barrier.wait(timeout=10)
        try:
            return media.claim(record_id, user_pk, "alice", client_id)
        except ValueError as exc:
            assert str(exc) == "another_media_session_active"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, clients))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    old = winners[0]
    with factory() as db:
        client_id = db.get(MockMediaSession, old.id).client_session_id
    replacement = media.claim(record_id, user_pk, "alice", client_id)
    media.release(old)
    media.renew(replacement)
    audio_id = media.register_audio(replacement, question_id, "q", b"\0\0" * 240, 24000)
    media.acknowledge(replacement, audio_id, 240, True)
    with factory() as db:
        row = db.get(MockMediaPlayback, audio_id)
        assert row.state == "client_reported" and row.reported_samples == 240
    with pytest.raises(RuntimeError, match="require_export"):
        command.downgrade(cfg, "0058")
    command.check(cfg)
    with factory() as db:
        assert db.get(MockMediaPlayback, audio_id).state == "client_reported"
