"""Tests for app.services.interview.interview_record_service.

Local SQLite fixture — the shared conftest db_session fixture is broken
because it imports a removed ``app.models.interview`` module.
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def record_db_session():
    import app.models.interview_qa  # noqa: F401
    import app.models.interview_record  # noqa: F401
    import app.models.interview_transcript  # noqa: F401
    import app.models.user  # noqa: F401
    from app.db.database import Base
    from app.models.user import User

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # ``interview_records.user_id`` is now an integer FK to ``users.id``
    # (CLEANUP #2); the service resolves the caller's username → pk via
    # ``resolve_user_pk``, so the ``users`` table must exist here and carry
    # rows for the usernames these tests use. Transcripts now live in their
    # own ``interview_transcripts`` table (RESUME-INTERVIEW split).
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["interview_records"],
            Base.metadata.tables["interview_qa"],
            Base.metadata.tables["interview_transcripts"],
        ],
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    session.add_all([
        User(username="alice", hashed_password="x"),
        User(username="bob", hashed_password="x"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class _NoCloseSession:
    """Forward attribute access; turn close() into a flush so cross-call
    state survives even when the service opens its own SessionLocal()."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def close(self):
        try:
            self._inner.commit()
        except Exception:
            self._inner.rollback()


def test_create_for_upload(record_db_session, monkeypatch):
    from app.models.interview_record import InterviewRecord
    from app.models.user import User
    from app.services.interview import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(record_db_session))

    service = module.InterviewRecordService()
    record = service.create_for_upload(
        user_id="alice",
        title="My Interview",
        audio_file_asset_id="upload_123",
        resume_text_snapshot="老的简历内容",
        db=record_db_session,
    )

    assert record.id.startswith("ir_")
    assert record.source == "upload"
    assert record.status == module.STATUS_PENDING
    # The service resolves the "alice" principal to users.id and stores the
    # integer pk, not the username string.
    alice_pk = record_db_session.query(User.id).filter(User.username == "alice").scalar()
    assert record.user_id == alice_pk
    assert record.resume_text_snapshot == "老的简历内容"

    rows = record_db_session.query(InterviewRecord).all()
    assert len(rows) == 1


def test_create_for_mock(record_db_session, monkeypatch):
    from app.services.interview import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(record_db_session))

    service = module.InterviewRecordService()
    record = service.create_for_mock(
        user_id="bob",
        title="模拟面试",
        interview_plan='{"phases": []}',
        db=record_db_session,
    )

    assert record.source == "mock"
    assert record.status == module.STATUS_PENDING
    assert record.interview_plan == '{"phases": []}'


def test_set_status_set_transcript_set_analysis(record_db_session, monkeypatch):
    """Status / transcript / analysis writes should all be observable on reload."""
    from app.models.interview_record import InterviewRecord
    from app.services.interview import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(record_db_session))

    service = module.InterviewRecordService()
    record = service.create_for_upload(user_id="alice", db=record_db_session)
    record_db_session.commit()

    service.set_transcript(record.id, transcript="Q: ...\nA: ...", db=record_db_session)
    service.set_analysis(
        record.id,
        {"schema_version": 2, "overall": {"score": 7.5}},
        db=record_db_session,
    )
    service.set_status(record.id, module.STATUS_COMPLETED, db=record_db_session)
    record_db_session.commit()

    refreshed = (
        record_db_session.query(InterviewRecord)
        .filter(InterviewRecord.id == record.id)
        .first()
    )
    # Transcript now lives in interview_transcripts; the record points at it.
    assert refreshed.transcript_id is not None
    assert service.get_transcript_text(record.id, db=record_db_session) == "Q: ...\nA: ..."
    assert refreshed.status == module.STATUS_COMPLETED
    assert refreshed.completed_at is not None
    parsed = json.loads(refreshed.analysis_json)
    assert parsed["overall"]["score"] == 7.5


def test_bulk_insert_qa_and_summary(record_db_session, monkeypatch):
    from app.models.interview_qa import InterviewQA
    from app.services.interview import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(record_db_session))

    service = module.InterviewRecordService()
    record = service.create_for_upload(
        user_id="alice",
        resume_text_snapshot="resume",
        db=record_db_session,
    )
    record_db_session.commit()

    rows = service.bulk_insert_qa(
        record.id,
        [
            {"question": "What is Redis?", "answer": "in-memory KV", "phase": "technical"},
            {"question": "Explain TCP handshake", "answer": "SYN/ACK", "phase": "technical"},
        ],
        db=record_db_session,
    )
    record_db_session.commit()

    assert len(rows) == 2
    qa_rows = (
        record_db_session.query(InterviewQA)
        .filter(InterviewQA.record_id == record.id)
        .all()
    )
    assert {r.question for r in qa_rows} == {"What is Redis?", "Explain TCP handshake"}

    service.update_qa_analysis(
        rows[0].id, score=9, critique="ok", improved_answer="…", db=record_db_session,
    )
    service.set_analysis(
        record.id,
        {"schema_version": 2, "overall": {"score": 8, "summary": "Good"}},
        db=record_db_session,
    )
    record_db_session.commit()

    summary = service.get_analysis_summary(record.id, "alice")
    assert "8" in summary
    assert "Redis" in summary
    assert "TCP" in summary


def test_get_analysis_summary_returns_empty_for_unknown(record_db_session, monkeypatch):
    """Unknown record_id / wrong user → empty string, no exception."""
    from app.services.interview import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: _NoCloseSession(record_db_session))

    summary = module.InterviewRecordService().get_analysis_summary("ir_nope", "alice")
    assert summary == ""
