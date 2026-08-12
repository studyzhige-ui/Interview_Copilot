import json
from importlib import import_module

from app.models.interview_qa import InterviewQA
from app.models.interview_record import InterviewRecord
from app.models.user import User

module = import_module("app.services.interview.analysis_orchestrator")


def test_persist_analysis_keeps_zero_and_null_distinct(db_session, monkeypatch):
    user = User(username="analysis-owner", hashed_password="x")
    db_session.add(user)
    db_session.flush()
    record = InterviewRecord(
        id="ir_analysis_persist",
        user_id=user.id,
        source="mock",
        status="processing_review",
    )
    db_session.add(record)
    db_session.add_all(
        [
            InterviewQA(
                id="qa_score_zero",
                record_id=record.id,
                order_idx=0,
                phase="technical",
                question="Q1",
                answer="A1",
            ),
            InterviewQA(
                id="qa_unassessed",
                record_id=record.id,
                order_idx=1,
                phase="technical",
                question="Q2",
                answer="A2",
            ),
        ]
    )
    db_session.commit()
    monkeypatch.setattr(module, "SessionLocal", lambda: db_session)

    module.analysis_orchestrator._persist_analysis(
        record.id,
        {
            "overall": {
                "score": 0.0,
                "summary": "整体总结",
                "strengths": [],
                "weaknesses": ["回答错误"],
                "key_growth_areas": [],
            },
            "phase_summary": [],
            "skill_radar": {"基础知识": 0.0, "系统设计": None},
            "tag": "Python",
            "per_question": [
                {
                    "score": 0.0,
                    "critique": "回答错误",
                    "improved_answer": "改进回答",
                    "tags": ["基础知识"],
                    "phase": "technical",
                },
                {
                    "score": None,
                    "critique": "不是可评分问答",
                    "improved_answer": "",
                    "tags": [],
                    "phase": "technical",
                },
            ],
        },
    )

    rows = (
        db_session.query(InterviewQA)
        .filter(InterviewQA.record_id == record.id)
        .order_by(InterviewQA.order_idx)
        .all()
    )
    saved_record = db_session.get(InterviewRecord, record.id)
    saved_report = json.loads(saved_record.analysis_json)
    assert rows[0].score == 0.0
    assert rows[1].score is None
    assert json.loads(rows[0].key_points_json) == ["基础知识"]
    assert saved_report["schema_version"] == 3
    assert saved_report["skill_radar"]["系统设计"] is None
    assert saved_record.analysis_schema_version == 3
    assert saved_record.tag == "Python"
