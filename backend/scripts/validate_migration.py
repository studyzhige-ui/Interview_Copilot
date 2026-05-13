"""Migration validation harness — runs alembic 0007/0008 against a sandboxed
SQLite DB stamped at 0006_chat_memory_cursor, then asserts the schema lines up.

Usage (from the backend/ directory):
    python scripts/validate_migration.py

What this validates
-------------------
1. 0007 creates the new tables (interview_qa, mock_interview_sessions) and
   adds the new columns to interview_records + chat_sessions.
2. 0008 migrates legacy interviews/transcripts/analysis_results triples into
   InterviewRecord + InterviewQA rows; mock-style analysis_json blobs with
   inline per_question / qa_history arrays get split into qa rows and pruned.
3. The three legacy tables are dropped at the end of 0008.

What this does NOT validate
---------------------------
Production runs against Postgres. SQLite's ALTER limitations would prevent
running from 0001 to head, so we sketch the minimal schema 0006 would have
produced and stamp at that revision. This is enough to exercise 0007+0008,
which is where all the new code lives.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

# Make `app.*` importable when run from the backend dir.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402


REPO_ROOT = BACKEND_DIR.parent


def _build_baseline_schema(engine) -> None:
    """Hand-roll the subset of pre-0007 schema we need: tables that 0007/0008
    will alter or read from. We stamp the DB at 0006 afterwards so alembic
    only runs 0007 and 0008."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE interview_records (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                source VARCHAR NOT NULL,
                title VARCHAR,
                tag VARCHAR(32),
                audio_upload_id VARCHAR,
                resume_upload_id VARCHAR,
                jd_upload_id VARCHAR,
                transcript TEXT,
                analysis_json TEXT,
                interview_plan TEXT,
                status VARCHAR NOT NULL DEFAULT 'processing',
                created_at DATETIME NOT NULL DEFAULT (datetime('now')),
                updated_at DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """))
        conn.execute(text("""
            CREATE TABLE chat_sessions (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                title VARCHAR,
                summary TEXT,
                session_type VARCHAR NOT NULL DEFAULT 'general',
                interview_id VARCHAR,
                session_state TEXT,
                compaction_cursor INTEGER DEFAULT 0,
                memory_extraction_cursor INTEGER NOT NULL DEFAULT 0,
                turn_count INTEGER DEFAULT 0,
                created_at DATETIME,
                updated_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id VARCHAR,
                status VARCHAR,
                task_id VARCHAR,
                upload_id VARCHAR,
                resume_upload_id VARCHAR,
                jd_text TEXT,
                file_url VARCHAR,
                created_at DATETIME
            )
        """))
        conn.execute(text("""
            CREATE TABLE transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER,
                content TEXT,
                raw_text TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE analysis_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER,
                score FLOAT,
                feedback TEXT,
                improved_answer TEXT
            )
        """))
        # alembic_version table, stamped at 0006
        conn.execute(text(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
        ))
        conn.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES ('0006_chat_memory_cursor')"
        ))


def _seed_legacy_rows(engine) -> dict[str, int]:
    """Insert a representative legacy upload triple + a mock-style record with
    inline qa_history so 0008's two migration branches both fire."""
    with engine.begin() as conn:
        # Legacy upload row triple
        conn.execute(text("""
            INSERT INTO interviews (id, user_id, status, task_id, upload_id, resume_upload_id, jd_text, file_url, created_at)
            VALUES (1, 'alice', 'COMPLETED', 'task-abc', 'upl_audio', 'upl_resume', 'JD text', 's3://bucket/file.mp3', datetime('now'))
        """))
        conn.execute(text("""
            INSERT INTO transcripts (id, interview_id, content, raw_text)
            VALUES (1, 1, 'Q: Hello\nA: Hi', 'raw text')
        """))
        per_q = [
            {"question": "Tell me about yourself", "answer": "I'm a backend dev", "score": 8, "feedback": "ok"},
            {"question": "Explain Redis", "answer": "in-memory KV", "score": 7, "feedback": "good"},
        ]
        conn.execute(
            text("""
                INSERT INTO analysis_results (id, interview_id, score, feedback, improved_answer)
                VALUES (1, 1, 7.5, 'overall good', :pq)
            """),
            {"pq": json.dumps(per_q, ensure_ascii=False)},
        )

        # A pre-existing mock InterviewRecord with inline qa_history we'll
        # split out into InterviewQA rows.
        mock_qa_history = [
            {"question": "How do you handle deadlocks?", "answer": "Use timeouts", "phase_id": "technical"},
            {"question": "Tell me about a conflict", "answer": "Stayed calm", "phase_id": "behavioral"},
        ]
        analysis = {
            "overall_score": 7.0,
            "overall_feedback": "decent",
            "strengths": ["clear"],
            "weaknesses": [],
            "improvement_suggestions": [],
            "qa_history": mock_qa_history,
            "per_question": [],
        }
        rec_id = f"ir_{uuid.uuid4().hex[:12]}"
        conn.execute(
            text("""
                INSERT INTO interview_records
                (id, user_id, source, title, status, analysis_json, interview_plan, created_at, updated_at)
                VALUES (:id, 'alice', 'mock', '模拟面试 fixture', 'ready', :a, '{"phases": []}', datetime('now'), datetime('now'))
            """),
            {"id": rec_id, "a": json.dumps(analysis, ensure_ascii=False)},
        )
    return {"legacy_interview_id": 1, "preexisting_record_count": 1}


