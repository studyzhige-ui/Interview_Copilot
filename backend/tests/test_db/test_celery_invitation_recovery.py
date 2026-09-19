"""Real PostgreSQL + Redis + Celery SIGKILL recovery, using offline model output."""

import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

from celery import Celery
import pytest
import redis

from app.db.types import utc_now
from app.models.agent_execution import AgentToolCall
from app.models.agent_interaction import AgentInteraction
from app.models.application_operation import ApplicationOperation
from app.models.conversation_turn import ConversationTurn
from app.models.interview_record import InterviewRecord
from app.models.job_opportunity import NextAction
from app.models.model_dispatch import AgentModelDispatch
from app.models.user import User
from app.schemas.interview_invitation import (
    FixtureInterviewInvitationInput,
    FactConfirmationResolution,
)
from app.career.application.fixture_invitation_adapter import (
    ingest_fixture_interview_invitation,
)
from app.services.chat import turn_executor
from app.services.chat.interaction_service import resolve_interaction
from tests.test_career.test_gmail_invitation_cutover import _proposal, _facts
from tests.test_db.test_budget_and_invitation_recovery_postgres import (
    database as database_fixture,
)
from tests.test_db.test_alembic_migrations import fresh_pg_db  # noqa: F401

database = database_fixture


def eventually(probe, *, process=None, log=None, timeout=35):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = probe()
        if result:
            return result
        if process is not None and process.poll() is not None:
            pytest.fail(
                f"Celery worker exited: {process.returncode}\n{Path(log).read_text()}"
            )
        time.sleep(0.1)
    pytest.fail(
        f"Timed out waiting for real Celery boundary\n{Path(log).read_text() if log else ''}"
    )


