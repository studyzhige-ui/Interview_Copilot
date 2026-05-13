"""测试 ORM 模型层的建表、CRUD 和关联查询。"""
import pytest
from datetime import datetime


def test_create_and_query_user(db_session):
    """User 模型：创建后应能通过 username 查询到。"""
    from app.models.user import User
    from app.core.security import get_password_hash

    user = User(
        username="orm_test_user",
        email="orm@test.com",
        hashed_password=get_password_hash("pass123")
    )
    db_session.add(user)
    db_session.flush()

    found = db_session.query(User).filter(User.username == "orm_test_user").first()
    assert found is not None
    assert found.email == "orm@test.com"
    assert found.is_active is True


def test_user_unique_username(db_session):
    """User 模型：重复 username 插入应报错。"""
    from app.models.user import User
    from sqlalchemy.exc import IntegrityError

    db_session.add(User(username="dup", hashed_password="h1"))
    db_session.flush()
    db_session.add(User(username="dup", hashed_password="h2"))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_chat_session_with_messages(db_session):
    """ChatSession + ChatMessage：ORM 外键关系应正确建立。"""
    from app.models.chat import ChatSession, ChatMessage

    session = ChatSession(id="sess-001", user_id="user1", title="测试会话")
    db_session.add(session)
    db_session.flush()

    msg1 = ChatMessage(session_id="sess-001", seq=1, role="User", content="你好")
    msg2 = ChatMessage(session_id="sess-001", seq=2, role="Agent", content="你好！有什么问题？")
    db_session.add_all([msg1, msg2])
    db_session.flush()

    # 通过 relationship 反查
    loaded = db_session.query(ChatSession).filter(ChatSession.id == "sess-001").first()
    assert len(loaded.messages) == 2
    assert loaded.messages[0].role == "User"
    assert loaded.messages[1].content == "你好！有什么问题？"


def test_interview_record_with_qa(db_session):
    """InterviewRecord + InterviewQA：unified schema 替换了旧的三表模型。"""
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord

    record = InterviewRecord(
        user_id="user1",
        source="upload",
        title="t",
        status="completed",
        transcript="面试官：你好\n候选人：你好",
        analysis_json='{"schema_version": 2, "overall": {"score": 8.5}}',
    )
    db_session.add(record)
    db_session.flush()

    qa1 = InterviewQA(
        record_id=record.id,
        order_idx=0,
        phase="technical",
        question="Q1",
        answer="A1",
        score=9,
    )
    qa2 = InterviewQA(
        record_id=record.id,
        order_idx=1,
        phase="technical",
        question="Q2",
        answer="A2",
        score=8,
    )
    db_session.add_all([qa1, qa2])
    db_session.flush()

    rows = (
        db_session.query(InterviewQA)
        .filter(InterviewQA.record_id == record.id)
        .order_by(InterviewQA.order_idx)
        .all()
    )
    assert len(rows) == 2
    assert rows[0].question == "Q1"


def test_interview_record_status_update(db_session):
    """InterviewRecord 状态机应支持更新。"""
    from app.models.interview_record import InterviewRecord

    record = InterviewRecord(user_id="u1", source="upload", status="pending")
    db_session.add(record)
    db_session.flush()

    record.status = "transcribing"
    db_session.flush()

    loaded = db_session.query(InterviewRecord).filter(InterviewRecord.id == record.id).first()
    assert loaded.status == "transcribing"
