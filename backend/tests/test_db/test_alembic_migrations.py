"""End-to-end test for the Alembic release baseline.

Migration behavior is tested against PostgreSQL because that is the supported
database and several indexes use PostgreSQL-specific predicates.

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
MODELS_DIR = PROJECT_ROOT / "backend" / "app" / "models"


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


@pytest.fixture()
def fresh_pg_db():
    """Provision an isolated, empty Postgres DB; drop it on teardown."""
    if not _pg_available():
        pytest.skip(
            "Postgres not reachable at TEST_PG_ADMIN_URL — skipping migration test."
        )

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


def test_release_schema_identifiers_fit_postgres_limit():
    """Catch DDL names that PostgreSQL refuses before a live upgrade is run."""
    import ast

    import app.models  # noqa: F401 -- populates the one declarative registry
    from app.db.database import Base

    max_length = 63
    metadata_names: list[str] = []
    for table in Base.metadata.tables.values():
        metadata_names.append(table.name)
        metadata_names.extend(column.name for column in table.columns)
        metadata_names.extend(
            item.name
            for item in (*table.constraints, *table.indexes)
            if item.name is not None
        )

    too_long = sorted({name for name in metadata_names if len(name) > max_length})

    named_operations = {
        "create_table",
        "create_index",
        "create_check_constraint",
        "create_unique_constraint",
        "create_foreign_key",
        "drop_constraint",
        "drop_index",
    }
    for path in VERSIONS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in named_operations or not node.args:
                continue
            name_arg = node.args[0]
            if (
                isinstance(name_arg, ast.Constant)
                and isinstance(name_arg.value, str)
                and len(name_arg.value) > max_length
            ):
                too_long.append(f"{path.name}:{node.lineno}:{name_arg.value}")

    assert not too_long, f"PostgreSQL identifiers exceed {max_length} chars: {too_long}"


def test_every_model_module_is_registered_once():
    """The Alembic/ORM registry must not miss or duplicate a model table."""
    import ast

    import app.models  # noqa: F401 -- populates the one declarative registry
    from app.db.database import Base

    declarations: dict[str, list[str]] = {}
    for path in MODELS_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Name) and target.id == "__tablename__"
                    for target in statement.targets
                ):
                    continue
                if isinstance(statement.value, ast.Constant) and isinstance(
                    statement.value.value, str
                ):
                    declarations.setdefault(statement.value.value, []).append(
                        f"{path.name}:{node.name}"
                    )

    duplicates = {
        table: owners for table, owners in declarations.items() if len(owners) > 1
    }
    unregistered = sorted(set(declarations) - set(Base.metadata.tables))
    assert not duplicates, f"Model tables have duplicate owners: {duplicates}"
    assert not unregistered, (
        f"Model tables missing from app.models registry: {unregistered}"
    )


def test_release_migration_columns_match_orm_registry():
    """Statically align 0029+ created/added columns with canonical ORM tables."""
    import ast

    import app.models  # noqa: F401 -- populates the one declarative registry
    from app.db.database import Base

    created_tables: dict[str, set[str]] = {}
    added_columns: list[tuple[str, str, str]] = []
    release_paths = sorted(VERSIONS_DIR.glob("00*.py"))
    release_paths = [path for path in release_paths if int(path.name[:4]) >= 29]

    for path in release_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        upgrade = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
            ),
            None,
        )
        assert upgrade is not None, f"Migration has no upgrade(): {path.name}"
        for node in ast.walk(upgrade):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr == "create_table" and node.args:
                table_arg = node.args[0]
                if not (
                    isinstance(table_arg, ast.Constant)
                    and isinstance(table_arg.value, str)
                ):
                    continue
                columns = {
                    argument.args[0].value
                    for argument in node.args[1:]
                    if isinstance(argument, ast.Call)
                    and isinstance(argument.func, ast.Attribute)
                    and argument.func.attr == "Column"
                    and argument.args
                    and isinstance(argument.args[0], ast.Constant)
                    and isinstance(argument.args[0].value, str)
                }
                assert table_arg.value not in created_tables, (
                    f"Release migrations create {table_arg.value} more than once"
                )
                created_tables[table_arg.value] = columns
            elif node.func.attr == "add_column" and len(node.args) >= 2:
                table_arg, column_call = node.args[:2]
                if not (
                    isinstance(table_arg, ast.Constant)
                    and isinstance(table_arg.value, str)
                    and isinstance(column_call, ast.Call)
                    and isinstance(column_call.func, ast.Attribute)
                    and column_call.func.attr == "Column"
                    and column_call.args
                    and isinstance(column_call.args[0], ast.Constant)
                    and isinstance(column_call.args[0].value, str)
                ):
                    continue
                added_columns.append(
                    (table_arg.value, column_call.args[0].value, path.name)
                )

    for table_name, column_name, _migration_name in added_columns:
        if table_name in created_tables:
            created_tables[table_name].add(column_name)

    for table_name, migrated_columns in created_tables.items():
        assert table_name in Base.metadata.tables, (
            f"Migration-created table missing from ORM registry: {table_name}"
        )
        orm_columns = set(Base.metadata.tables[table_name].columns.keys())
        assert migrated_columns == orm_columns, (
            f"Migration/ORM column mismatch for {table_name}: "
            f"migration_only={sorted(migrated_columns - orm_columns)}, "
            f"orm_only={sorted(orm_columns - migrated_columns)}"
        )

    for table_name, column_name, migration_name in added_columns:
        assert table_name in Base.metadata.tables, (
            f"{migration_name} adds a column to unregistered table {table_name}"
        )
        assert column_name in Base.metadata.tables[table_name].columns, (
            f"{migration_name} adds {table_name}.{column_name} but ORM omits it"
        )


def test_alembic_upgrade_head_on_fresh_postgres(fresh_pg_db, monkeypatch):
    """Install the release schema in a virgin PostgreSQL database."""
    from sqlalchemy import Float, create_engine, inspect
    from sqlalchemy.dialects.postgresql import JSONB

    from alembic import command

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)

    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    # Core tables that must exist after head.
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
        "interview_transcripts",
        "interview_qa",
        "mock_interview_runtime",
        "conversations",
        "conversation_messages",
        "conversation_turns",
        "job_opportunity_direction_links",
        "job_opportunity_merges",
        "conversation_deletion_receipts",
        "artifact_resume_states",
        "career_profile_candidate_items",
        "gmail_observations",
        "gmail_observation_snapshots",
        "gmail_observation_review_cards",
        "pending_submissions",
        "persistent_tasks",
        "persistent_task_triggers",
        "notification_preferences",
        "agent_tool_calls",
        "agent_model_dispatches",
        "agent_task_skill_bindings",
        "user_skill_resources",
        "gmail_integration_accounts",
        "gmail_oauth_states",
        "external_plugin_accounts",
        "external_plugin_oauth_states",
        "agent_memory_settings",
        "long_term_agent_memories",
        "long_term_agent_memory_sources",
        "memory_documents",
        "memory_ability_states",
        "memory_audit_logs",
        "resumes",
        "resume_sections",
    }
    missing = expected_tables - tables
    assert not missing, f"Missing tables after upgrade head: {missing}"

    # Operational structured values are JSONB, while all lifecycle timestamps
    # expose timezone-aware semantics at the database boundary.
    outbox_columns = {c["name"]: c for c in insp.get_columns("outbox_jobs")}
    turn_columns = {c["name"]: c for c in insp.get_columns("conversation_turns")}
    user_columns = {c["name"]: c for c in insp.get_columns("users")}
    conversation_columns = {c["name"]: c for c in insp.get_columns("conversations")}
    runtime_columns = {c["name"]: c for c in insp.get_columns("mock_interview_runtime")}
    record_columns = {c["name"]: c for c in insp.get_columns("interview_records")}
    qa_columns = {c["name"]: c for c in insp.get_columns("interview_qa")}
    ability_columns = {c["name"]: c for c in insp.get_columns("memory_ability_states")}
    chunk_columns = {c["name"]: c for c in insp.get_columns("document_chunks")}
    gmail_state_columns = {c["name"]: c for c in insp.get_columns("gmail_oauth_states")}
    event_columns = {c["name"]: c for c in insp.get_columns("process_events")}
    assert isinstance(outbox_columns["payload_json"]["type"], JSONB)
    assert isinstance(event_columns["analysis_context_json"]["type"], JSONB)
    assert isinstance(turn_columns["budget_json"]["type"], JSONB)
    assert isinstance(turn_columns["question_indexes_json"]["type"], JSONB)
    assert isinstance(turn_columns["tool_snapshot_json"]["type"], JSONB)
    assert isinstance(turn_columns["loaded_tool_schemas_json"]["type"], JSONB)
    assert "capability_snapshot_json" not in turn_columns
    assert "loaded_schemas_json" not in turn_columns
    assert "global_memory_enabled" not in user_columns
    assert "global_memory_enabled" not in conversation_columns
    assert user_columns["created_at"]["type"].timezone is True
    assert runtime_columns["answer_claimed_at"]["type"].timezone is True
    assert isinstance(runtime_columns["plan_json"]["type"], JSONB)
    assert runtime_columns["plan_json"]["nullable"] is False
    assert runtime_columns["current_stage_key"]["nullable"] is False
    assert runtime_columns["current_question_message_id"]["nullable"] is False
    assert runtime_columns["target_question_count"]["nullable"] is False
    assert set(runtime_columns) == {
        "interview_record_id",
        "user_id",
        "conversation_id",
        "plan_json",
        "interviewer_style",
        "target_question_count",
        "current_stage_key",
        "current_question_message_id",
        "answer_claimed_at",
        "last_activity_at",
    }
    assert isinstance(qa_columns["score"]["type"], Float)
    assert isinstance(ability_columns["ability_score"]["type"], Float)
    assert chunk_columns["document_id"]["nullable"] is False
    assert "lexical_index_id" not in chunk_columns
    assert "gmail_oauth_credentials" not in tables
    assert gmail_state_columns["code_verifier_ciphertext"]["nullable"] is False
    assert "code_verifier" not in gmail_state_columns
    assert "interview_plan" not in record_columns
    assert "debrief_summary" not in record_columns

    # Retired schemas must not leak back into the release baseline.
    legacy = {
        "interviews",
        "transcripts",
        "analysis_results",
        "interview_states",
        "memory_items",
        "agent_runs",
        "agent_steps",
        "mock_interview_sessions",
        "conversation_capability_states",
        "agent_checkpoints",
        "session_tasks",
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
    """The release baseline contains the composite indexes used by hot queries."""
    from sqlalchemy import create_engine, inspect

    from alembic import command

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)

    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    insp = inspect(engine)

    expectations = {
        "conversations": "ix_conversations_user_type_arch",
        "knowledge_documents": "ix_knowledge_docs_user_category",
        "file_assets": "ix_file_assets_user_purpose",
        "interview_qa": "ix_interview_qa_record_order",
    }
    for table, ix_name in expectations.items():
        names = {ix["name"] for ix in insp.get_indexes(table)}
        assert ix_name in names, (
            f"{table} missing composite index {ix_name}: have {names}"
        )

    engine.dispose()


def test_0004_preserves_legacy_json_and_utc_instants(fresh_pg_db, monkeypatch):
    """Upgrade real 0003-shaped values instead of validating only an empty DB."""
    from datetime import UTC, datetime

    from sqlalchemy import create_engine, text

    from alembic import command

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "0003")

    engine = create_engine(fresh_pg_db)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, hashed_password, email_verified, "
                "global_memory_enabled, created_at, updated_at) VALUES "
                "(1, 'legacy', 'x', FALSE, FALSE, "
                "'2026-08-05 10:30:00', '2026-08-05 10:30:00')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO outbox_jobs "
                "(id, user_id, job_type, payload_json, status, attempts, "
                "max_attempts, next_run_at, created_at, updated_at) VALUES "
                "('job_legacy', 1, 'test', '{\"items\":[1,2]}', 'pending', "
                "0, 3, '2026-08-05 10:30:00', "
                "'2026-08-05 10:30:00', '2026-08-05 10:30:00')"
            )
        )
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT payload_json, created_at FROM outbox_jobs "
                    "WHERE id = 'job_legacy'"
                )
            )
            .mappings()
            .one()
        )
    assert row["payload_json"] == {"items": [1, 2]}
    assert row["created_at"].astimezone(UTC) == datetime(2026, 8, 5, 10, 30, tzinfo=UTC)
    engine.dispose()


def test_interview_record_children_cascade(fresh_pg_db, monkeypatch):
    """The release baseline cascades interview child rows.

    Verify behaviourally (not just via inspector): insert one parent
    interview_records row + one interview_qa child + one
    mock_interview_runtime child, delete the parent, and assert
    that both children disappear without any IntegrityError. Without
    the cascade, the parent delete would either raise or leave
    orphan children — both are regressions worth pinning.
    """
    from sqlalchemy import create_engine, text

    from alembic import command

    monkeypatch.setenv("DATABASE_URL", fresh_pg_db)
    cfg = _make_alembic_config(fresh_pg_db)
    command.upgrade(cfg, "head")

    engine = create_engine(fresh_pg_db)
    with engine.begin() as conn:
        # Both mock_interview_runtime.user_id and interview_records.user_id are
        # integer users.id FKs (CLEANUP #2), so seed a users row and reference
        # its id (1) from both child inserts.
        conn.execute(
            text(
                "INSERT INTO users "
                "(id, username, hashed_password, email_verified, "
                "created_at, updated_at) "
                "VALUES (1, 'alice', 'x', FALSE, NOW(), NOW())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO interview_records "
                "(id, user_id, source, status, analysis_schema_version, "
                "analyzed_qa_count, created_at, updated_at) "
                "VALUES ('ir_cascade', 1, 'upload', 'completed', 1, 0, NOW(), NOW())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO interview_qa "
                "(id, record_id, order_idx, phase, question, answer, "
                "is_follow_up, follow_up_depth, answer_input_mode, created_at) "
                "VALUES ('qa_x', 'ir_cascade', 0, 'general', 'q?', 'a.', "
                "FALSE, 0, 'text', NOW())"
            )
        )
        conn.execute(
            text(
                "INSERT INTO conversations "
                "(id, user_id, type, mode) "
                "VALUES ('conv_cascade', 1, 'mock_interview', 'chat')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO mock_interview_runtime "
                "(user_id, interview_record_id, conversation_id, "
                "current_stage_key, current_question_message_id, plan_json, "
                "interviewer_style, target_question_count, last_activity_at) "
                "VALUES (1, 'ir_cascade', 'conv_cascade', "
                "'self_intro', 1, '[{\"key\": \"self_intro\"}]', "
                "'professional', 20, NOW())"
            )
        )

    # The parent delete must not raise or leave orphan rows.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM interview_records WHERE id = 'ir_cascade'"))

    with engine.connect() as conn:
        qa_left = conn.execute(
            text("SELECT count(*) FROM interview_qa WHERE record_id = 'ir_cascade'")
        ).scalar()
        runtime_left = conn.execute(
            text(
                "SELECT count(*) FROM mock_interview_runtime "
                "WHERE interview_record_id = 'ir_cascade'"
            )
        ).scalar()
    assert qa_left == 0, f"interview_qa not cascaded — {qa_left} orphan rows"
    assert runtime_left == 0, (
        f"mock_interview_runtime not cascaded — {runtime_left} orphan rows"
    )

    engine.dispose()
