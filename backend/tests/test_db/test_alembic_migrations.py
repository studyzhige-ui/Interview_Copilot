"""End-to-end test for the 14 alembic migrations.

SQLite cannot execute several of the migrations (0002 adds a column with an
inline FK constraint; SQLite has no ALTER for constraints — alembic batch
mode is not used there). We therefore run the migration chain against a
real Postgres instance.

In CI / dev we expect a Postgres at
``postgresql://postgres:postgres@localhost:5432`` (the Docker compose
service used by the project). The test creates an isolated database
``interview_copilot_test_<uuid>`` for each run and drops it on teardown
so concurrent runs / re-runs never collide.

If Postgres is unreachable the test is skipped — that way `pytest` is
still green in environments without Docker (e.g. lightweight CI),
and CI that does spin up PG catches migration breakage.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest


PG_ADMIN_URL = os.environ.get(
    "TEST_PG_ADMIN_URL",
    "postgresql://postgres:postgres@localhost:5432/postgres",
)
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
ALEMBIC_DIR = PROJECT_ROOT / "alembic"
VERSIONS_DIR = ALEMBIC_DIR / "versions"


def _pg_available() -> bool:
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        return False
    try:
        import psycopg2

        conn = psycopg2.connect(PG_ADMIN_URL)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="Postgres not reachable at TEST_PG_ADMIN_URL — skipping migration test.",
)


@pytest.fixture()
def fresh_pg_db():
    """Provision an isolated, empty Postgres DB; drop it on teardown."""
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    db_name = f"ic_mig_test_{uuid.uuid4().hex[:12]}"

    admin = psycopg2.connect(PG_ADMIN_URL)
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{db_name}"')
    admin.close()

    # Build the target URL by swapping the dbname segment in PG_ADMIN_URL.
    base = PG_ADMIN_URL.rsplit("/", 1)[0]
    db_url = f"{base}/{db_name}"

    yield db_url

    # Teardown — disconnect everyone & drop.
    admin = psycopg2.connect(PG_ADMIN_URL)
    admin.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    with admin.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (db_name,),
        )
        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    admin.close()


def _make_alembic_config(db_url: str):
    """Build an alembic Config bound to ``db_url``.

    ``alembic/env.py`` consults its ``-x url=...`` argument first and only
    falls back to ``settings.DATABASE_URL`` otherwise. We feed the per-test
    DB URL through ``cmd_opts.x`` so env.py picks it up *even though*
    ``app.core.config.settings`` is module-scoped and was bound at import
    time to whatever DATABASE_URL was set when the process started.
    """
    from argparse import Namespace
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI), cmd_opts=Namespace(x=[f"url={db_url}"]))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def test_migration_chain_has_no_gaps_and_one_head():
    """Static check: every revision links cleanly, exactly one head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly one head revision, got {heads}"

    # Walk from head back to base — no dangling down_revision should error.
    revisions = list(script.walk_revisions())
    revision_ids = {rev.revision for rev in revisions}
    # All down_revisions referenced must exist (or be None for the base).
    for rev in revisions:
        downs = rev.down_revision
        if downs is None:
            continue
        if isinstance(downs, str):
            downs = (downs,)
        for d in downs:
            assert d in revision_ids, f"{rev.revision} points at missing {d}"

    # Every on-disk version file must be part of the single linear chain:
    # no orphan revision, no accidentally-deleted middle file. Comparing the
    # file count to the walked-chain length catches both and stays correct as
    # new migrations land — no magic number to bump each package.
    on_disk = [p for p in VERSIONS_DIR.glob("*.py") if not p.name.startswith("_")]
    assert len(on_disk) == len(revisions), (
        f"On-disk version files ({len(on_disk)}) don't match the walked chain "
        f"length ({len(revisions)}) — orphan or deleted migration?"
    )


