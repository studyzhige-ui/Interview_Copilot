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
    import app.services.interview.interview_record_service as irs_mod
    monkeypatch.setattr(irs_mod, "SessionLocal", Session_)
    # The SSE events endpoint (interview_record_events_stream + the
    # _poll_record_snapshot helper) also opens its own SessionLocal()
    # per tick — same redirect needed.
    monkeypatch.setattr(interview_mod, "SessionLocal", Session_)

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


# ── /interview-records/{id}/events (SSE) ─────────────────────────────────


def test_events_stream_404_when_record_missing(client):
    """No row → 404 (before the SSE stream starts, so a normal HTTP
    error response, not an in-band 'error' event)."""
    resp = client.get("/api/v1/interview-records/missing/events")
    assert resp.status_code == 404


def test_events_stream_404_when_record_belongs_to_other_user(client, db: Session):
    """The owner check is on user_id, not just record_id — pinning
    that a record belonging to a different user looks identical to
    a missing record (no IDOR leakage)."""
    db.add(InterviewRecord(
        id="ir_other", user_id="bob", source="upload",
        status="analyzing", title="bob's record",
    ))
    db.commit()
    resp = client.get("/api/v1/interview-records/ir_other/events")
    assert resp.status_code == 404


def test_events_stream_emits_done_for_completed_record(client, db: Session):
    """When the record is already COMPLETED on the first poll, the
    stream yields one progress frame + one done frame, then closes.

    We use TestClient.stream() to consume the SSE response — the
    handler closes the generator after emitting ``done`` so the
    context manager exits cleanly without timing out."""
    import json as _json
    db.add(InterviewRecord(
        id="ir_done", user_id="alice", source="upload",
        status="completed", title="finished",
        analysis_json=_json.dumps({"overall": {"score": 88, "summary": "well done"}}),
        analyzed_qa_count=5,
    ))
    db.commit()

    with client.stream("GET", "/api/v1/interview-records/ir_done/events") as resp:
        assert resp.status_code == 200
        chunks = [line for line in resp.iter_lines() if line.startswith("data: ")]

    # One progress frame (the first tick reads status=completed) then
    # one done frame, then the generator returns.
    payloads = [_json.loads(line[len("data: "):]) for line in chunks]
    assert any(p["type"] == "progress" for p in payloads)
    done = next((p for p in payloads if p["type"] == "done"), None)
    assert done is not None, payloads
    assert done["status"] == "completed"
    assert done["analysis"]["score"] == 88
    assert done["analysis"]["summary"] == "well done"


def test_events_stream_emits_error_for_failed_record(client, db: Session):
    """failed status → in-band ``error`` event with the row's
    ``error_message``, then close. (Contrast with the 404 path,
    which fails synchronously before the stream starts.)"""
    import json as _json
    db.add(InterviewRecord(
        id="ir_failed", user_id="alice", source="upload",
        status="failed", title="bad upload",
        error_message="upload corrupted",
    ))
    db.commit()

    with client.stream("GET", "/api/v1/interview-records/ir_failed/events") as resp:
        assert resp.status_code == 200
        chunks = [line for line in resp.iter_lines() if line.startswith("data: ")]

    payloads = [_json.loads(line[len("data: "):]) for line in chunks]
    err = next((p for p in payloads if p["type"] == "error"), None)
    assert err is not None, payloads
    assert err["message"] == "upload corrupted"


def test_poll_record_snapshot_returns_none_for_missing_id(db: Session):
    """The poll helper must return None when the row disappears
    (the SSE loop maps None → 'record disappeared' error event)."""
    from app.api.interview import _poll_record_snapshot
    # ``db`` fixture didn't insert anything, so any id misses.
    assert _poll_record_snapshot("nothing-here") is None


def test_poll_record_snapshot_returns_plain_dict_not_orm_row(db: Session):
    """The helper must NOT return an ORM row — the SessionLocal
    closes immediately after the read, and any attempt to access
    a lazy-loaded attribute on a detached row would raise
    DetachedInstanceError. Returning a plain dict pins that
    contract so a future edit can't reintroduce the leak."""
    db.add(InterviewRecord(
        id="ir_snap", user_id="alice", source="upload",
        status="analyzing", title="snap test",
        analyzed_qa_count=3,
    ))
    db.commit()

    from app.api.interview import _poll_record_snapshot
    snap = _poll_record_snapshot("ir_snap")
    assert isinstance(snap, dict)
    assert snap["status"] == "analyzing"
    assert snap["analyzed_qa_count"] == 3
    # Whatever the snapshot returns must be safely usable without
    # a live session — assertable equality after the fixture-owned
    # session is no longer referenced anywhere in this test.
    assert snap["id"] == "ir_snap"
