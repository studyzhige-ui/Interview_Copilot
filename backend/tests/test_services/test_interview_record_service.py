import json

from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord


def test_create_for_upload(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_for_upload(
        user_id="alice",
        title="My Interview",
        audio_upload_id="upload_123",
        resume_text_snapshot="老的简历内容",
        db=db_session,
    )

    assert record.id.startswith("ir_")
    assert record.source == "upload"
    assert record.status == module.STATUS_PENDING
    assert record.user_id == "alice"
    assert record.resume_text_snapshot == "老的简历内容"

    rows = db_session.query(InterviewRecord).all()
    assert len(rows) == 1


def test_create_for_mock(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_for_mock(
        user_id="bob",
        title="模拟面试",
        interview_plan='{"phases": []}',
        db=db_session,
    )

    assert record.source == "mock"
    assert record.status == module.STATUS_PENDING
    assert record.interview_plan == '{"phases": []}'


def test_set_status_and_analysis(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_for_upload(user_id="alice", db=db_session)
    db_session.commit()

    service.set_transcript(record.id, transcript="Q: ...\nA: ...", db=db_session)
    service.set_analysis(record.id, {"schema_version": 2, "overall": {"score": 7.5}}, db=db_session)
    service.set_status(record.id, module.STATUS_COMPLETED, db=db_session)
    db_session.commit()

    refreshed = db_session.query(InterviewRecord).filter(InterviewRecord.id == record.id).first()
    assert refreshed.transcript == "Q: ...\nA: ..."
    assert refreshed.status == module.STATUS_COMPLETED
    assert refreshed.completed_at is not None
    parsed = json.loads(refreshed.analysis_json)
    assert parsed["overall"]["score"] == 7.5


def test_bulk_insert_qa_and_summary(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_for_upload(
        user_id="alice",
        resume_text_snapshot="resume",
        db=db_session,
    )
    db_session.commit()

    rows = service.bulk_insert_qa(
        record.id,
        [
            {"question": "What is Redis?", "answer": "in-memory KV", "phase": "technical"},
            {"question": "Explain TCP handshake", "answer": "SYN/ACK", "phase": "technical"},
        ],
        db=db_session,
    )
    db_session.commit()

    assert len(rows) == 2
    qa_rows = db_session.query(InterviewQA).filter(InterviewQA.record_id == record.id).all()
    assert {r.question for r in qa_rows} == {"What is Redis?", "Explain TCP handshake"}

    # Score one so the summary has something to show
    service.update_qa_analysis(
        rows[0].id, score=9, critique="ok", improved_answer="…", db=db_session,
    )
    service.set_analysis(
        record.id,
        {"schema_version": 2, "overall": {"score": 8, "summary": "Good"}},
        db=db_session,
    )
    db_session.commit()

    summary = service.get_analysis_summary(record.id, "alice")
    assert "8" in summary
    assert "Redis" in summary
    assert "TCP" in summary
