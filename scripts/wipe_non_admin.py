"""Delete every trace of non-admin users from the system.

Wipes, in this order (each step transactional or idempotent):
  1. Milvus  — vector rows whose ``doc_id`` belongs to a non-admin user
  2. Postgres — rows in every user-scoped table, then the users themselves
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


# Every user-scoped table now keys on the stable users.id integer FK (CLEANUP #2
# migrated the last of them — document_chunks / resume_sections). The ``users``
# row itself is matched by its username column (handled separately at the end).
# conversation_messages / interview_qa carry no user_id — they're wiped via a
# parent-id subquery (handled specially below).
USER_PK_TABLES = (
    "file_assets",
    "outbox_jobs",
    "user_model_credentials",
    "user_model_provider_settings",
    "user_model_selections",
    "memory_documents",
    "memory_ability_states",
    "memory_audit_logs",
    "resumes",
    "knowledge_documents",
    "interview_records",
    "mock_interview_sessions",
    "mock_interview_runtime",
    "conversations",
    "document_chunks",
    "resume_sections",
)
# Order is exception-tolerant (each statement runs in its own savepoint), but we
# still wipe children before parents for any non-CASCADE FK.

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

    NOTE: every user-scoped table compares ``user_id`` against the admin's stable
    users.id pk; the two child tables join their pk-keyed parent. Each count runs
    in its own implicit savepoint — if one fails (table missing, column mis-typed)
    we rollback and continue, instead of the whole transaction going into aborted
    state.
    """
    admin_pk = db.execute(
        text("SELECT id FROM users WHERE username = :auname"), {"auname": admin_username},
    ).scalar()

    # (table, sql, params) — children-via-parent first, then the pk tables.
    queries: list[tuple[str, str, dict]] = [
        ("conversation_messages",
         "SELECT COUNT(*) FROM conversation_messages cm JOIN conversations cs "
         "ON cm.session_id = cs.id WHERE cs.user_id != :apk", {"apk": admin_pk}),
        ("interview_qa",
         "SELECT COUNT(*) FROM interview_qa iq JOIN interview_records ir "
         "ON iq.record_id = ir.id WHERE ir.user_id != :apk", {"apk": admin_pk}),
    ]
    queries += [
        (t, f"SELECT COUNT(*) FROM {t} WHERE user_id != :apk", {"apk": admin_pk})
        for t in USER_PK_TABLES
    ]

    counts: dict[str, int] = {}
    for table, q, params in queries:
        try:
            counts[table] = db.execute(text(q), params).scalar() or 0
        except Exception as exc:
            db.rollback()  # clear aborted state so the NEXT query can run
            counts[table] = -1
            print(f"  (skipping {table}: {type(exc).__name__})")
    return counts


def _non_admin_doc_ids(db, admin_username: str) -> list[str]:
    """Collect every Milvus-side ``doc_id`` that points at non-admin data.

    Source table:
      * ``knowledge_documents.id`` — the ``kdoc_*`` key stored as
        ``doc_id`` in the ``interview_copilot_rag`` collection.
    Post-v3 cleanup (alembic 0003 dropped ``memory_items``): only
    ``knowledge_documents.id`` is a valid source. The historical UNION
    against ``memory_items`` would now crash with ``relation
    "memory_items" does not exist`` on every invocation — operators
    trying to wipe a staging DB would get nothing wiped.

    The ``interview_copilot_memory`` collection itself was retired by
    the v3 migration; Milvus delete iterates whatever collections exist
    today (``_delete_milvus_vectors`` skips missing collections).
    """
    admin_pk = db.execute(
        text("SELECT id FROM users WHERE username = :auname"), {"auname": admin_username},
    ).scalar()
    rows = db.execute(
        text(
            "SELECT id FROM knowledge_documents WHERE user_id != :apk"
        ),
        {"apk": admin_pk},
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
    """One transaction; each DELETE runs in its own savepoint so a missing
    table is skipped rather than aborting the whole run.

    Every user-scoped table compares ``user_id`` against the admin's stable
    users.id pk; the two child tables join their pk-keyed parent. The ``users``
    table itself is filtered on its ``username``.
    """
    if dry_run:
        return
    admin_pk = db.execute(
        text("SELECT id FROM users WHERE username = :auname"), {"auname": admin_username},
    ).scalar()

    # Children-via-parent first, then the pk tables.
    deletes: list[tuple[str, str, dict]] = [
        ("interview_qa",
         "DELETE FROM interview_qa WHERE record_id IN "
         "(SELECT id FROM interview_records WHERE user_id != :apk)", {"apk": admin_pk}),
        ("conversation_messages",
         "DELETE FROM conversation_messages WHERE session_id IN "
         "(SELECT id FROM conversations WHERE user_id != :apk)", {"apk": admin_pk}),
    ]
    deletes += [
        (t, f"DELETE FROM {t} WHERE user_id != :apk", {"apk": admin_pk})
        for t in USER_PK_TABLES
    ]

    for table, sql, params in deletes:
        try:
            db.execute(text(sql), params)
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
        print("\n=== Plan ===")
        print(f"  Keep:    id={admin_id}  username='{args.admin_username}'")
        print(f"  Wipe:    {len(others)} other user(s): "
              f"{[(u.id, u.username) for u in others]}")

        pg_counts = _count_rows_per_table(db, args.admin_username)
        print("\n  Postgres rows to delete:")
        for t, n in pg_counts.items():
            if n >= 0:
                print(f"    {t:<28} {_human(n):>8}")
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
