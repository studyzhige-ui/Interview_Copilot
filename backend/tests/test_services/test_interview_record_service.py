import json

from app.models.interview_record import InterviewRecord


def test_create_from_upload(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_from_upload(
        user_id="alice",
        title="My Interview",
        audio_upload_id="upload_123",
        transcript="Q: Hello\nA: Hi",
        analysis_json=json.dumps({"overall_score": 8}),
        db=db_session,
    )

    assert record.id.startswith("ir_")
    assert record.source == "upload"
    assert record.status == "ready"
    assert record.user_id == "alice"

    rows = db_session.query(InterviewRecord).all()
    assert len(rows) == 1


def test_create_from_mock(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_from_mock(
        user_id="bob",
        title="模拟面试",
        interview_plan='{"phases": []}',
        db=db_session,
    )

    assert record.source == "mock"
    assert record.status == "processing"
    assert record.interview_plan == '{"phases": []}'


def test_update_after_analysis(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    record = service.create_from_upload(
        user_id="alice",
        transcript="",
        analysis_json="",
        db=db_session,
    )
    assert record.status == "processing"

    updated = service.update_after_analysis(
        record.id,
        transcript="Q: ...\nA: ...",
        analysis_json=json.dumps({"overall_score": 7}),
        db=db_session,
    )
    assert updated.status == "ready"
    assert updated.transcript == "Q: ...\nA: ..."


def test_get_analysis_summary(db_session, monkeypatch):
    from app.services import interview_record_service as module

    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    service = module.InterviewRecordService()
    analysis = {
        "overall_score": 8,
        "overall_feedback": "Good performance",
        "qa_list": [
            {"question": "What is Redis?", "score": 9},
            {"question": "Explain TCP handshake", "score": 7},
        ],
    }
    record = service.create_from_upload(
        user_id="alice",
        analysis_json=json.dumps(analysis),
        db=db_session,
    )

    summary = service.get_analysis_summary(record.id, "alice")
    assert "8" in summary
    assert "Redis" in summary
    assert "TCP" in summary
