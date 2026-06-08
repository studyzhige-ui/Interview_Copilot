"""MEM-SCHEMA tests: memory_document_service + memory_ability_state_service.

These are the additive v3 memory tables (memory_documents /
memory_ability_states / memory_audit_logs). The services open their own
``SessionLocal`` internally, so — like the other v3 memory tests — we run on a
dedicated in-memory engine and rebind every service's ``SessionLocal`` to it.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def engine_and_session():
    from app.db.database import Base
    import app.models.memory_ability_state  # noqa: F401
    import app.models.memory_audit_logs     # noqa: F401
    import app.models.memory_document       # noqa: F401
    import app.models.user                  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield engine, Session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def seeded(engine_and_session, monkeypatch):
    """Rebind service SessionLocals to the test engine and seed one user."""
    _engine, Session = engine_and_session
    import app.services.memory._db_helpers as helpers_mod
    import app.services.memory._memory_audit as audit_mod
    import app.services.memory.memory_ability_state_service as ability_mod
    import app.services.memory.memory_document_service as doc_mod
    for mod in (helpers_mod, audit_mod, ability_mod, doc_mod):
        monkeypatch.setattr(mod, "SessionLocal", Session, raising=False)

    from app.models.user import User
    s = Session()
    s.add(User(username="alice", hashed_password="x"))
    s.commit()
    s.close()
    return Session


def _audit_count(Session, **filters):
    from app.models.memory_audit_logs import MemoryAuditEntry
    s = Session()
    try:
        q = s.query(MemoryAuditEntry)
        for k, v in filters.items():
            q = q.filter(getattr(MemoryAuditEntry, k) == v)
        return q.count()
    finally:
        s.close()


# ── memory_document_service ──────────────────────────────────────────────


def test_document_apply_creates_and_appends(seeded):
    from app.services.memory import memory_document_service as svc

    r = svc.apply_patches(
        "alice", "user_profile",
        [{"op": "add", "new_line": "- 用户名：卷卷"}],
        change_type="patch_realtime",
    )
    assert r.applied == 1
    assert "卷卷" in svc.load("alice", "user_profile")
    assert svc.load_description("alice", "user_profile")  # one_liner populated

    svc.apply_patches(
        "alice", "user_profile",
        [{"op": "add", "new_line": "- 目标：后端岗位"}],
        change_type="patch_realtime",
    )
    body = svc.load("alice", "user_profile")
    assert "卷卷" in body and "后端" in body


def test_document_no_op_patch_does_not_create_row(seeded):
    from app.services.memory import memory_document_service as svc

    # update with no existing match_line → applied 0 → no row materialised.
    r = svc.apply_patches(
        "alice", "learning_strategy",
        [{"op": "update", "match_line": "- nope", "new_line": "- x"}],
        change_type="patch_realtime",
    )
    assert r.applied == 0
    assert svc.load("alice", "learning_strategy") == ""


def test_document_idempotency_key_skips_second_apply(seeded):
    from app.services.memory import memory_document_service as svc

    p = [{"op": "add", "new_line": "- 偏好：简洁回答"}]
    svc.apply_patches("alice", "user_profile", p, change_type="patch_realtime",
                      idempotency_key="job-1")
    r2 = svc.apply_patches("alice", "user_profile", p, change_type="patch_realtime",
                           idempotency_key="job-1")
    assert r2.applied == 0
    # Only one audit row carries the key.
    assert _audit_count(seeded, idempotency_key="job-1") == 1


def test_document_user_edit_overwrites_body(seeded):
    from app.services.memory import memory_document_service as svc

    svc.apply_patches("alice", "user_profile",
                      [{"op": "add", "new_line": "- a"}], change_type="patch_realtime")
    stored = svc.upsert_user_edit("alice", "user_profile", "- only this line")
    assert stored == "- only this line"
    assert svc.load("alice", "user_profile") == "- only this line"


def test_document_rejects_unknown_doc_type(seeded):
    from app.services.memory import memory_document_service as svc
    with pytest.raises(ValueError):
        svc.load("alice", "habit")


def test_document_unknown_user_raises(seeded):
    from app.services.memory import memory_document_service as svc
    with pytest.raises(svc.UnknownUser):
        svc.apply_patches("ghost", "user_profile",
                          [{"op": "add", "new_line": "- x"}], change_type="patch_realtime")


# ── memory_ability_state_service ─────────────────────────────────────────


def test_ability_upsert_creates_then_updates_in_place(seeded):
    from app.services.memory import memory_ability_state_service as svc

    row = svc.upsert(
        "alice", topic="Redis 缓存穿透", skill_type="knowledge_topic",
        mastery_level="weak", summary="不理解布隆过滤器", change_type="patch_realtime",
    )
    assert row is not None
    assert "Redis" in (row.search_text or "")
    assert len(svc.load_active("alice")) == 1

    # Same (topic, skill_type) updates the live row, not a duplicate.
    svc.upsert("alice", topic="Redis 缓存穿透", skill_type="knowledge_topic",
               mastery_level="improving", summary="理解了布隆过滤器",
               change_type="patch_dreaming")
    active = svc.load_active("alice")
    assert len(active) == 1
    assert active[0].mastery_level == "improving"


def test_ability_evidence_refs_serialised(seeded):
    from app.services.memory import memory_ability_state_service as svc
    row = svc.upsert(
        "alice", topic="MySQL 索引", skill_type="knowledge_topic",
        mastery_level="stable", summary="懂联合索引最左前缀",
        evidence_refs=[{"type": "interview_qa", "id": "qa_1"}],
        change_type="patch_realtime",
    )
    assert json.loads(row.evidence_refs_json) == [{"type": "interview_qa", "id": "qa_1"}]


def test_ability_list_by_mastery(seeded):
    from app.services.memory import memory_ability_state_service as svc
    svc.upsert("alice", topic="A", skill_type="behavioral", mastery_level="weak",
               summary="s", change_type="patch_realtime")
    svc.upsert("alice", topic="B", skill_type="behavioral", mastery_level="strong",
               summary="s", change_type="patch_realtime")
    weak = svc.list_by_mastery("alice", ("weak", "improving"))
    assert [r.topic for r in weak] == ["A"]


def test_ability_archive_then_reupsert_makes_new_active_row(seeded):
    from app.services.memory import memory_ability_state_service as svc
    from app.models.memory_ability_state import MemoryAbilityState

    svc.upsert("alice", topic="TCP", skill_type="knowledge_topic", mastery_level="weak",
               summary="s1", change_type="patch_realtime")
    assert svc.archive("alice", topic="TCP", skill_type="knowledge_topic") is True
    assert svc.load_active("alice") == []

    # Re-upsert after archive: a fresh active row (archived one stays as history).
    svc.upsert("alice", topic="TCP", skill_type="knowledge_topic", mastery_level="improving",
               summary="s2", change_type="patch_realtime")
    assert len(svc.load_active("alice")) == 1

    s = seeded()
    try:
        total = s.query(MemoryAbilityState).filter(MemoryAbilityState.topic == "TCP").count()
    finally:
        s.close()
    assert total == 2  # one archived + one active


def test_ability_idempotency_key_skips(seeded):
    from app.services.memory import memory_ability_state_service as svc
    svc.upsert("alice", topic="Kafka", skill_type="knowledge_topic", mastery_level="weak",
               summary="s", change_type="patch_realtime", idempotency_key="job-9")
    again = svc.upsert("alice", topic="Kafka", skill_type="knowledge_topic",
                       mastery_level="strong", summary="s2",
                       change_type="patch_realtime", idempotency_key="job-9")
    assert again is None
    assert svc.load_active("alice")[0].mastery_level == "weak"  # unchanged


def test_ability_rejects_invalid_enums(seeded):
    from app.services.memory import memory_ability_state_service as svc
    with pytest.raises(ValueError):
        svc.upsert("alice", topic="X", skill_type="bogus", mastery_level="weak",
                   summary="s", change_type="patch_realtime")
    with pytest.raises(ValueError):
        svc.upsert("alice", topic="X", skill_type="behavioral", mastery_level="bogus",
                   summary="s", change_type="patch_realtime")


def test_build_search_text():
    from app.services.memory import memory_ability_state_service as svc
    assert svc.build_search_text("Redis", "穿透") == "Redis\n穿透"
    assert svc.build_search_text("Redis", None) == "Redis"
