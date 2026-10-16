"""Disposable PostgreSQL migration and real pgvector retrieval acceptance."""

import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "alembic.ini").is_file():
    ROOT = ROOT.parent


@pytest.fixture(scope="module")
def postgres():
    admin_url = os.environ.get("TEST_PG_ADMIN_URL")
    if not admin_url:
        if os.environ.get("REQUIRE_TEST_POSTGRES") == "1":
            pytest.fail("TEST_PG_ADMIN_URL is required")
        pytest.skip("explicit disposable PostgreSQL admin URL required")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    name = "contract_" + uuid.uuid4().hex
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    engine = create_engine(url)
    try:
        environment = {**os.environ, "DATABASE_URL": url}
        for args in (["upgrade", "head"], ["check"]):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_schema_has_version_bound_resume_spans_and_one_vector_repository(postgres):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(
        Config(str(ROOT / "alembic.ini"))
    ).get_current_head()
    with postgres.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar()
            == head
        )
        assert (
            connection.execute(
                text(
                    "select count(*) from information_schema.columns where table_name='artifact_resume_states' and column_name='section_spans_json'"
                )
            ).scalar()
            == 1
        )
        assert (
            connection.execute(
                text("select '[1,0]'::vector <=> '[1,0]'::vector")
            ).scalar()
            == 0
        )


def test_context_checkpoint_has_one_publisher_across_connections(postgres, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.conversation import context_store
    from app.models.chat import Conversation
    from app.models.user import User

    sessions = sessionmaker(postgres, expire_on_commit=False)
    with sessions.begin() as db:
        owner = User(
            username="checkpoint-" + uuid.uuid4().hex, hashed_password="unused"
        )
        db.add(owner)
        db.flush()
        conversation = Conversation(user_id=owner.id)
        db.add(conversation)
        db.flush()
        conversation_id = conversation.id
    monkeypatch.setattr(context_store, "SessionLocal", sessions)
    ready = Barrier(2)

    def publish(value):
        ready.wait(timeout=5)
        return context_store.save(
            conversation_id,
            expected_version=0,
            through_seq=2,
            state={"messages": [{"role": "user", "content": value}]},
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(publish, ["writer-one", "writer-two"]))
    assert sum(result is not None for result in results) == 1
    restored = context_store.load(conversation_id)
    assert restored["version"] == 1 and restored["through_seq"] == 2
    assert restored["state"] == next(result["state"] for result in results if result)


def test_preference_generated_identity_can_be_persisted_in_postgres(postgres):
    from app.models.user import User
    from app.career.application.personalization import replace_copilot_preference
    from app.schemas.personalization import CopilotPreferenceUpdate

    with sessionmaker(postgres).begin() as db:
        user = User(username="preference-" + uuid.uuid4().hex, hashed_password="unused")
        db.add(user)
        db.flush()
        preference = replace_copilot_preference(
            db,
            user_pk=user.id,
            command=CopilotPreferenceUpdate(
                expected_version=0, instructions=["Explain assumptions."]
            ),
        )
        assert len(preference.id) == 37 and preference.version == 1


def test_memory_source_claim_is_exclusive_across_postgres_connections(
    postgres, monkeypatch
):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Event
    from app.db.types import utc_now
    from app.memory import consolidation
    from app.models.user import User
    from app.models.chat import Conversation, ConversationMessage
    from app.models.conversation_turn import ConversationTurn
    from app.models.long_term_memory import AgentMemorySetting
    from app.models.memory_pipeline import MemoryExtraction

    factory = sessionmaker(postgres)
    identity = str(uuid.uuid4())
    with factory.begin() as db:
        user = User(username=identity, hashed_password="unused")
        db.add(user)
        db.flush()
        owner = user.id
        db.add_all(
            [
                Conversation(id=identity, user_id=owner),
                AgentMemorySetting(user_id=owner, contribution_enabled=True),
            ]
        )
        db.flush()
        db.add_all(
            [
                ConversationMessage(
                    conversation_id=identity,
                    seq=1,
                    role="User",
                    content="比较表帮助看清取舍。",
                ),
                ConversationMessage(
                    conversation_id=identity, seq=2, role="Assistant", content="收到。"
                ),
                ConversationTurn(
                    id=identity,
                    conversation_id=identity,
                    user_id=owner,
                    mode="agent",
                    message="比较表帮助看清取舍。",
                    status="completed",
                    user_message_seq=1,
                    assistant_message_seq=2,
                    completed_at=utc_now() - timedelta(hours=1),
                ),
            ]
        )
    entered, release = Event(), Event()
    calls = []

    async def model(*_):
        calls.append(identity)
        entered.set()
        assert await asyncio.to_thread(release.wait, 10)
        return {"summary": "", "candidates": []}

    monkeypatch.setattr(consolidation, "SessionLocal", factory)
    monkeypatch.setattr(consolidation, "model_json", model)
    monkeypatch.setattr(consolidation.settings, "AGENT_MEMORY_PRODUCER_ENABLED", True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(lambda: asyncio.run(consolidation.extract_turn(identity)))
        try:
            assert entered.wait(10)
            second = pool.submit(
                lambda: asyncio.run(consolidation.extract_turn(identity))
            )
            assert second.result(timeout=5) is None
        finally:
            release.set()
        assert first.result(timeout=10) == owner
    assert calls == [identity]
    with factory() as db:
        row = db.get(MemoryExtraction, identity)
        assert (
            row.status == "no_output" and row.attempts == 1 and row.lease_token is None
        )


def test_refresh_ticket_has_one_winner_across_database_sessions(postgres):
    from concurrent.futures import ThreadPoolExecutor
    import time
    from app.core.token_blacklist import consume

    sessions = sessionmaker(postgres)
    jti = uuid.uuid4().hex

    def rotate():
        with sessions.begin() as db:
            return consume(db, jti, time.time() + 60)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: rotate(), range(2))) == [False, True]