@pytest.mark.parametrize("origin", ["fixture", "gmail"])
@pytest.mark.parametrize("phase", ["waiting", "verifying", "committed"])
def test_celery_worker_kill_resumes_same_decision_and_turn(
    database, tmp_path, monkeypatch, origin, phase
):
    url, _, factory = database
    redis_url = os.environ.get(
        "TEST_REDIS_URL", os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
    try:
        client.ping()
    except redis.RedisError as exc:
        if os.environ.get("REQUIRE_TEST_POSTGRES") == "1":
            pytest.fail(f"Redis is mandatory for this recovery campaign: {exc}")
        pytest.skip("Redis required for real Celery recovery")
    queue = "ic-recovery-test-" + uuid4().hex
    sender = Celery("isolated-test-sender", broker=redis_url)
    sender.conf.broker_transport_options = {"global_keyprefix": queue + ":"}
    monkeypatch.setattr(turn_executor, "SessionLocal", factory)
    monkeypatch.setattr(
        turn_executor,
        "schedule_turn",
        lambda turn_id: sender.send_task(
            "tasks.process_conversation_turn", args=[turn_id], queue=queue
        ),
    )
    monkeypatch.setattr(turn_executor.settings, "TURN_STALE_SECONDS", 60)
    with factory() as db:
        if origin == "gmail":
            user, _, _, proposal = _proposal(db)
            handoff = proposal.invitation_handoff
            turn_id, interaction_id = handoff["turn_id"], handoff["interaction_id"]
        else:
            user = User(username="fixture-worker-owner", hashed_password="x")
            db.add(user)
            db.commit()
            result = ingest_fixture_interview_invitation(
                db,
                user_pk=user.id,
                command=FixtureInterviewInvitationInput(
                    idempotency_key="worker-invitation",
                    source_identity="offline-fixture",
                    source_version="1",
                    observed_at=utc_now(),
                    raw_payload={"subject": "Synthetic invitation"},
                    extracted_facts=_facts().model_dump(),
                    extractor_version="test@1",
                ),
            )
            turn_id, interaction_id = result.turn_id, result.interaction.id
        user_id = user.id
        db.commit()

    def resolve_saved_decision():
        with factory() as db:
            interaction = db.get(AgentInteraction, interaction_id)
            resolve_interaction(
                db,
                interaction_id=interaction.id,
                user_id=user_id,
                expected_version=interaction.version,
                status="resolved",
                resolution=FactConfirmationResolution(
                    decision="correct_and_confirm",
                    corrected_facts=_facts(),
                    opportunity={"kind": "create_new"},
                ),
                resolution_identity="original-user-decision",
            )
            turn_executor.resume_waiting_turn(db, turn_id=turn_id, user_id=user_id)
            db.commit()

    boundary = tmp_path / "boundary"
    env = dict(
        os.environ,
        DATABASE_URL=url,
        REDIS_URL=redis_url,
        SECRET_KEY="isolated-worker-test-secret-not-production",
        DEEPSEEK_API_KEY="test-key-not-real",
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        IC_CELERY_TEST_CONFIG=str(tmp_path / "config.json"),
    )
    workers = []
    handles = []

    def start(stage):
        Path(env["IC_CELERY_TEST_CONFIG"]).write_text(
            json.dumps({"phase": stage, "queue": queue, "boundary_file": str(boundary)})
        )
        log = tmp_path / f"{stage or 'recovered'}.log"
        output = log.open("w")
        handles.append(output)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "tests.test_db.celery_recovery_host:celery_app",
                "worker",
                "--pool=solo",
                "--concurrency=1",
                "--queues",
                queue,
                "--hostname",
                queue,
                "--loglevel=WARNING",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
            ],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        workers.append(process)
        return process, log

    try:
        if phase != "waiting":
            resolve_saved_decision()
        worker, log = start(phase)
        if phase == "waiting":
            eventually(lambda: "[queues]" in log.read_text(), process=worker, log=log)
        else:
            sender.send_task(
                "tasks.process_conversation_turn", args=[turn_id], queue=queue
            )
            eventually(boundary.exists, process=worker, log=log)
        worker.kill()
        worker.wait(timeout=10)
        assert worker.returncode == -signal.SIGKILL
        with factory() as db:
            assert db.query(InterviewRecord).count() == int(phase == "committed")
            decision = db.get(AgentInteraction, interaction_id)
            assert decision.status == ("pending" if phase == "waiting" else "resolved")
        if phase == "waiting":
            resolve_saved_decision()
        else:
            with factory() as db:
                turn = db.get(ConversationTurn, turn_id)
                turn.heartbeat_at = utc_now() - timedelta(minutes=5)
                db.commit()
            assert asyncio.run(turn_executor.fail_orphaned_turns()) == 0
        recovered, log = start(None)
        sender.send_task("tasks.process_conversation_turn", args=[turn_id], queue=queue)

        def finished():
            with factory() as db:
                turn = db.get(ConversationTurn, turn_id)
                return (
                    turn.status
                    if turn.status in {"completed", "failed", "blocked", "cancelled"}
                    else None
                )

        assert eventually(finished, process=recovered, log=log) == "completed", (
            log.read_text()
        )
        # Deliberate duplicate broker delivery must be a no-op after success.
        sender.send_task("tasks.process_conversation_turn", args=[turn_id], queue=queue)
        time.sleep(0.3)
        with factory() as db:
            turn = db.get(ConversationTurn, turn_id)
            assert turn.recovery_attempts == int(phase != "waiting")
            assert turn.assistant_message_seq is not None
            assert (
                db.get(AgentInteraction, interaction_id).resolution_identity
                == "original-user-decision"
            )
            assert db.query(InterviewRecord).count() == 1
            assert db.query(NextAction).count() == 0
            assert (
                db.query(ApplicationOperation)
                .filter_by(operation_name="confirm_interview_invitation")
                .count()
                == 1
            )
            assert db.query(AgentToolCall).filter_by(turn_id=turn_id).count() == 1
            assert db.query(AgentModelDispatch).filter_by(turn_id=turn_id).count() == 1
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)
        for handle in handles:
            handle.close()
        sender.close()
        # Remove only this test's isolated broker namespace, never FLUSHDB.
        for key in client.scan_iter(match=queue + ":*", count=100):
            client.delete(key)
        client.close()
