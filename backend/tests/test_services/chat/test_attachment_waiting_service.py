"""Waiting/resume chain for asynchronous Conversation attachment parsing."""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.db.types import utc_now
from app.models.chat import Conversation
from app.models.conversation_attachment import ConversationAttachmentRef
from app.models.conversation_turn import ConversationTurn
from app.models.file_asset import FileAsset
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.services.chat import attachment_waiting_service
from app.services.chat.attachment_waiting_service import (
    ATTACHMENT_PARSING_WAIT_REASON,
    recover_terminal_attachment_turns,
    wake_attachment_turn_if_terminal,
    wake_attachment_turns_for_projection,
)


def _seed_waiting_turn(db, *, second_status: str = "processing") -> str:
    user = User(username="attachment-waiter", hashed_password="x")
    db.add(user)
    db.flush()
    conversation = Conversation(
        id="conv-attachment-wait",
        user_id=user.id,
        title="attachment wait",
    )
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        id="turn-attachment-wait",
        conversation_id=conversation.id,
        user_id=user.id,
        mode="agent",
        message="compare files",
        status="waiting",
        waiting_reason=ATTACHMENT_PARSING_WAIT_REASON,
        dispatch_generation=1,
    )
    db.add(turn)
    db.flush()
    conversation.active_turn_id = turn.id

    for position, status in enumerate(("ready", second_status)):
        asset_id = f"fa-attachment-wait-{position}"
        document_id = f"kdoc-attachment-wait-{position}"
        asset = FileAsset(
            id=asset_id,
            user_id=user.id,
            purpose="knowledge_document",
            original_filename=f"file-{position}.txt",
            object_key=f"uploads/{user.id}/{asset_id}/file.txt",
            storage_uri=f"s3://bucket/uploads/{user.id}/{asset_id}/file.txt",
            upload_status="consumed",
            validation_status="passed",
        )
        document = KnowledgeDocument(
            id=document_id,
            user_id=user.id,
            conversation_id=conversation.id,
            file_asset_id=asset.id,
            title=asset.original_filename,
            category="会话附件",
            source_kind="chat_attachment",
            storage_uri=asset.storage_uri,
            object_key=asset.object_key,
            status=status,
        )
        ref = ConversationAttachmentRef(
            id=f"ar-attachment-wait-{position}",
            draft_id=f"ad-attachment-wait-{position}",
            user_id=user.id,
            conversation_id=conversation.id,
            turn_id=turn.id,
            submission_id="submission-attachment-wait",
            position=position,
            file_asset_id=asset.id,
            source_document_id=document.id,
            file_asset_version=f"file_asset:{asset.id}",
            display_name=asset.original_filename,
        )
        db.add_all([asset, document, ref])
    db.commit()
    return turn.id


def _patch_runtime(db_session, monkeypatch, scheduled, reset) -> None:
    maker = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(attachment_waiting_service, "SessionLocal", maker)
    monkeypatch.setattr(
        attachment_waiting_service,
        "_reset_events",
        lambda turn_id: reset.append(turn_id),
    )
    import app.services.chat.turn_executor as turn_executor

    monkeypatch.setattr(
        turn_executor,
        "schedule_turn",
        lambda turn_id: scheduled.append(turn_id),
    )


def test_last_terminal_projection_resumes_same_turn_once(db_session, monkeypatch):
    turn_id = _seed_waiting_turn(db_session)
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)

    assert wake_attachment_turns_for_projection("kdoc-attachment-wait-0") == []
    waiting = db_session.get(ConversationTurn, turn_id)
    db_session.refresh(waiting)
    assert waiting.status == "waiting"

    second = db_session.get(KnowledgeDocument, "kdoc-attachment-wait-1")
    second.status = "ready"
    db_session.commit()
    assert wake_attachment_turns_for_projection(second.id) == [turn_id]

    db_session.refresh(waiting)
    assert waiting.status == "pending"
    assert waiting.waiting_reason is None
    assert waiting.dispatch_generation == 2
    assert scheduled == [turn_id]
    assert reset == [turn_id]

    assert wake_attachment_turns_for_projection(second.id) == []
    assert scheduled == [turn_id]


def test_failed_projection_stays_on_same_turn_until_retry_is_ready(
    db_session, monkeypatch
):
    turn_id = _seed_waiting_turn(db_session, second_status="failed")
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)

    assert wake_attachment_turns_for_projection("kdoc-attachment-wait-1") == []
    turn = db_session.get(ConversationTurn, turn_id)
    db_session.refresh(turn)
    assert turn.status == "waiting"
    assert scheduled == []

    from app.services.chat.attachment_source_service import (
        prepare_attachment_projection_retry,
    )

    retry = prepare_attachment_projection_retry(
        db_session,
        user_pk=turn.user_id,
        conversation_id=turn.conversation_id,
        source_id="ar-attachment-wait-1",
    )
    assert retry.should_dispatch is True
    failed_document = db_session.get(KnowledgeDocument, "kdoc-attachment-wait-1")
    failed_document.status = "ready"
    db_session.commit()
    assert wake_attachment_turns_for_projection(failed_document.id) == [turn_id]
    assert scheduled == [turn_id]


def test_explicit_failed_source_removal_resumes_when_remaining_sources_are_ready(
    db_session, monkeypatch
):
    turn_id = _seed_waiting_turn(db_session, second_status="failed")
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)
    failed_ref = db_session.get(
        ConversationAttachmentRef,
        "ar-attachment-wait-1",
    )
    failed_ref.removed_at = utc_now()
    db_session.commit()

    assert wake_attachment_turn_if_terminal(turn_id) is True
    turn = db_session.get(ConversationTurn, turn_id)
    db_session.refresh(turn)
    assert turn.status == "pending"
    assert scheduled == [turn_id]


def test_dispatch_failure_terminalizes_resumed_turn(db_session, monkeypatch):
    turn_id = _seed_waiting_turn(db_session, second_status="ready")
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)
    import app.services.chat.turn_executor as turn_executor

    def _dispatch_failure(_turn_id: str) -> None:
        raise ConnectionError("queue unavailable")

    monkeypatch.setattr(turn_executor, "schedule_turn", _dispatch_failure)

    assert wake_attachment_turns_for_projection("kdoc-attachment-wait-1") == []
    turn = db_session.get(ConversationTurn, turn_id)
    db_session.refresh(turn)
    assert turn.status == "failed"
    assert "恢复队列" in (turn.error or "")


def test_post_wait_recheck_closes_ingestion_before_wait_race(db_session, monkeypatch):
    turn_id = _seed_waiting_turn(db_session, second_status="ready")
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)

    assert wake_attachment_turn_if_terminal(turn_id) is True
    assert wake_attachment_turn_if_terminal(turn_id) is False
    assert scheduled == [turn_id]


def test_repair_scan_retries_durable_missed_wakeup(db_session, monkeypatch):
    turn_id = _seed_waiting_turn(db_session, second_status="ready")
    scheduled: list[str] = []
    reset: list[str] = []
    _patch_runtime(db_session, monkeypatch, scheduled, reset)

    assert recover_terminal_attachment_turns(limit=10) == [turn_id]
    assert recover_terminal_attachment_turns(limit=10) == []
    assert scheduled == [turn_id]
