"""PostgreSQL arbitrates refresh consumption, independently of Redis."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.token_blacklist import consume, is_revoked
from app.models.token_revocation import TokenRevocation
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401


def test_release_schema_has_no_drift(fresh_pg_db):  # noqa: F811
    from alembic import command
    from tests.test_db.test_alembic_migrations import _make_alembic_config

    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")
    engine = create_engine(fresh_pg_db)
    try:
        command.check(cfg)
        command.downgrade(cfg, "0051")
        command.upgrade(cfg, "head")
        command.check(cfg)
    finally:
        engine.dispose()


def test_postgres_refresh_has_one_winner(fresh_pg_db):  # noqa: F811
    engine = create_engine(fresh_pg_db, pool_size=8)
    TokenRevocation.__table__.create(engine)
    barrier = Barrier(8)

    def attempt(_):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            won = consume(db, "contested-jti", 4102444800)
            db.commit()
            return won

    try:
        with ThreadPoolExecutor(max_workers=8) as workers:
            assert sum(workers.map(attempt, range(8))) == 1
        engine.dispose()
        with Session(engine) as db:
            assert is_revoked(db, "contested-jti")
    finally:
        engine.dispose()