def test_token_pruning_counts_only_expired_rows(postgres):
    import time
    from app.core.token_blacklist import consume, is_revoked, prune_expired

    expired, current = uuid.uuid4().hex, uuid.uuid4().hex
    with sessionmaker(postgres).begin() as db:
        assert consume(db, expired, time.time() - 60)
        assert consume(db, current, time.time() + 60)
        assert prune_expired(db) == 1
        assert not is_revoked(db, expired)
        assert is_revoked(db, current)
        assert prune_expired(db) == 0


def test_local_login_refresh_and_logout_use_the_postgres_token_ledger(
    postgres, monkeypatch
):
    from fastapi.testclient import TestClient
    from app.core.config import settings
    from app.core.passwords import get_password_hash
    from app.core.rate_limit import limiter
    from app.db.database import get_db
    from app.main import app
    from app.models.user import User

    sessions = sessionmaker(postgres)
    username = "auth-" + uuid.uuid4().hex
    password = "Disposable-test-password-123"
    with sessions.begin() as db:
        db.add(User(username=username, hashed_password=get_password_hash(password)))

    def database_session():
        with sessions() as db:
            yield db

    monkeypatch.setattr(settings, "AUTH_PROVIDER", "local")
    monkeypatch.setattr(limiter, "enabled", False)
    with monkeypatch.context() as patch:
        patch.setitem(app.dependency_overrides, get_db, database_session)
        client = TestClient(app)
        login = client.post(
            "/api/v1/auth/login", data={"username": username, "password": password}
        )
        assert login.status_code == 200
        original = login.json()
        rotated = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
        )
        assert rotated.status_code == 200
        assert (
            client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": original["refresh_token"]},
            ).status_code
            == 401
        )
        current = rotated.json()
        headers = {"Authorization": "Bearer " + current["access_token"]}
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
        assert (
            client.post(
                "/api/v1/auth/logout",
                headers=headers,
                json={"refresh_token": current["refresh_token"]},
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert (
            client.post(
                "/api/v1/auth/refresh", json={"refresh_token": current["refresh_token"]}
            ).status_code
            == 401
        )


def test_primary_transport_permit_has_one_winner_across_database_sessions(
    postgres, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from app.core.model_request_identity import request_fingerprint
    from app.models.user import User
    from app.models.model_budget import ModelBudgetReservation
    from app.usage import runtime, service

    sessions = sessionmaker(postgres)
    monkeypatch.setattr(runtime, "SessionLocal", sessions)
    profile = SimpleNamespace(provider="test", model="test")
    request = SimpleNamespace(
        messages=[{"role": "user", "content": "permit regression"}],
        tools=[],
        system=None,
        max_tokens=8,
        temperature=0,
    )
    digest = request_fingerprint(
        messages=request.messages,
        tools=request.tools,
        system=request.system,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
    )
    with sessions.begin() as db:
        user = User(username="permit-" + uuid.uuid4().hex, hashed_password="unused")
        db.add(user)
        db.flush()
        owner = user.id
        request.usage_permit = service.reserve(
            db,
            user_id=owner,
            turn_id=uuid.uuid4().hex,
            call_id="primary",
            token_allowance=100,
        )
        reservation = db.get(ModelBudgetReservation, request.usage_permit)
        reservation.provider = profile.provider
        reservation.model = profile.model
        reservation.request_fingerprint = digest

    def claim():
        with runtime.scope(owner, "permit-regression"):
            try:
                runtime.claim_primary(request, profile)
            except RuntimeError as exc:
                assert str(exc) == "primary_transport_permit_unavailable"
                return False
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]
    with sessions() as db:
        assert (
            db.get(ModelBudgetReservation, request.usage_permit).transport_claimed_at
            is not None
        )


def test_diagnostic_failure_does_not_poison_following_checks(postgres, monkeypatch):
    from scripts import consistency_scan as scan

    monkeypatch.setattr(scan, "SessionLocal", sessionmaker(postgres))

    def fail(db):
        db.execute(text("SELECT * FROM deliberately_missing_audit_table"))

    def healthy(db):
        assert db.scalar(text("SELECT 1")) == 1
        return [scan.Finding("healthy", 0)]

    monkeypatch.setattr(scan, "scan_orphan_file_assets", fail)
    for name in (
        "scan_orphan_chunks",
        "scan_subjectless_conversations",
        "scan_legacy_migration_sources",
    ):
        monkeypatch.setattr(scan, name, healthy)
    assert [row.count for row in scan.run_scan()] == [-1, 0, 0, 0]


def test_exact_and_hnsw_share_generation_owner_and_source_deletion_fences(
    postgres, monkeypatch
):
    from app.core.config import settings
    from app.db import database
    from app.models.user import User
    from app.models.knowledge import KnowledgeDocument
    from app.models.document_chunk import DocumentChunk
    from app.rag import hybrid_index as index
    from app.rag.index.identity import current_index_identity
    from app.rag.index.hnsw import prepare
    from app.db.types import utc_now

    sessions = sessionmaker(postgres, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "exact")
    identity = current_index_identity()
    vector = [1.0] + [0.0] * (identity.embedding_dim - 1)
    with sessions() as db:
        users = [
            User(username="pg_owner", hashed_password="none"),
            User(username="pg_other", hashed_password="none"),
        ]
        db.add_all(users)
        db.flush()
        ids = [u.id for u in users]
        for i, owner in enumerate(ids):
            db.add(
                KnowledgeDocument(
                    id=f"doc-{i}",
                    user_id=owner,
                    title="RAG",
                    source_kind="manual_text",
                    content_text="alpha evidence",
                    status="ready",
                )
            )
            db.flush()
            db.add(
                DocumentChunk(
                    id=f"chunk-{i}",
                    document_id=f"doc-{i}",
                    user_id=owner,
                    node_id=f"node-{i}",
                    source_kind="manual_text",
                    text="alpha evidence",
                    chunk_index=0,
                )
            )
        db.commit()
    for i, owner in enumerate(ids):
        index.replace_document(
            user_pk=owner,
            document_id=f"doc-{i}",
            source_kind="manual_text",
            rows=[
                {
                    "id": f"node-{i}",
                    "source_text": "alpha evidence",
                    "text": "alpha evidence",
                    "dense": vector,
                }
            ],
        )
    exact = index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5)
    assert len(exact) == 1 and exact[0]["document_id"] == "doc-0"
    with sessions() as db:
        prepare(db, identity, ids[0])
        db.commit()
    monkeypatch.setattr(settings, "PGVECTOR_DENSE_INDEX_TYPE", "hnsw")
    assert [
        r["id"] for r in index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5)
    ] == [r["id"] for r in exact]
    with sessions() as db:
        db.get(KnowledgeDocument, "doc-0").deleted_at = utc_now()
        db.commit()
    assert index.dense_search(query_dense=vector, user_pk=ids[0], top_k=5) == []


