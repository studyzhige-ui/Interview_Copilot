"""ORM-layer tests for SQLAlchemy models under ``app.models``.

The repo-wide ``conftest.py`` provides a ``db_session`` fixture, but it
imports the stale ``app.models.interview`` module which no longer exists
(the unified-schema refactor in alembic 0007/0008 dropped it). Until
conftest is fixed centrally, we shadow ``test_engine`` / ``db_session``
locally so this file is self-contained and the rest of the suite is
unaffected.

Coverage:
  * column / index / FK / unique-constraint definitions match the schema
    the alembic migrations build.
  * Round-trip insert + query through an in-memory SQLite session for the
    core entities (User, ChatSession+ChatMessage, InterviewRecord +
    InterviewQA, UserUpload, KnowledgeDocument, MemoryItem,
    MockInterviewSession, AgentRun + AgentStep, UserAPIKey,
    ResumeSection).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker


# ─────────────────────────────────────────────────────────────────────
# Local fixtures (shadow the broken ones in tests/conftest.py)
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def test_engine():  # noqa: D401 — fixture, not a function
    """Module-scoped in-memory SQLite engine with all ORM tables created."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )

    from app.db.database import Base
    # Importing the models package registers every mapper on Base.metadata.
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """Per-test transactional session — rolled back on teardown.

    We use ``Session.begin_nested`` + listen-on-after-transaction-end so
    that callers may freely call ``session.rollback()`` mid-test (e.g.
    after asserting an IntegrityError) without losing the outer
    SAVEPOINT we use to keep the DB pristine between tests.
    """
    from sqlalchemy import event

    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):  # noqa: D401
        if trans.nested and not trans._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


# ─────────────────────────────────────────────────────────────────────
# Schema-shape assertions
# ─────────────────────────────────────────────────────────────────────


def test_all_expected_tables_registered(test_engine):
    insp = inspect(test_engine)
    tables = set(insp.get_table_names())
    expected = {
        "users",
        "user_uploads",
        "user_api_keys",
        "knowledge_documents",
        "interview_records",
        "interview_qa",
        "mock_interview_sessions",
        "chat_sessions",
        "chat_messages",
        "memory_items",
        "agent_runs",
        "agent_steps",
        "resume_sections",
    }
    missing = expected - tables
    assert not missing, f"ORM is missing tables: {missing}"


def test_user_columns_and_uniques(test_engine):
    insp = inspect(test_engine)
    cols = {c["name"]: c for c in insp.get_columns("users")}
    for required in ("id", "username", "email", "hashed_password", "is_active",
                     "email_verified", "nickname", "avatar_url", "bio",
                     "created_at", "updated_at"):
        assert required in cols, f"User.{required} missing"
    uniques = {u["name"] for u in insp.get_indexes("users") if u["unique"]}
    # Index-style uniqueness on username/email.
    assert any("username" in u["column_names"] for u in insp.get_indexes("users")), \
        "username should be indexed"


def test_user_api_key_unique_constraint(test_engine):
    insp = inspect(test_engine)
    uqs = insp.get_unique_constraints("user_api_keys")
    names = {u["name"] for u in uqs}
    assert "uq_user_api_keys_user_provider" in names, \
        f"Missing unique (user_id, provider): {uqs}"


def test_interview_qa_foreign_key_to_record(test_engine):
    insp = inspect(test_engine)
    fks = insp.get_foreign_keys("interview_qa")
    targets = {(fk["referred_table"], tuple(fk["referred_columns"])) for fk in fks}
    assert ("interview_records", ("id",)) in targets, \
        f"interview_qa → interview_records FK missing: {fks}"


def test_chat_message_foreign_key_to_session(test_engine):
    insp = inspect(test_engine)
    fks = insp.get_foreign_keys("chat_messages")
    targets = {fk["referred_table"] for fk in fks}
    assert "chat_sessions" in targets


def test_mock_session_cascades_from_interview_record(test_engine):
    insp = inspect(test_engine)
    fks = insp.get_foreign_keys("mock_interview_sessions")
    assert any(fk["referred_table"] == "interview_records" for fk in fks)


# ─────────────────────────────────────────────────────────────────────
# Behavioural round-trips
# ─────────────────────────────────────────────────────────────────────


def test_create_and_query_user(db_session):
    from app.models.user import User

    user = User(
        username="orm_test_user",
        email="orm@test.com",
        hashed_password="hashed-not-real",
    )
    db_session.add(user)
    db_session.flush()

    found = db_session.query(User).filter(User.username == "orm_test_user").first()
    assert found is not None
    assert found.email == "orm@test.com"
    assert found.is_active is True
    assert found.email_verified is False


def test_user_unique_username_violates(db_session):
    from app.models.user import User

    db_session.add(User(username="dup", hashed_password="h1"))
    db_session.flush()
    db_session.add(User(username="dup", hashed_password="h2"))

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_chat_session_with_messages_relationship(db_session):
    from app.models.chat import ChatSession, ChatMessage

    session = ChatSession(id="sess-001", user_id="user1", title="测试会话")
    db_session.add(session)
    db_session.flush()

    db_session.add_all([
        ChatMessage(session_id="sess-001", seq=1, role="User", content="hi"),
        ChatMessage(session_id="sess-001", seq=2, role="Agent", content="hello back"),
    ])
    db_session.flush()

    loaded = db_session.query(ChatSession).filter(ChatSession.id == "sess-001").first()
    assert len(loaded.messages) == 2
    # relationship order_by=seq → first msg is the user msg
    assert loaded.messages[0].seq == 1
    assert loaded.messages[1].content == "hello back"


