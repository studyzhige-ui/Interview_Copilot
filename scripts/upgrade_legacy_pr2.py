"""Explicit, atomic adoption of the unpublished PR2 0059 schema.

Run only after a verified backup and stopping every API/worker process. Default
is read-only inspection. Published main databases use ordinary Alembic instead.
No user rows, ownership IDs, files, or retrieval vectors are rewritten/deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import inspect

MANIFEST = Path(__file__).with_name("migration_baselines") / "pr2_0059_schema.json"


def schema_signature(connection) -> dict:
    inspector = inspect(connection)
    return {
        table: {
            c["name"]: {
                "type": str(c["type"].compile(dialect=connection.dialect)).upper(),
                "nullable": c["nullable"],
            }
            for c in inspector.get_columns(table)
        }
        for table in inspector.get_table_names()
        if table != "alembic_version"
    }


def inspect_legacy(connection) -> str:
    # Register vector reflection without contacting any external service.
    from pgvector.sqlalchemy import VECTOR  # noqa: F401

    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        raise ValueError("No migration identity; do not guess the database baseline")
    versions = (
        connection.execute(sa.text("SELECT version_num FROM alembic_version"))
        .scalars()
        .all()
    )
    if versions != ["0059"]:
        raise ValueError(
            "Only the exact unpublished PR2 0059 baseline is supported; use its original checkout to finish earlier PR2 migrations first"
        )
    expected = json.loads(MANIFEST.read_text())
    actual = schema_signature(connection)
    if actual != expected:
        changed = sorted(
            name
            for name in set(actual) | set(expected)
            if actual.get(name) != expected.get(name)
        )
        raise ValueError(
            "Schema fingerprint mismatch; no changes made. Review tables: "
            + ", ".join(changed)
        )
    return hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()


def adopt(connection, *, backup_confirmed: bool, writers_stopped: bool) -> str:
    if not backup_confirmed or not writers_stopped:
        raise ValueError("A verified backup and stopped writers are required")
    if connection.dialect.name != "postgresql":
        raise ValueError("This adoption path supports PostgreSQL only")
    # Caller owns ONE transaction; any failure rolls all DDL, token invalidation
    # and the revision identity back together. Never stamp an unchecked schema.
    connection.execute(sa.text("SELECT pg_advisory_xact_lock(428107259)"))
    signature = inspect_legacy(connection)
    expected = json.loads(MANIFEST.read_text())
    names = ", ".join('"' + name.replace('"', '""') + '"' for name in sorted(expected))
    connection.execute(
        sa.text(f"LOCK TABLE {names}, alembic_version IN ACCESS EXCLUSIVE MODE")
    )
    if inspect_legacy(connection) != signature:
        raise ValueError("Schema changed while acquiring migration locks")
    connection.execute(
        sa.text(
            "CREATE TABLE token_revocations (jti VARCHAR(64) PRIMARY KEY, expires_at TIMESTAMP WITH TIME ZONE NOT NULL)"
        )
    )
    connection.execute(
        sa.text(
            "CREATE INDEX ix_token_revocations_expires_at ON token_revocations (expires_at)"
        )
    )
    connection.execute(
        sa.text(
            "ALTER TABLE outbox_jobs ADD COLUMN lease_version INTEGER DEFAULT 0 NOT NULL"
        )
    )
    connection.execute(
        sa.text(
            "ALTER TABLE conversation_turns ADD COLUMN cancel_requested BOOLEAN DEFAULT false NOT NULL"
        )
    )
    # Main's security authority transition must also invalidate PR2 Redis-era tokens.
    connection.execute(sa.text("UPDATE users SET token_version = token_version + 1"))
    connection.execute(
        sa.text(
            "UPDATE alembic_version SET version_num = '0072' WHERE version_num = '0059'"
        )
    )
    return signature


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    args = parser.parse_args()
    from app.core.config import settings

    engine = sa.create_engine(settings.DATABASE_URL)
    try:
        with engine.begin() as connection:
            signature = (
                adopt(
                    connection,
                    backup_confirmed=args.backup_confirmed,
                    writers_stopped=args.writers_stopped,
                )
                if args.apply
                else inspect_legacy(connection)
            )
        print(
            (
                "Adopted as 0072; now run alembic upgrade head. "
                if args.apply
                else "Verified PR2 0059; read-only check. "
            )
            + "Schema SHA256: "
            + signature
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