def test_recording_publication_rollback_and_generation_fence(postgres, monkeypatch):
    import importlib
    from app.models.user import User
    from app.models.interview_record import InterviewRecord
    from app.models.interview_transcript import InterviewTranscript
    from app.models.interview_qa import InterviewQA
    from app.interviews.application.review_fence import review_scope, ReviewSuperseded

    module = importlib.import_module(
        "app.interviews.application.interview_record_service"
    )
    sessions = sessionmaker(postgres, expire_on_commit=False)
    monkeypatch.setattr(module, "SessionLocal", sessions)
    service = module.interview_record_service
    with sessions.begin() as db:
        owner = User(username="publication_" + uuid.uuid4().hex, hashed_password="test")
        db.add(owner)
        db.flush()
        record = InterviewRecord(user_id=owner.id, source="upload", review_generation=1)
        db.add(record)
        db.flush()
        transcript = InterviewTranscript(
            record_id=record.id, user_id=owner.id, quality_json={"status": "partial"}
        )
        db.add(transcript)
        db.flush()
        record.transcript_id = transcript.id
        old = InterviewQA(record_id=record.id, question="old", answer="old")
        db.add(old)
        db.flush()
        record_id, transcript_id, old_id = record.id, transcript.id, old.id

    def publish():
        service.publish_recording_qa(
            record_id,
            transcript_id,
            structure={"schema_version": 2},
            quality={"status": "complete"},
            qa_pairs=[{"question": "new", "answer": "new"}],
        )

    original = service.bulk_insert_qa

    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("failure after flush")

    with monkeypatch.context() as patch:
        patch.setattr(service, "bulk_insert_qa", fail)
        with (
            review_scope(record_id, 1),
            pytest.raises(RuntimeError, match="after flush"),
        ):
            publish()
    with sessions() as db:
        assert db.get(InterviewQA, old_id).answer == "old"
        assert (
            db.get(InterviewTranscript, transcript_id).quality_json["status"]
            == "partial"
        )
    with sessions.begin() as db:
        db.get(InterviewRecord, record_id).review_generation = 2
    with review_scope(record_id, 1), pytest.raises(ReviewSuperseded):
        publish()
    with review_scope(record_id, 2):
        publish()
    with sessions() as db:
        assert db.get(InterviewQA, old_id) is None
        rows = db.query(InterviewQA).filter_by(record_id=record_id).all()
        assert len(rows) == 1 and rows[0].answer == "new"
        assert (
            db.get(InterviewTranscript, transcript_id).quality_json["status"]
            == "complete"
        )


