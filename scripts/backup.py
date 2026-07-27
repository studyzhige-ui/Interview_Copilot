"""Create and restore portable PostgreSQL + object-storage backups.

Milvus is intentionally not backed up: PostgreSQL document chunks are the
source of truth and ``scripts/reingest_hybrid.py`` rebuilds the vector index.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import settings  # noqa: E402


def _database_parts(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.path.lstrip("/"):
        raise ValueError("Only PostgreSQL DATABASE_URL values are supported")
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
    }


def _run_postgres_tool(
    binary: str,
    args: list[str],
    *,
    database_url: str,
    output=None,
    container: str | None = None,
) -> None:
    db = _database_parts(database_url)
    if container:
        command = [
            "docker",
            "exec",
            "-e",
            f"PGPASSWORD={db['password']}",
            container,
            binary,
            "-h",
            "127.0.0.1",
            "-p",
            "5432",
            "-U",
            db["user"],
            *args,
        ]
        env = None
    else:
        executable = shutil.which(binary)
        if not executable:
            raise RuntimeError(
                f"{binary} was not found; install PostgreSQL client tools or "
                "pass --postgres-container"
            )
        command = [
            executable,
            "-h",
            db["host"],
            "-p",
            db["port"],
            "-U",
            db["user"],
            *args,
        ]
        env = {**os.environ, "PGPASSWORD": db["password"]}
    subprocess.run(command, check=True, env=env, stdout=output)


def _backup_objects(destination: Path) -> int:
    from app.core.storage import s3_client

    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.S3_BUCKET_NAME):
        for item in page.get("Contents", []):
            key = item["Key"]
            target = destination / Path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            s3_client.download_file(settings.S3_BUCKET_NAME, key, str(target))
            count += 1
    return count


def _restore_objects(source: Path) -> int:
    from app.core.storage import s3_client

    count = 0
    for path in source.rglob("*"):
        if path.is_file():
            key = path.relative_to(source).as_posix()
            s3_client.upload_file(str(path), settings.S3_BUCKET_NAME, key)
            count += 1
    return count


def create_backup(args: argparse.Namespace) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(args.output).resolve() / timestamp
    destination.mkdir(parents=True, exist_ok=False)
    dump_path = destination / "database.dump"
    database = _database_parts(settings.DATABASE_URL)["database"]
    with dump_path.open("wb") as output:
        _run_postgres_tool(
            "pg_dump",
            ["--format=custom", "--no-owner", database],
            database_url=settings.DATABASE_URL,
            output=output,
            container=args.postgres_container,
        )
    object_count = (
        _backup_objects(destination / "objects") if args.include_objects else 0
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": database,
        "database_dump": dump_path.name,
        "objects_included": args.include_objects,
        "object_count": object_count,
        "milvus_rebuild_command": "python scripts/reingest_hybrid.py",
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return destination


def restore_backup(args: argparse.Namespace) -> int:
    source = Path(args.backup).resolve()
    dump_path = source / "database.dump"
    if not dump_path.is_file():
        raise FileNotFoundError(f"Missing backup file: {dump_path}")
    source_db = _database_parts(settings.DATABASE_URL)["database"]
    target = _database_parts(args.target_database_url)
    if target["database"] == source_db and not args.allow_source_database:
        raise RuntimeError(
            "Refusing to restore over the configured source database; use a "
            "different --target-database-url"
        )
    with dump_path.open("rb") as dump:
        subprocess_args = [
            "--clean",
            "--if-exists",
            "--no-owner",
            "--dbname",
            target["database"],
        ]
        if args.postgres_container:
            command = [
                "docker",
                "exec",
                "-i",
                "-e",
                f"PGPASSWORD={target['password']}",
                args.postgres_container,
                "pg_restore",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                target["user"],
                *subprocess_args,
            ]
            subprocess.run(command, check=True, stdin=dump)
        else:
            executable = shutil.which("pg_restore")
            if not executable:
                raise RuntimeError("pg_restore was not found")
            command = [
                executable,
                "-h",
                target["host"],
                "-p",
                target["port"],
                "-U",
                target["user"],
                *subprocess_args,
            ]
            subprocess.run(
                command,
                check=True,
                stdin=dump,
                env={**os.environ, "PGPASSWORD": target["password"]},
            )
    if args.restore_objects:
        objects = source / "objects"
        if not objects.is_dir():
            raise FileNotFoundError("Backup does not contain an objects directory")
        _restore_objects(objects)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--output", default="data/backups")
    create.add_argument("--include-objects", action="store_true")
    create.add_argument("--postgres-container")
    create.set_defaults(handler=create_backup)

    restore = subparsers.add_parser("restore")
    restore.add_argument("backup")
    restore.add_argument("--target-database-url", required=True)
    restore.add_argument("--restore-objects", action="store_true")
    restore.add_argument("--allow-source-database", action="store_true")
    restore.add_argument("--postgres-container")
    restore.set_defaults(handler=restore_backup)

    args = parser.parse_args()
    result = args.handler(args)
    if isinstance(result, Path):
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
