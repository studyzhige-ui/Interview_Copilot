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
    InterviewQA, UserUpload, KnowledgeDocument, MemoryDocument /
    MemoryAbilityState / MemoryAuditEntry (v3 memory),
    MockInterviewSession, UserModelCredential, ResumeSection).
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
        "file_assets",
        "outbox_jobs",
        "user_model_credentials",
        "user_model_provider_settings",
        "user_model_selections",
        "knowledge_documents",
        "document_chunks",
        "interview_records",
        "interview_qa",
        "mock_interview_sessions",
        "mock_interview_runtime",
        "chat_sessions",
        "chat_messages",
        "resumes",
        # MEMORY-V3 stores (old knowledge/strategy/habit/audit_log dropped in 0023)
        "memory_documents",
        "memory_ability_states",
        "memory_audit_logs",
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
    # Index-style uniqueness on username/email.
    assert any("username" in u["column_names"] for u in insp.get_indexes("users")), \
        "username should be indexed"


def test_user_model_credential_unique_constraint(test_engine):
    insp = inspect(test_engine)
    uqs = insp.get_unique_constraints("user_model_credentials")
    names = {u["name"] for u in uqs}
    assert "uq_user_model_credentials_user_provider" in names, \
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


def _make_user(db_session, username: str = "mem_user") -> int:
    """Seed a users row and return its integer PK (v3 memory tables key on
    ``users.id``)."""
    from app.models.user import User

    u = User(username=username, hashed_password="x")
    db_session.add(u)
    db_session.flush()
    return u.id


def test_memory_document_defaults_and_unique_per_doc_type(db_session):
    """v3 memory: ``memory_documents`` has one row per (user_id, doc_type)
    with denormalised ``one_liner``; the unique constraint blocks a second
    row of the same doc_type for the same user."""
    from sqlalchemy.exc import IntegrityError

    from app.models.memory_document import MemoryDocument

    uid = _make_user(db_session)

    doc = MemoryDocument(user_id=uid, doc_type="user_profile", body="- 目标：后端")
    db_session.add(doc)
    db_session.flush()

    loaded = db_session.query(MemoryDocument).first()
    assert loaded.doc_type == "user_profile"
    assert loaded.one_liner == ""          # default
    assert loaded.body == "- 目标：后端"
    assert loaded.id.startswith("mdoc_")   # generated id prefix

    # A different doc_type for the same user is allowed.
    db_session.add(MemoryDocument(user_id=uid, doc_type="learning_strategy", body="x"))
    db_session.flush()

    # But a duplicate (user_id, doc_type) violates the unique constraint.
    db_session.add(MemoryDocument(user_id=uid, doc_type="user_profile", body="dup"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_memory_ability_state_defaults_and_active_uniqueness(db_session):
    """``memory_ability_states`` defaults ``mastery_level='improving'`` and
    enforces ONE ACTIVE row per (user, topic, skill_type) via the partial
    unique index (archived rows are excluded, so re-adding after archive is
    allowed)."""
    from datetime import datetime

    from sqlalchemy.exc import IntegrityError

    from app.models.memory_ability_state import MemoryAbilityState

    uid = _make_user(db_session)

    s1 = MemoryAbilityState(user_id=uid, topic="Redis", skill_type="knowledge_topic")
    db_session.add(s1)
    db_session.flush()

    loaded = db_session.query(MemoryAbilityState).first()
    assert loaded.mastery_level == "improving"   # default
    assert loaded.archived_at is None
    assert loaded.id.startswith("mas_")

    # A second ACTIVE row for the same (user, topic, skill_type) is rejected.
    # NB: this flush raises, and the fixture rolls back to the SAVEPOINT —
    # which also discards ``s1``. So the archive-then-readd check below
    # re-seeds its own rows rather than relying on ``s1`` surviving.
    db_session.add(
        MemoryAbilityState(user_id=uid, topic="Redis", skill_type="knowledge_topic")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    # Seed a fresh live row, archive it, then re-add: the partial index
    # excludes the archived row, so a new active row for the same key is
    # allowed (history is preserved).
    uid2 = _make_user(db_session, username="mem_user_b")
    live = MemoryAbilityState(user_id=uid2, topic="TCP", skill_type="knowledge_topic")
    db_session.add(live)
    db_session.flush()
    live.archived_at = datetime.utcnow()
    db_session.flush()
    db_session.add(
        MemoryAbilityState(user_id=uid2, topic="TCP", skill_type="knowledge_topic",
                           mastery_level="weak")
    )
    db_session.flush()
    active = db_session.query(MemoryAbilityState).filter(
        MemoryAbilityState.topic == "TCP",
        MemoryAbilityState.archived_at.is_(None),
    ).all()
    assert len(active) == 1
    assert active[0].mastery_level == "weak"
    # Total TCP rows = 1 archived + 1 active.
    assert db_session.query(MemoryAbilityState).filter(
        MemoryAbilityState.topic == "TCP"
    ).count() == 2


def test_memory_audit_entry_round_trip_and_unique_idem_key(db_session):
    """``memory_audit_logs`` is append-only; the ``idempotency_key`` index is
    unique so a retried job can't double-write an audit row (NULL keys stay
    distinct)."""
    from sqlalchemy.exc import IntegrityError

    from app.models.memory_audit_logs import MemoryAuditEntry

    uid = _make_user(db_session)

    db_session.add_all([
        MemoryAuditEntry(user_id=uid, change_type="patch_realtime", doc_type="user_profile"),
        MemoryAuditEntry(user_id=uid, change_type="user_edit"),   # NULL idem key
        MemoryAuditEntry(user_id=uid, change_type="user_edit"),   # NULL idem key — allowed
    ])
    db_session.flush()
    assert db_session.query(MemoryAuditEntry).count() == 3

    db_session.add(
        MemoryAuditEntry(user_id=uid, change_type="patch_dreaming", idempotency_key="job-1")
    )
    db_session.flush()
    db_session.add(
        MemoryAuditEntry(user_id=uid, change_type="patch_dreaming", idempotency_key="job-1")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# test_agent_run_and_steps_relationship was removed in the audit
# cleanup — the agent_runs / agent_steps tables were dropped (see
# alembic 0008_drop_agent_trace) because LangSmith's wrap_openai
# instrumentation already captures every LLM call with full trace.


def test_user_model_credential_uniqueness(db_session):
    from app.models.user import User
    from app.models.user_model_credentials import UserModelCredential

    user = User(username="u1", email="u1@example.com", hashed_password="x")
    db_session.add(user)
    db_session.flush()

    db_session.add(UserModelCredential(
        user_id=user.id, provider="openai",
        key_ciphertext="aaa", key_masked="sk-****abcd",
    ))
    db_session.flush()
    db_session.add(UserModelCredential(
        user_id=user.id, provider="openai",
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