def test_ingestion_identity_is_visible_before_fast_worker_and_failure_is_recoverable(
    postgres,
):
    from sqlalchemy.orm import Session
    from app.models.user import User
    from app.models.knowledge import KnowledgeDocument
    from app.rag.application.document_commands import enqueue_ingestion
    from app.rag.index.source import source_snapshot
    from app.core.command_errors import CommandError

    with Session(postgres) as db:
        user = User(
            username="dispatch-" + uuid.uuid4().hex, hashed_password="not-a-login"
        )
        db.add(user)
        db.flush()
        document = KnowledgeDocument(
            user_id=user.id,
            title="Fast worker",
            source_kind="manual_text",
            status="processing",
        )
        db.add(document)
        db.commit()
        document_id = document.id

        def fast_worker(identity, *, task_id):
            with Session(postgres) as worker:
                row = worker.get(KnowledgeDocument, identity)
                assert (
                    row.task_id == task_id
                )  # Separate connection sees the committed fence.
                snapshot = source_snapshot(worker, row)
                with Session(postgres) as observer:
                    assert (
                        source_snapshot(
                            observer, observer.get(KnowledgeDocument, identity)
                        )
                        == snapshot
                    )
                row.status, row.content_text = "ready", "Worker result"
                worker.commit()

        result = enqueue_ingestion(db, document_id=document_id, dispatch=fast_worker)
        assert result.status == "ready" and result.content_text == "Worker result"
        enqueue_ingestion(
            db,
            document_id=document_id,
            dispatch=lambda *_a, **_k: pytest.fail("terminal replay must not dispatch"),
        )

        result.status, result.task_id = "processing", None
        db.commit()

        def unavailable(*_args, **_kwargs):
            raise ConnectionError("broker unavailable")

        with pytest.raises(CommandError, match="后台处理队列"):
            enqueue_ingestion(db, document_id=document_id, dispatch=unavailable)
        with Session(postgres) as observer:
            assert observer.get(KnowledgeDocument, document_id).status == "failed"
