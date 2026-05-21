"""API tests for ``app.api.interview`` — upload, analyze, records.

The handlers are async and mostly call into Celery / S3 / RAG ingestion;
we patch those at the boundary and verify orchestration + DB side effects.

Like the other files in this directory, we build a local SQLite engine
because the shared ``db_session`` fixture in tests/conftest.py references
the missing ``app.models.interview`` module.
"""
from __future__ import annotations

from io import BytesIO
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import interview as interview_mod
from app.core.security import get_current_user
from app.db.database import Base, get_db
import app.models  # noqa: F401  — ensure mappers registered
from app.models.interview_record import InterviewRecord
from app.models.upload import UserUpload


@pytest.fixture
def db(monkeypatch) -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session_ = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session_()

    # Several interview endpoints (cancel, list, get, delete) call into
    # ``interview_record_service`` which opens its own ``SessionLocal()``
    # bound to the real configured DB. Redirect that to our test engine.
    import app.services.interview_record_service as irs_mod
    monkeypatch.setattr(irs_mod, "SessionLocal", Session_)

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    class FakeUser:
        username = "alice"

    def fake_user() -> FakeUser:
        return FakeUser()

    def fake_db() -> Iterator[Session]:
        yield db

    app = FastAPI()
    # Plug a slowapi limiter shim because @limiter.limit lives on a few
    # routes; rate_limit lib is already imported by app.api.interview's
    # dependency tree but no actual limit decorators are applied here.
    app.include_router(interview_mod.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_db] = fake_db
    return TestClient(app)


# ── /upload/audio/direct ──────────────────────────────────────────────────