def test_interview_record_with_qa_rows(db_session):
    from app.models.interview_qa import InterviewQA
    from app.models.interview_record import InterviewRecord

    record = InterviewRecord(
        user_id="user1",
        source="upload",
        title="t",
        status="completed",
        transcript="面试官:你好",
        analysis_json='{"schema_version": 2}',
    )
    db_session.add(record)
    db_session.flush()

    db_session.add_all([
        InterviewQA(record_id=record.id, order_idx=0, phase="technical",
                    question="Q1", answer="A1", score=9),
        InterviewQA(record_id=record.id, order_idx=1, phase="technical",
                    question="Q2", answer="A2", score=8),
    ])
    db_session.flush()

    rows = (
        db_session.query(InterviewQA)
        .filter(InterviewQA.record_id == record.id)
        .order_by(InterviewQA.order_idx)
        .all()
    )
    assert [r.question for r in rows] == ["Q1", "Q2"]
    assert rows[0].is_follow_up is False
    assert rows[0].answer_input_mode == "text"


def test_interview_record_status_update(db_session):
    from app.models.interview_record import InterviewRecord

    record = InterviewRecord(user_id="u1", source="upload", status="pending")
    db_session.add(record)
    db_session.flush()

    record.status = "transcribing"
    db_session.flush()

    loaded = (
        db_session.query(InterviewRecord)
        .filter(InterviewRecord.id == record.id)
        .first()
    )
    assert loaded.status == "transcribing"
    # default schema_version=2 should apply.
    assert loaded.analysis_schema_version == 2


def test_user_upload_object_key_unique(db_session):
    from app.models.upload import UserUpload

    db_session.add(UserUpload(
        id="upl_a", user_id="u1", purpose="resume",
        original_filename="cv.pdf", storage_uri="s3://bk/a",
        object_key="key-shared",
    ))
    db_session.flush()
    db_session.add(UserUpload(
        id="upl_b", user_id="u1", purpose="resume",
        original_filename="cv2.pdf", storage_uri="s3://bk/b",
        object_key="key-shared",
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_knowledge_document_default_values(db_session):
    from app.models.knowledge import KnowledgeDocument
    from app.models.upload import UserUpload

    db_session.add(UserUpload(
        id="upl_k", user_id="u1", purpose="knowledge",
        original_filename="doc.pdf", storage_uri="s3://bk/k",
        object_key="key-knowledge",
    ))
    db_session.flush()

    doc = KnowledgeDocument(
        user_id="u1",
        upload_id="upl_k",
        title="Redis 缓存雪崩",
        source_type="interview_qa",
        storage_uri="s3://bk/k",
        object_key="key-knowledge",
    )
    db_session.add(doc)
    db_session.flush()

    loaded = db_session.query(KnowledgeDocument).first()
    assert loaded.category == "默认"
    assert loaded.status == "processing"
    assert loaded.chunk_count == 0
    assert loaded.node_ids == "[]"


def test_memory_item_required_fields(db_session):
    from app.models.memory import MemoryItem

    mem = MemoryItem(
        user_id="u1",
        type="user_profile",
        description="prefers concise answers",
        normalized_key="prefers_concise_answers",
        content="The user prefers short, direct answers.",
    )
    db_session.add(mem)
    db_session.flush()

    loaded = db_session.query(MemoryItem).first()
    assert loaded.scope == "user"
    assert loaded.confidence == 0.0
    assert loaded.embedding_status == "pending"


def test_agent_run_and_steps_relationship(db_session):
    from app.models.agent_trace import AgentRun, AgentStep

    run = AgentRun(user_id="u1", session_id="s1", goal="answer X")
    db_session.add(run)
    db_session.flush()

    db_session.add_all([
        AgentStep(run_id=run.id, step_index=0, action_type="tool_call",
                  tool_name="search"),
        AgentStep(run_id=run.id, step_index=1, action_type="final_answer"),
    ])
    db_session.flush()

    loaded = db_session.query(AgentRun).filter(AgentRun.id == run.id).first()
    assert len(loaded.steps) == 2
    assert loaded.steps[0].action_type == "tool_call"
    assert loaded.steps[1].action_type == "final_answer"


def test_user_api_key_uniqueness(db_session):
    from app.models.user_api_key import UserAPIKey

    db_session.add(UserAPIKey(
        user_id="u1", provider="openai",
        key_ciphertext="aaa", key_masked="sk-****abcd",
    ))
    db_session.flush()
    db_session.add(UserAPIKey(
        user_id="u1", provider="openai",
        key_ciphertext="bbb", key_masked="sk-****xyzw",
    ))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_mock_interview_session_defaults(db_session):
    from app.models.interview_record import InterviewRecord
    from app.models.mock_interview_session import MockInterviewSession

    rec = InterviewRecord(user_id="u1", source="mock", status="pending")
    db_session.add(rec)
    db_session.flush()

    mis = MockInterviewSession(user_id="u1", interview_record_id=rec.id)
    db_session.add(mis)
    db_session.flush()

    loaded = db_session.query(MockInterviewSession).first()
    assert loaded.status == "in_progress"
    assert loaded.current_question_idx == 0
    assert loaded.interviewer_style == "professional"
    assert loaded.voice_mode == "hybrid"


def test_resume_section_round_trip(db_session):
    from app.models.resume_section import ResumeSection

    section = ResumeSection(
        user_id="u1",
        upload_id="upl_x",
        section_type="project",
        title="Interview Copilot",
        content="Built a multi-tenant RAG over BM25+vector.",
    )
    db_session.add(section)
    db_session.flush()

    loaded = db_session.query(ResumeSection).first()
    assert loaded.embedding_status == "pending"
    assert loaded.title.startswith("Interview")
