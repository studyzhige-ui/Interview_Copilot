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


def test_interview_with_transcript_and_analysis(db_session):
    """Interview + Transcript + AnalysisResult：完整数据链路。"""
    from app.models.interview import Interview, Transcript, AnalysisResult

    interview = Interview(user_id="user1", status="PENDING", file_url="s3://bucket/test.wav")
    db_session.add(interview)
    db_session.flush()

    transcript = Transcript(
        interview_id=interview.id,
        content="面试官：你好\n候选人：你好",
        raw_text="raw text content"
    )
    db_session.add(transcript)

    analysis = AnalysisResult(
        interview_id=interview.id,
        score=8.5,
        feedback="回答不错",
        improved_answer='[{"question": "test"}]'
    )
    db_session.add(analysis)
    db_session.flush()

    # 验证关联
    loaded = db_session.query(Interview).filter(Interview.id == interview.id).first()
    assert len(loaded.transcripts) == 1
    assert loaded.analysis is not None
    assert loaded.analysis.score == 8.5


def test_interview_status_update(db_session):
    """Interview 状态机应支持更新。"""
    from app.models.interview import Interview

    interview = Interview(user_id="u1", status="PENDING")
    db_session.add(interview)
    db_session.flush()

    interview.status = "TRANSCRIBING"
    db_session.flush()

    loaded = db_session.query(Interview).filter(Interview.id == interview.id).first()
    assert loaded.status == "TRANSCRIBING"