def test_upload_audio_direct_rejects_bad_extension(client):
    """Server-side format guard fires before we touch storage."""
    resp = client.post(
        "/api/v1/upload/audio/direct",
        files={"file": ("note.txt", BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_audio_direct_writes_user_upload(client, db: Session):
    with patch(
        "app.api.interview.upload_file_to_owned_key",
        return_value="s3://bucket/uploads/alice/upl_x/clip.wav",
    ):
        resp = client.post(
            "/api/v1/upload/audio/direct",
            files={"file": ("clip.wav", BytesIO(b"RIFFxxxxWAVE"), "audio/wav")},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    upload_id = body["upload_id"]
    row = db.query(UserUpload).filter(UserUpload.id == upload_id).first()
    assert row is not None
    assert row.user_id == "alice"
    assert row.purpose == "interview_audio"
    assert row.status == "uploaded"


# ── /analyze ──────────────────────────────────────────────────────────────


def test_analyze_dispatches_celery_and_creates_record(client, db: Session):
    db.add_all([
        UserUpload(
            id="upl_audio",
            user_id="alice",
            purpose="interview_audio",
            original_filename="a.wav",
            storage_uri="s3://b/uploads/alice/upl_audio/a.wav",
            object_key="uploads/alice/upl_audio/a.wav",
            status="uploaded",
        ),
        UserUpload(
            id="upl_resume",
            user_id="alice",
            purpose="interview_resume",
            original_filename="r.pdf",
            storage_uri="s3://b/uploads/alice/upl_resume/r.pdf",
            object_key="uploads/alice/upl_resume/r.pdf",
            status="uploaded",
        ),
    ])
    db.commit()

    fake_task = MagicMock()
    fake_task.id = "celery-abc"
    with patch("app.api.interview.process_interview_analysis") as mock_proc, \
         patch("app.api.interview._extract_resume_snapshot", return_value="resume txt"):
        mock_proc.delay.return_value = fake_task
        resp = client.post(
            "/api/v1/analyze",
            json={
                "upload_id": "upl_audio",
                "resume_upload_id": "upl_resume",
                "jd_text": "looking for Redis expert",
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "processing"
    assert body["task_id"] == "celery-abc"
    assert body["record_id"].startswith("ir_")
    # Default language is "zh"; the task receives it as a kwarg so a
    # re-run can override it without breaking idempotency.
    mock_proc.delay.assert_called_once_with(body["record_id"], language="zh")

    record = db.query(InterviewRecord).filter(InterviewRecord.id == body["record_id"]).first()
    assert record is not None
    assert record.user_id == "alice"
    assert record.celery_task_id == "celery-abc"


def test_analyze_returns_404_for_missing_audio_upload(client, db: Session):
    db.add(
        UserUpload(
            id="upl_resume",
            user_id="alice",
            purpose="interview_resume",
            original_filename="r.pdf",
            storage_uri="s3://b/uploads/alice/upl_resume/r.pdf",
            object_key="uploads/alice/upl_resume/r.pdf",
            status="uploaded",
        ),
    )
    db.commit()
    resp = client.post(
        "/api/v1/analyze",
        json={"upload_id": "nope", "resume_upload_id": "upl_resume"},
    )
    assert resp.status_code == 404


def test_analyze_blocks_already_consumed_audio(client, db: Session):
    db.add_all([
        UserUpload(
            id="upl_audio",
            user_id="alice",
            purpose="interview_audio",
            original_filename="a.wav",
            storage_uri="s3://b/x",
            object_key="x",
            status="consumed",
        ),
        UserUpload(
            id="upl_resume",
            user_id="alice",
            purpose="interview_resume",
            original_filename="r.pdf",
            storage_uri="s3://b/y",
            object_key="y",
            status="uploaded",
        ),
    ])
    db.commit()
    resp = client.post(
        "/api/v1/analyze",
        json={"upload_id": "upl_audio", "resume_upload_id": "upl_resume"},
    )
    assert resp.status_code == 409


# ── /analyze/{record_id}/cancel ───────────────────────────────────────────


def test_cancel_analysis_revokes_celery_task(client, db: Session):
    record = InterviewRecord(
        id="ir_1",
        user_id="alice",
        source="upload",
        title="t",
        status="pending",
        celery_task_id="task-x",
    )
    db.add(record)
    db.commit()

    with patch("app.worker.celery_app.celery_app") as mock_celery:
        resp = client.post("/api/v1/analyze/ir_1/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["revoked"] is True
    mock_celery.control.revoke.assert_called_once()
    db.expire_all()
    assert db.get(InterviewRecord,"ir_1").status == "failed"


def test_cancel_analysis_404_for_other_user(client, db: Session):
    db.add(InterviewRecord(
        id="ir_bob", user_id="bob", source="upload", title="t", status="pending",
    ))
    db.commit()
    resp = client.post("/api/v1/analyze/ir_bob/cancel")
    assert resp.status_code == 404


# ── /memory/save ──────────────────────────────────────────────────────────


def test_save_personal_memory_calls_ingest(client):
    with patch("app.api.interview.ingest_text", new_callable=AsyncMock) as mock_ingest:
        resp = client.post(
            "/api/v1/memory/save",
            json={
                "question": "what is a distributed lock",
                "improved_answer": "use redlock or redisson",
                "original_score": 4.0,
                "tags": ["redis"],
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    mock_ingest.assert_awaited_once()
    kwargs = mock_ingest.await_args.kwargs
    assert kwargs["source_type"] == "personal_memory"
    assert kwargs["user_id"] == "alice"


# ── /analytics/report ─────────────────────────────────────────────────────


def test_analytics_report_delegates_to_service(client):
    fake = {"status": "success", "report": {"score": 4.2}}
    with patch(
        "app.api.interview.generate_comprehensive_report",
        new_callable=AsyncMock,
        return_value=fake,
    ) as mock_gen:
        resp = client.get("/api/v1/analytics/report", params={"limit": 10})
    assert resp.status_code == 200
    assert resp.json() == fake
    mock_gen.assert_awaited_once_with(10, user_id="alice")


# ── /interview-records (list / detail / patch / delete) ───────────────────


def test_list_interview_records_returns_user_records(client, db: Session):
    db.add_all([
        InterviewRecord(id="ir_a", user_id="alice", source="upload", title="A", status="completed"),
        InterviewRecord(id="ir_b", user_id="bob",   source="upload", title="B", status="completed"),
    ])
    db.commit()
    resp = client.get("/api/v1/interview-records")
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert ids == ["ir_a"]


def test_get_interview_record_404_for_other_user(client, db: Session):
    db.add(InterviewRecord(id="ir_b", user_id="bob", source="upload", title="B", status="completed"))
    db.commit()
    resp = client.get("/api/v1/interview-records/ir_b")
    assert resp.status_code == 404


def test_patch_interview_record_updates_title(client, db: Session):
    db.add(InterviewRecord(id="ir_a", user_id="alice", source="upload", title="old", status="completed"))
    db.commit()
    resp = client.patch("/api/v1/interview-records/ir_a", json={"title": "new title"})
    assert resp.status_code == 200
    db.expire_all()
    assert db.get(InterviewRecord,"ir_a").title == "new title"


def test_patch_interview_record_400_when_empty(client, db: Session):
    db.add(InterviewRecord(id="ir_a", user_id="alice", source="upload", title="old", status="completed"))
    db.commit()
    resp = client.patch("/api/v1/interview-records/ir_a", json={})
    assert resp.status_code == 400


def test_delete_interview_record_cascades_chat_sessions(client, db: Session):
    """Deleting an interview record nukes its chat sessions + messages too.

    The legacy detach mode (keep chats, NULL out interview_id) was removed —
    in practice it produced confusing orphan sessions, and the user expressed
    they wanted a clean wipe when removing an interview.
    """
    from app.models.chat import ChatMessage, ChatSession

    db.add(InterviewRecord(id="ir_a", user_id="alice", source="upload", title="t", status="completed"))
    db.add(ChatSession(
        id="cs_1", user_id="alice", title="debrief",
        session_type="debrief", interview_id="ir_a",
    ))
    db.add(ChatMessage(session_id="cs_1", seq=0, role="user", content="hi"))
    db.add(ChatMessage(session_id="cs_1", seq=1, role="assistant", content="hello"))
    db.commit()

    # The delete handler no longer touches Milvus (memory_items cascade
    # removed in v3 cleanup; ``_delete_milvus_doc_ids`` deleted with it).
    resp = client.delete("/api/v1/interview-records/ir_a")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["deleted_sessions"] == 1

    db.expire_all()
    assert db.get(InterviewRecord, "ir_a") is None
    assert db.get(ChatSession, "cs_1") is None
    assert db.query(ChatMessage).filter(ChatMessage.session_id == "cs_1").count() == 0
