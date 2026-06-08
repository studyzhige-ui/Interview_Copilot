"""Tests for the resumes entity business rules (RESUME-INTERVIEW)."""
from __future__ import annotations

import pytest

from app.models.user import User
from app.services.resume import resume_entity_service


def _user(db, username="alice") -> User:
    u = User(username=username, email=f"{username}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    return u


def _create(db, username="alice", **kw):
    return resume_entity_service.create_resume(db, user_id=username, **kw)


def test_first_resume_becomes_default(db_session):
    _user(db_session)
    r = _create(db_session, title="A", raw_text_snapshot="cv A")
    assert r.is_default is True
    assert r.parse_status == "ready"  # had text


def test_second_resume_keeps_existing_default(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")
    r2 = _create(db_session, title="B")
    assert r1.is_default is True
    assert r2.is_default is False


def test_second_with_make_default_moves_default(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")
    r2 = _create(db_session, title="B", make_default=True)
    db_session.refresh(r1)
    assert r1.is_default is False
    assert r2.is_default is True


def test_third_resume_raises_limit(db_session):
    _user(db_session)
    _create(db_session, title="A")
    _create(db_session, title="B")
    with pytest.raises(resume_entity_service.ResumeLimitError):
        _create(db_session, title="C")


def test_delete_default_auto_promotes_other(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")  # default
    r2 = _create(db_session, title="B")
    assert resume_entity_service.delete_resume(db_session, user_id="alice", resume_id=r1.id)
    db_session.refresh(r2)
    assert r2.is_default is True  # promoted
    # And only one active resume remains.
    assert len(resume_entity_service.list_resumes(db_session, user_id="alice")) == 1


def test_delete_non_default_keeps_default(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")  # default
    r2 = _create(db_session, title="B")
    assert resume_entity_service.delete_resume(db_session, user_id="alice", resume_id=r2.id)
    db_session.refresh(r1)
    assert r1.is_default is True


def test_delete_last_resume_leaves_none_default(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")
    assert resume_entity_service.delete_resume(db_session, user_id="alice", resume_id=r1.id)
    assert resume_entity_service.list_resumes(db_session, user_id="alice") == []


def test_set_default_switches(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")
    r2 = _create(db_session, title="B")
    resume_entity_service.set_default_resume(db_session, user_id="alice", resume_id=r2.id)
    db_session.refresh(r1)
    db_session.refresh(r2)
    assert r1.is_default is False
    assert r2.is_default is True


def test_replace_archives_old_and_inherits_default(db_session):
    _user(db_session)
    r1 = _create(db_session, title="A")  # default
    r2 = _create(db_session, title="B")
    new = resume_entity_service.replace_resume(
        db_session, user_id="alice", replaced_resume_id=r1.id, title="A2",
    )
    db_session.refresh(r1)
    assert r1.archived_at is not None
    assert new.is_default is True  # inherited from r1
    db_session.refresh(r2)
    assert r2.is_default is False
    # Still only two active (B + A2).
    active = resume_entity_service.list_resumes(db_session, user_id="alice")
    assert {r.title for r in active} == {"B", "A2"}


def test_ownership_isolation(db_session):
    _user(db_session, "alice")
    _user(db_session, "bob")
    r = _create(db_session, "alice", title="A")
    assert resume_entity_service.get_owned_resume(db_session, resume_id=r.id, user_id="bob") is None
    assert resume_entity_service.delete_resume(db_session, user_id="bob", resume_id=r.id) is False
