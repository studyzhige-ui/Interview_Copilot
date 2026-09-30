"""Preserve both published main and unpublished PR2 data during adoption."""

import tarfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from alembic import command
from scripts.upgrade_legacy_pr2 import adopt, inspect_legacy
from tests.test_db.test_alembic_migrations import fresh_pg_db, _make_alembic_config  # noqa: F401


def test_published_main_upgrade_preserves_owner_and_content(fresh_pg_db):  # noqa: F811
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "0052")
    engine = create_engine(fresh_pg_db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, is_active, email_verified, token_version, created_at, updated_at) VALUES (101, 'main-owner', 'fixture', true, true, 3, now(), now())"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT username, token_version FROM users WHERE id = 101")
        ).one() == ("main-owner", 3)
    command.check(cfg)
    engine.dispose()


def test_pr2_upgrade_is_explicit_atomic_and_preserves_owners(fresh_pg_db, tmp_path):  # noqa: F811
    source = Path(__file__).parents[1] / "fixtures/pr2_2803c798_migrations.tar"
    with tarfile.open(source) as archive:
        archive.extractall(tmp_path, filter="data")
    cfg = _make_alembic_config(fresh_pg_db)
    cfg.set_main_option("script_location", str(tmp_path / "alembic"))
    command.upgrade(cfg, "head")
    engine = create_engine(fresh_pg_db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, is_active, email_verified, token_version, last_dreamed_at, created_at, updated_at) VALUES (102, 'pr2-owner', 'fixture', true, true, 3, now(), now(), now())"
            )
        )
        signature = inspect_legacy(conn)
        with pytest.raises(ValueError, match="verified backup"):
            adopt(conn, backup_confirmed=False, writers_stopped=True)
    canonical = _make_alembic_config(fresh_pg_db)
    with pytest.raises(RuntimeError, match="Unpublished PR2"):
        command.upgrade(canonical, "head")
    with engine.begin() as conn:
        assert adopt(conn, backup_confirmed=True, writers_stopped=True) == signature
    command.upgrade(canonical, "head")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT username, token_version, last_dreamed_at FROM users WHERE id = 102"
            )
        ).one()
        assert row[:2] == ("pr2-owner", 4)
        assert row[2] is not None
    command.check(canonical)
    engine.dispose()


def test_schema_signature_preserves_postgresql_timezone_and_array_types(monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy.dialects import postgresql
    from scripts import upgrade_legacy_pr2

    inspector = SimpleNamespace(
        get_table_names=lambda: ["sample", "alembic_version"],
        get_columns=lambda _: [
            {
                "name": "at",
                "type": postgresql.TIMESTAMP(timezone=True),
                "nullable": False,
            },
            {
                "name": "terms",
                "type": postgresql.ARRAY(postgresql.TEXT()),
                "nullable": True,
            },
        ],
    )
    monkeypatch.setattr(upgrade_legacy_pr2, "inspect", lambda _: inspector)
    result = upgrade_legacy_pr2.schema_signature(
        SimpleNamespace(dialect=postgresql.dialect())
    )
    assert result == {
        "sample": {
            "at": {"type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
            "terms": {"type": "TEXT[]", "nullable": True},
        }
    }
