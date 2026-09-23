"""Persistent revocation invariants, including concurrent token consumption."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.token_blacklist import consume, is_revoked, prune_expired, revoke
from app.models.token_revocation import TokenRevocation


@pytest.fixture
def token_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tokens.db'}")
    TokenRevocation.__table__.create(engine)
    yield engine
    engine.dispose()


def test_concurrent_refresh_has_exactly_one_durable_winner(token_engine):
    barrier = Barrier(8)

    def attempt(_):
        with Session(token_engine) as db:
            barrier.wait(timeout=10)
            won = consume(db, "same-token", 4102444800)
            db.commit()
            return won

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 1
    with Session(token_engine) as db:
        assert is_revoked(db, "same-token")


def test_logout_is_durable_idempotent_and_requires_commit(token_engine):
    with Session(token_engine) as db:
        revoke(db, "access", 4102444800)
        revoke(db, "access", 4102444800)
        revoke(db, "refresh", 4102444800)
        db.commit()
    with Session(token_engine) as db:
        assert is_revoked(db, "access")
        assert is_revoked(db, "refresh")
        revoke(db, "rolled-back", 4102444800)
        db.rollback()
    with Session(token_engine) as db:
        assert not is_revoked(db, "rolled-back")


def test_maintenance_only_removes_expired_tokens(token_engine):
    with Session(token_engine) as db:
        revoke(db, "expired", 1)
        revoke(db, "live", 4102444800)
        assert prune_expired(db) == 1
        db.commit()
        assert is_revoked(db, "live")
        assert not is_revoked(db, "expired")
