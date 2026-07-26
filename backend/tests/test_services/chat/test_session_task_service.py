"""Tests for the session-scoped task CRUD layer."""

import pytest

from app.services.chat.session_task_service import (
    create_task,
    get_task,
    list_incomplete,
    list_tasks,
    record_verification,
    update_task,
)

SESSION_ID = "test-session-tasks-001"


@pytest.fixture(autouse=True)
def _seed_conversation(db_session):
    """Insert a parent conversation row so the FK constraint is satisfied."""
    from app.models.chat import Conversation

    db_session.add(
        Conversation(
            id=SESSION_ID,
            user_id="u1",
            title="task test",
        )
    )
    db_session.commit()


def test_create_task_assigns_incremental_ids(db_session):
    t1 = create_task(db_session, SESSION_ID, "First task")
    t2 = create_task(db_session, SESSION_ID, "Second task")
    assert t1["task_id"] == 1
    assert t2["task_id"] == 2
    assert t1["status"] == "pending"


def test_create_task_with_description(db_session):
    t = create_task(db_session, SESSION_ID, "Task", description="details here")
    assert t["description"] == "details here"


def test_get_task_found(db_session):
    create_task(db_session, SESSION_ID, "Findable")
    result = get_task(db_session, SESSION_ID, 1)
    assert result is not None
    assert result["subject"] == "Findable"


def test_get_task_not_found(db_session):
    assert get_task(db_session, SESSION_ID, 999) is None


def test_update_task_status(db_session):
    create_task(db_session, SESSION_ID, "Work")
    updated = update_task(db_session, SESSION_ID, 1, status="in_progress")
    assert updated["status"] == "in_progress"


def test_update_task_subject_and_description(db_session):
    create_task(db_session, SESSION_ID, "Old subject")
    updated = update_task(
        db_session,
        SESSION_ID,
        1,
        subject="New subject",
        description="New desc",
    )
    assert updated["subject"] == "New subject"
    assert updated["description"] == "New desc"


def test_update_task_invalid_status(db_session):
    create_task(db_session, SESSION_ID, "Work")
    result = update_task(db_session, SESSION_ID, 1, status="bogus")
    assert "error" in result


def test_update_task_not_found(db_session):
    assert update_task(db_session, SESSION_ID, 999, status="completed") is None


def test_list_tasks_ordered(db_session):
    create_task(db_session, SESSION_ID, "A")
    create_task(db_session, SESSION_ID, "B")
    create_task(db_session, SESSION_ID, "C")
    tasks = list_tasks(db_session, SESSION_ID)
    assert [t["task_id"] for t in tasks] == [1, 2, 3]


def test_list_tasks_empty(db_session):
    assert list_tasks(db_session, SESSION_ID) == []


def test_list_incomplete(db_session):
    create_task(db_session, SESSION_ID, "Done", acceptance_criteria="done")
    create_task(db_session, SESSION_ID, "Pending")
    create_task(db_session, SESSION_ID, "WIP")
    update_task(db_session, SESSION_ID, 1, status="verifying", evidence=["done output"])
    record_verification(db_session, SESSION_ID, 1, verdict="PASS", notes="verified")
    update_task(db_session, SESSION_ID, 3, status="in_progress")
    incomplete = list_incomplete(db_session, SESSION_ID)
    assert {t["task_id"] for t in incomplete} == {2, 3}


def test_dependency_blocks_start_until_prerequisite_is_verified(db_session):
    create_task(db_session, SESSION_ID, "First", acceptance_criteria="first done")
    create_task(
        db_session,
        SESSION_ID,
        "Second",
        blocked_by=[1],
        acceptance_criteria="second done",
    )
    blocked = update_task(db_session, SESSION_ID, 2, status="in_progress")
    assert blocked["error"] == "task_blocked"
    update_task(
        db_session, SESSION_ID, 1, status="verifying", evidence=["first output"]
    )
    record_verification(db_session, SESSION_ID, 1, verdict="PASS", notes="verified")
    assert (
        update_task(db_session, SESSION_ID, 2, status="in_progress")["status"]
        == "in_progress"
    )


def test_dependency_cycle_is_rejected(db_session):
    create_task(db_session, SESSION_ID, "First")
    create_task(db_session, SESSION_ID, "Second", blocked_by=[1])
    result = update_task(db_session, SESSION_ID, 1, blocked_by=[2])
    assert result["error"] == "task_dependency_cycle"


def test_task_ids_scoped_per_session(db_session):
    """Tasks in different sessions get independent id sequences."""
    other_session = "test-session-tasks-002"
    from app.models.chat import Conversation

    db_session.add(Conversation(id=other_session, user_id="u1", title="other"))
    db_session.commit()

    t1 = create_task(db_session, SESSION_ID, "Session 1 task")
    t2 = create_task(db_session, other_session, "Session 2 task")
    assert t1["task_id"] == 1
    assert t2["task_id"] == 1
