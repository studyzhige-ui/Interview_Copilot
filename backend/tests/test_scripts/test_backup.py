import argparse

import pytest

from scripts import backup


def test_database_parts_decodes_credentials():
    parts = backup._database_parts("postgresql://alice:p%40ss@db.example:5433/copilot")

    assert parts == {
        "host": "db.example",
        "port": "5433",
        "user": "alice",
        "password": "p@ss",
        "database": "copilot",
    }


def test_restore_refuses_configured_source_database(tmp_path, monkeypatch):
    (tmp_path / "database.dump").write_bytes(b"dump")
    monkeypatch.setattr(
        backup.settings,
        "DATABASE_URL",
        "postgresql://postgres:secret@localhost/interview_copilot",
    )
    args = argparse.Namespace(
        backup=str(tmp_path),
        target_database_url=backup.settings.DATABASE_URL,
        restore_objects=False,
        allow_source_database=False,
        postgres_container=None,
    )

    with pytest.raises(RuntimeError, match="Refusing to restore"):
        backup.restore_backup(args)
