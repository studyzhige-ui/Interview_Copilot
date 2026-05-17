"""Delete every trace of non-admin users from the system.

Wipes, in this order (each step transactional or idempotent):
  1. Milvus  — vector rows whose ``doc_id`` belongs to a non-admin user
  2. Postgres — rows in 9 user-scoped tables, then the users themselves
  3. MinIO   — object keys under ``uploads/<username>/`` and ``avatars/<username>/``
               for every non-admin username

The ``users.id`` sequence is NOT reset — admin keeps id=5, the next register
gets id=6. No id collision is possible.

Run dry-first to see exactly what will go:

    python scripts/wipe_non_admin.py --admin-username admin --dry-run

Then commit:

    python scripts/wipe_non_admin.py --admin-username admin --yes
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the project's backend code importable.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text

from app.db.database import SessionLocal
from app.models.user import User


# Tables with a ``user_id`` FK. Order doesn't matter because we delete inside
# a single transaction and Postgres handles FK cascades; we just need to hit
# every place that contains user-scoped data.
USER_TABLES = (
    "user_api_keys",
    "user_uploads",
    "knowledge_documents",
    "memory_items",
    "chat_sessions",
    "chat_messages",            # FK via chat_sessions.user_id
    "mock_interview_sessions",
    "interview_records",
    "interview_qa",             # FK via interview_records.user_id
    "agent_runs",
    "resume_sections",
)

MILVUS_COLLECTIONS = (
    "interview_copilot_rag",
    "interview_copilot_memory",
    "interview_copilot_resume",  # may not exist yet — handled
)

MINIO_PREFIXES = ("uploads/", "avatars/")


def _human(n: int) -> str:
    return f"{n:,}"


def _admin_id_and_other_users(db, admin_username: str) -> tuple[int, list[User]]:
    admin = db.query(User).filter(User.username == admin_username).first()
    if admin is None:
        sys.exit(
            f"ERROR: no user with username='{admin_username}' in this DB. "
            f"Did you mean one of: "
            f"{[u.username for u in db.query(User).all()]}"
        )
    others = db.query(User).filter(User.id != admin.id).all()
    return admin.id, others


def _count_rows_per_table(db, admin_username: str) -> dict[str, int]:
    """For each user-scoped table, count rows that would be deleted.

    NOTE: in this schema ``<table>.user_id`` is VARCHAR storing the *username*
    (NOT users.id integer FK). So all comparisons run against the username.

    Each count runs in its own implicit savepoint — if one fails (table
    missing, column mis-typed) we rollback and continue, instead of the
    whole transaction going into aborted state.
    """
    counts: dict[str, int] = {}
    for table in USER_TABLES:
        if table == "chat_messages":
            q = (
                "SELECT COUNT(*) FROM chat_messages cm "
                "JOIN chat_sessions cs ON cm.session_id = cs.id "
                "WHERE cs.user_id != :auname"
            )
        elif table == "interview_qa":
            q = (
                "SELECT COUNT(*) FROM interview_qa iq "
                "JOIN interview_records ir ON iq.record_id = ir.id "
                "WHERE ir.user_id != :auname"
            )
        else:
            q = f"SELECT COUNT(*) FROM {table} WHERE user_id != :auname"
        try:
            counts[table] = db.execute(text(q), {"auname": admin_username}).scalar() or 0
        except Exception as exc:
            db.rollback()  # clear aborted state so the NEXT query can run
            counts[table] = -1
            print(f"  (skipping {table}: {type(exc).__name__})")
    return counts


def _non_admin_doc_ids(db, admin_username: str) -> list[str]:
    """Collect every Milvus-side ``doc_id`` that points at non-admin data.

    Two source tables:
      * ``knowledge_documents.id`` — the ``kdoc_*`` key stored as
        ``doc_id`` in the ``interview_copilot_rag`` collection.
      * ``memory_items.id`` (UUID) — stored as ``doc_id`` in the
        ``interview_copilot_memory`` collection.

    We merge both into one expression; entries that don't exist in a given
    collection are simply no-ops at delete time.
    """
    rows = db.execute(
        text(
            "SELECT id FROM knowledge_documents WHERE user_id != :auname "
            "UNION "
            "SELECT id FROM memory_items WHERE user_id != :auname"
        ),
        {"auname": admin_username},
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def _delete_milvus_vectors(doc_ids: list[str], dry_run: bool) -> dict[str, int]:
    """Delete every Milvus row whose ``doc_id`` is in ``doc_ids``.

    Skips collections that don't exist (interview_copilot_resume might not be
    initialised yet). Returns per-collection deleted count.
    """
    from pymilvus import Collection, connections, utility

    milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
    host = milvus_uri.replace("http://", "").replace("https://", "").split(":")[0]
    port = milvus_uri.rsplit(":", 1)[-1] if ":" in milvus_uri.replace("://", "") else "19530"
    connections.connect(host=host, port=port)

    results: dict[str, int] = {}
    if not doc_ids:
        for name in MILVUS_COLLECTIONS:
            results[name] = 0
        return results

    # Milvus' delete-by-expression is fastest with `in [...]`. To stay under
    # the expression-length limit on huge batches, chunk into groups of 100.
    chunk_size = 100
    for name in MILVUS_COLLECTIONS:
        if not utility.has_collection(name):
            results[name] = -1  # not present
            continue
        c = Collection(name)
        c.load()
        deleted = 0
        for i in range(0, len(doc_ids), chunk_size):
            chunk = doc_ids[i:i + chunk_size]
            # doc_id is a VARCHAR field — quote each value.
            expr = "doc_id in [" + ", ".join(f'"{d}"' for d in chunk) + "]"
            try:
                if not dry_run:
                    c.delete(expr)
                # Milvus returns delete count via res.delete_count, but only
                # if it executed. For dry-run we use a query() instead so
                # the user sees the real count.
                count_res = c.query(expr=expr, output_fields=["doc_id"], limit=chunk_size)
                deleted += len(count_res)
            except Exception as exc:
                print(f"  Milvus {name} chunk {i//chunk_size} failed: {exc}")
        if not dry_run:
            c.flush()
        results[name] = deleted
    return results


def _delete_postgres_rows(db, admin_username: str, dry_run: bool) -> None:
    """One transaction; Postgres FK cascade handles join tables automatically.

    Schema quirk: child tables store **username** (VARCHAR) in their
    ``user_id`` column, not the integer ``users.id``. So we compare on
    username everywhere — and on the ``users`` table itself we use the actual
    ``username`` column.
    """
    if dry_run:
        return
    # Delete in reverse dependency order so non-CASCADE FKs don't trip.
    for table in (
        "interview_qa",            # child of interview_records
        "chat_messages",           # child of chat_sessions
        "agent_runs",
        "user_api_keys",
        "user_uploads",
        "memory_items",
        "knowledge_documents",
        "resume_sections",
        "interview_records",
        "mock_interview_sessions",
        "chat_sessions",
    ):
        try:
            if table == "chat_messages":
                db.execute(text(
                    "DELETE FROM chat_messages WHERE session_id IN "
                    "(SELECT id FROM chat_sessions WHERE user_id != :auname)"
                ), {"auname": admin_username})
            elif table == "interview_qa":
                db.execute(text(
                    "DELETE FROM interview_qa WHERE record_id IN "
                    "(SELECT id FROM interview_records WHERE user_id != :auname)"
                ), {"auname": admin_username})
            else:
                db.execute(text(f"DELETE FROM {table} WHERE user_id != :auname"),
                           {"auname": admin_username})
        except Exception as exc:
            db.rollback()
            print(f"  (skipping {table} delete: {type(exc).__name__}: {exc})")
    # Finally the users themselves — note ``users`` uses ``username`` column.
    db.execute(text("DELETE FROM users WHERE username != :auname"),
               {"auname": admin_username})
    db.commit()


def _delete_minio_objects(admin_username: str, dry_run: bool) -> dict[str, int]:
    """Delete every uploads/<username>/ and avatars/<username>/ tree where
    <username> isn't admin. Uses boto3 against the local MinIO."""
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("AWS_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "minioadmin"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(signature_version="s3v4"),
    )
    bucket = os.getenv("S3_BUCKET_NAME", "interview-copilot-bucket")

    counts: dict[str, int] = {}
    for prefix in MINIO_PREFIXES:
        deleted = 0
        # Paginate — MinIO returns at most 1000 keys per page.
        token = None
        to_delete: list[dict] = []
        while True:
            kw = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = s3.list_objects_v2(**kw)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                # Key shape: "<prefix><username>/..." — extract username.
                rest = key[len(prefix):]
                user_part = rest.split("/", 1)[0] if "/" in rest else rest
                if user_part != admin_username:
                    to_delete.append({"Key": key})
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")

        if to_delete and not dry_run:
            # delete_objects takes batches of up to 1000.
            for i in range(0, len(to_delete), 1000):
                s3.delete_objects(Bucket=bucket, Delete={"Objects": to_delete[i:i+1000]})
        deleted = len(to_delete)
        counts[prefix] = deleted
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--admin-username", required=True,
                   help="Username to keep. Everything else gets wiped.")
    p.add_argument("--dry-run", action="store_true",
                   help="Show counts without deleting anything.")
    p.add_argument("--yes", action="store_true",
                   help="Required (in addition to no --dry-run) to actually delete.")
    args = p.parse_args()

    if not args.dry_run and not args.yes:
        sys.exit("Refusing to run destructively without --yes. Re-run with --dry-run first.")

    db = SessionLocal()
    try:
        admin_id, others = _admin_id_and_other_users(db, args.admin_username)
        print(f"\n=== Plan ===")
        print(f"  Keep:    id={admin_id}  username='{args.admin_username}'")
        print(f"  Wipe:    {len(others)} other user(s): "
              f"{[(u.id, u.username) for u in others]}")

        pg_counts = _count_rows_per_table(db, args.admin_username)
        print("\n  Postgres rows to delete:")
        for t in USER_TABLES:
            if pg_counts[t] >= 0:
                print(f"    {t:<28} {_human(pg_counts[t]):>8}")
        print(f"    {'users':<28} {_human(len(others)):>8}")

        non_admin_docs = _non_admin_doc_ids(db, args.admin_username)
        print(f"\n  Milvus doc_ids that point to non-admin data: "
              f"{_human(len(non_admin_docs))}")

        # Apply now.
        print(f"\n=== {'Dry run' if args.dry_run else 'Executing'} ===")
        milvus_res = _delete_milvus_vectors(non_admin_docs, dry_run=args.dry_run)
        for name, n in milvus_res.items():
            marker = "(no collection)" if n == -1 else f"{_human(n)} rows"
            print(f"  Milvus {name:<32} {marker}")

        minio_res = _delete_minio_objects(args.admin_username, dry_run=args.dry_run)
        for prefix, n in minio_res.items():
            print(f"  MinIO  {prefix:<32} {_human(n)} object(s)")

        _delete_postgres_rows(db, args.admin_username, dry_run=args.dry_run)
        verb = "would delete" if args.dry_run else "deleted"
        print(f"  Postgres: {verb} rows + {len(others)} user(s)")

        print(f"\n{'(dry run — nothing changed)' if args.dry_run else 'Done.'}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