def test_alembic_upgrade_head_on_fresh_postgres(fresh_pg_db, monkeypatch):
    """Run every migration from 0001 → head against a virgin Postgres."""
    from alembic import command
    from sqlalchemy import create_engine, inspect

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)

    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    # Core tables that must exist after head.
    # After the v3 cleanup migration (0003) ``memory_items`` is GONE — the
    # four v3 doc tables (knowledge_docs / strategy_docs / habit_docs /
    # memory_audit_log) are the replacement.
    expected_tables = {
        "alembic_version",
        "users",
        "file_assets",
        "outbox_jobs",
        "user_model_credentials",
        "user_model_provider_settings",
        "user_model_selections",
        "knowledge_documents",
        "document_chunks",
        "interview_records",
        "interview_qa",
        "mock_interview_sessions",
        "mock_interview_runtime",
        "chat_sessions",
        "chat_messages",
        "memory_documents",
        "memory_ability_states",
        "memory_audit_logs",
        "resumes",
        "resume_sections",
    }
    missing = expected_tables - tables
    assert not missing, f"Missing tables after upgrade head: {missing}"

    # Legacy tables from the pre-squash chain (originally dropped by the
    # old 0008 migration) must NOT exist. We retain this assertion even
    # after squashing so an accidental "restore from old dump" still
    # trips the test. ``memory_items`` is in this list since 0003
    # drops it; ``agent_runs``/``agent_steps`` since 0008 drops them.
    legacy = {
        "interviews", "transcripts", "analysis_results", "interview_states",
        "memory_items", "agent_runs", "agent_steps",
    }
    leftover = legacy & tables
    assert not leftover, f"Legacy tables still present: {leftover}"

    # alembic_version row should be at the current HEAD (bump alongside
    # new migrations so a hand-rolled SQL change is caught here).
    with engine.connect() as conn:
        from sqlalchemy import text

        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        from alembic.script import ScriptDirectory
        expected_head = ScriptDirectory.from_config(cfg).get_current_head()
        assert version == expected_head, (
            f"DB should be at the script head {expected_head!r}, got {version!r}"
        )

    engine.dispose()


def test_hot_query_composite_indexes_exist(fresh_pg_db, monkeypatch):
    """0014 adds composite indexes — confirm they land on the right tables."""
    from alembic import command
    from sqlalchemy import create_engine, inspect

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)

    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    insp = inspect(engine)

    # ``memory_items.ix_memory_items_user_type_key`` was dropped together
    # with the table in 0003; only the still-relevant composite indexes
    # are asserted here.
    expectations = {
        "chat_sessions": "ix_chat_sessions_user_type_arch",
        "knowledge_documents": "ix_knowledge_docs_user_category",
        # ``user_uploads`` (+ its ix_user_uploads_user_purpose) was dropped in
        # 0025; the replacement file_assets table carries the equivalent
        # (user_id, purpose) hot-list composite index (created in 0018).
        "file_assets": "ix_file_assets_user_purpose",
        "interview_qa": "ix_interview_qa_record_order",
    }
    for table, ix_name in expectations.items():
        names = {ix["name"] for ix in insp.get_indexes(table)}
        assert ix_name in names, f"{table} missing composite index {ix_name}: have {names}"

    engine.dispose()


def test_interview_record_child_cascades_after_0009(fresh_pg_db, monkeypatch):
    """Alembic 0009 added ON DELETE CASCADE to the two FKs that the
    ``DELETE /interview-records/{id}`` endpoint silently depended on.

    Verify behaviourally (not just via inspector): insert one parent
    interview_records row + one interview_qa child + one
    mock_interview_sessions child, delete the parent, and assert
    that both children disappear without any IntegrityError. Without
    the cascade, the parent delete would either raise or leave
    orphan children — both are regressions worth pinning.
    """
    from alembic import command
    from sqlalchemy import create_engine, text

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    with engine.begin() as conn:
        # Both mock_interview_sessions.user_id and interview_records.user_id
        # are now integer users.id FKs (CLEANUP #2), so seed a users row and
        # reference its id (1) from both child inserts.
        conn.execute(text(
            "INSERT INTO users (id, username, hashed_password) VALUES (1, 'alice', 'x')"
        ))
        conn.execute(text(
            "INSERT INTO interview_records (id, user_id, source, status) "
            "VALUES ('ir_cascade', 1, 'upload', 'completed')"
        ))
        conn.execute(text(
            "INSERT INTO interview_qa (id, record_id, order_idx, question, answer) "
            "VALUES ('qa_x', 'ir_cascade', 0, 'q?', 'a.')"
        ))
        conn.execute(text(
            "INSERT INTO mock_interview_sessions "
            "(id, user_id, interview_record_id, status, current_question_idx) "
            "VALUES ('mis_x', 1, 'ir_cascade', 'finished', 0)"
        ))

    # The actual cascade probe. Pre-0009 this would have raised
    # IntegrityError because the FKs had no ondelete clause.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM interview_records WHERE id = 'ir_cascade'"))

    with engine.connect() as conn:
        qa_left = conn.execute(text(
            "SELECT count(*) FROM interview_qa WHERE record_id = 'ir_cascade'"
        )).scalar()
        mis_left = conn.execute(text(
            "SELECT count(*) FROM mock_interview_sessions "
            "WHERE interview_record_id = 'ir_cascade'"
        )).scalar()
    assert qa_left == 0, f"interview_qa not cascaded — {qa_left} orphan rows"
    assert mis_left == 0, f"mock_interview_sessions not cascaded — {mis_left} orphan rows"

    engine.dispose()