def _run_migrations(db_url: str) -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


def _assert(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond:
        errors.append(msg)


def _inspect_results(engine, errors: list[str]) -> None:
    ins = inspect(engine)
    tables = set(ins.get_table_names())

    _assert("interview_qa" in tables, "interview_qa not created", errors)
    _assert("mock_interview_sessions" in tables, "mock_interview_sessions not created", errors)
    for legacy in ("interviews", "transcripts", "analysis_results"):
        _assert(legacy not in tables, f"legacy table {legacy} was not dropped", errors)

    ir_cols = {c["name"] for c in ins.get_columns("interview_records")}
    required = {
        "resume_text_snapshot",
        "jd_text_snapshot",
        "resume_structured_json",
        "jd_structured_json",
        "transcript_segments_json",
        "analysis_schema_version",
        "analyzed_qa_count",
        "celery_task_id",
        "error_message",
        "completed_at",
        "resume_doc_id",
    }
    missing = required - ir_cols
    _assert(not missing, f"interview_records missing cols: {sorted(missing)}", errors)

    chat_cols = {c["name"] for c in ins.get_columns("chat_sessions")}
    _assert("archived_at" in chat_cols, "chat_sessions.archived_at missing", errors)

    with engine.connect() as conn:
        # Legacy upload row should have been migrated
        legacy = conn.execute(text(
            "SELECT id, source, title, jd_text_snapshot, analyzed_qa_count "
            "FROM interview_records WHERE error_message = 'legacy:interview:1'"
        )).first()
        _assert(legacy is not None, "legacy interview row not migrated", errors)
        if legacy is not None:
            _assert(legacy.source == "upload", f"legacy row source != upload, got {legacy.source}", errors)
            _assert(legacy.jd_text_snapshot == "JD text", "jd snapshot not copied", errors)
            _assert(legacy.analyzed_qa_count == 2, f"qa_count != 2, got {legacy.analyzed_qa_count}", errors)

            qa_count = conn.execute(text(
                "SELECT COUNT(*) FROM interview_qa WHERE record_id = :r"
            ), {"r": legacy.id}).scalar()
            _assert(qa_count == 2, f"legacy qa rows != 2, got {qa_count}", errors)

        # Mock pre-existing row should have qa_history split into interview_qa
        mock_row = conn.execute(text(
            "SELECT id, analysis_json FROM interview_records "
            "WHERE source = 'mock' AND title = '模拟面试 fixture'"
        )).first()
        _assert(mock_row is not None, "mock fixture row missing", errors)
        if mock_row is not None:
            qa_rows = conn.execute(text(
                "SELECT order_idx, question, phase FROM interview_qa "
                "WHERE record_id = :r ORDER BY order_idx"
            ), {"r": mock_row.id}).all()
            _assert(len(qa_rows) == 2, f"mock qa rows != 2, got {len(qa_rows)}", errors)
            if len(qa_rows) == 2:
                _assert(qa_rows[0].phase == "technical", f"mock qa[0].phase = {qa_rows[0].phase}", errors)
                _assert("deadlocks" in (qa_rows[0].question or ""), "first qa question lost", errors)

            pruned = json.loads(mock_row.analysis_json)
            _assert(
                "qa_history" not in pruned and "per_question" not in pruned,
                "inline qa arrays not pruned from mock analysis_json",
                errors,
            )
            _assert(
                pruned.get("schema_version") == 2,
                f"analysis_schema_version not bumped to 2, got {pruned.get('schema_version')}",
                errors,
            )


def main() -> int:
    db_dir = tempfile.mkdtemp(prefix="mig_validate_")
    db_path = os.path.join(db_dir, "validate.db")
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url

    print(f"[1/4] Building baseline schema at {db_path}")
    engine = create_engine(db_url)
    _build_baseline_schema(engine)

    print("[2/4] Seeding legacy + mock fixtures")
    _seed_legacy_rows(engine)
    engine.dispose()

    print("[3/4] Running alembic upgrade head (0006 → 0007 → 0008)")
    _run_migrations(db_url)

    print("[4/4] Asserting post-migration schema and data")
    engine = create_engine(db_url)
    errors: list[str] = []
    _inspect_results(engine, errors)
    engine.dispose()

    if errors:
        print("\nFAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("\n✅ Migration validation passed.")
    print(f"   Sandbox left at: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
