"""Ownership, credentials, approval and consumption are independent boundaries."""

import io
import os
import asyncio
import pytest
from app.core import passwords, storage
from app.core.config import settings
from app.agent_runtime.tool_policy import (
    ToolEffect,
    ToolPolicyContext,
    evaluate_tool_policy,
)
from app.usage import service as usage


def test_unknown_account_performs_real_password_work(db, monkeypatch):
    from app.identity.application import user_account_service as accounts

    hashes = []

    def hash_password(value):
        result = passwords.get_password_hash(value)
        hashes.append(result)
        return result

    monkeypatch.setattr(accounts, "get_password_hash", hash_password)
    assert accounts.authenticate(db, "missing-account", "wrong-password") is None
    assert len(hashes) == 1
    assert passwords.verify_password("wrong-password", hashes[0])


@pytest.mark.parametrize("local", [True, False])
@pytest.mark.parametrize("asynchronous", [True, False])
def test_local_model_failure_preserves_cause_without_refunding_usage(
    monkeypatch, local, asynchronous
):
    from app.usage import runtime
    from app.core.execution_errors import ModelOutcomeUnknownError

    settlements = []
    monkeypatch.setattr(runtime, "begin", lambda **_: object())
    monkeypatch.setattr(
        runtime, "finish", lambda receipt, outcome, *args: settlements.append(outcome)
    )
    cause = ValueError("invalid_alignment_time")

    def fail():
        raise cause

    async def afail():
        fail()

    with pytest.raises(ValueError if local else ModelOutcomeUnknownError) as caught:
        if asynchronous:
            asyncio.run(runtime.invoke_async(afail, local_execution=local))
        else:
            runtime.invoke_sync(fail, local_execution=local)
    if local:
        assert caught.value is cause
    assert settlements == ["unknown"]


@pytest.mark.parametrize(
    "state", ["pending", "waiting", "cancel_requested", "cancelled"]
)
def test_model_admission_rejects_non_running_or_cancel_requested_turn(
    db, owners, state
):
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.models.model_dispatch import AgentModelDispatch
    from app.conversation.application.model_dispatch_service import (
        start_model_dispatch,
        ModelDispatchConflictError,
    )

    conversation = Conversation(user_id=owners[0].id)
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=owners[0].id,
        mode="agent",
        message="task",
        status="running" if state == "cancel_requested" else state,
        cancel_requested=state == "cancel_requested",
        dispatch_generation=1,
    )
    db.add(turn)
    db.flush()
    with pytest.raises(ModelDispatchConflictError):
        start_model_dispatch(
            db,
            call_id="forbidden-call",
            turn_id=turn.id,
            user_id=owners[0].id,
            dispatch_generation=1,
            provider="test",
            model="test",
            fingerprint="a" * 64,
        )
    assert db.query(AgentModelDispatch).count() == 0


def test_terminal_turn_closes_unreceipted_model_call_without_refunding(
    db, owners, monkeypatch
):
    from app.models.chat import Conversation
    from app.models.conversation_turn import ConversationTurn
    from app.conversation.application.model_dispatch_service import start_model_dispatch
    from app.conversation.application.turn_store import _terminalize

    # Keep service commits inside this SQLite fixture's rollback boundary.
    monkeypatch.setattr(db, "commit", db.flush)
    conversation = Conversation(user_id=owners[0].id)
    db.add(conversation)
    db.flush()
    turn = ConversationTurn(
        conversation_id=conversation.id,
        user_id=owners[0].id,
        mode="chat",
        message="test",
        status="running",
    )
    db.add(turn)
    db.flush()
    conversation.active_turn_id = turn.id
    dispatch = start_model_dispatch(
        db,
        call_id="lost-call",
        turn_id=turn.id,
        user_id=owners[0].id,
        dispatch_generation=1,
        provider="test",
        model="test",
        fingerprint="a" * 64,
        token_allowance=100,
    )
    changed, _ = _terminalize(
        db, turn.id, allowed_statuses={"running"}, status="failed", error="worker_lost"
    )
    db.refresh(dispatch)
    assert changed and conversation.active_turn_id is None
    assert dispatch.status == "unknown" and dispatch.completed_at is not None
    view = usage.usage_view(db, user_id=owners[0].id)
    assert view["tokens_reserved"] == 100 and view["unresolved_all_dates"] == 1


def test_password_hash_never_accepts_wrong_or_malformed_passwords():
    hashed = passwords.get_password_hash("测试密钥-123")
    assert hashed != "测试密钥-123" and hashed.startswith("$argon2")
    assert passwords.verify_password("测试密钥-123", hashed)
    for value in ("wrong", "", "测试密钥-12"):
        assert not passwords.verify_password(value, hashed)
    assert passwords.verify_and_maybe_rehash("x", "garbage") == (False, None)


@pytest.mark.parametrize("effect", list(ToolEffect))
def test_hard_deny_is_not_overridden_by_auto_mode_or_confirmation(effect):
    decision = evaluate_tool_policy(
        effect,
        ToolPolicyContext(
            execution_mode="auto",
            user_confirmed_this_call=True,
            current_task_authorizes=True,
            hard_deny_reason="scope_lost",
        ),
    )
    assert decision.outcome == "deny"


def test_reads_and_external_writes_have_different_authority():
    assert evaluate_tool_policy(ToolEffect.READ, ToolPolicyContext()).outcome == "allow"
    assert (
        evaluate_tool_policy(ToolEffect.EXTERNAL_WRITE, ToolPolicyContext()).outcome
        == "ask"
    )
    assert (
        evaluate_tool_policy(
            ToolEffect.READ, ToolPolicyContext(provider_scope_allows=False)
        ).outcome
        == "deny"
    )


def test_unknown_model_outcome_keeps_reservation_until_reconciled(db, owners):
    owner, other = owners
    kwargs = dict(user_id=owner.id, turn_id="turn", call_id="call", token_allowance=100)
    identity = usage.reserve(db, **kwargs)
    assert identity
    with pytest.raises(ValueError, match="already_exists"):
        usage.reserve(db, **kwargs)
    usage.settle(
        db,
        user_id=owner.id,
        turn_id="turn",
        call_id="call",
        outcome="unknown",
        observed_tokens=None,
    )
    before = usage.usage_view(db, user_id=owner.id)
    assert before["tokens_reserved"] == 100 and before["unresolved_all_dates"] == 1
    usage.settle(
        db,
        user_id=owner.id,
        turn_id="turn",
        call_id="call",
        outcome="rejected",
        observed_tokens=None,
    )
    assert usage.usage_view(db, user_id=owner.id)["tokens_reserved"] == 100
    assert usage.usage_view(db, user_id=other.id)["tokens_reserved"] == 0
    usage.settle(
        db,
        user_id=owner.id,
        turn_id="turn",
        call_id="call",
        outcome="completed",
        observed_tokens=60,
        reconciliation_ref="operator:receipt-1",
    )
    assert usage.usage_view(db, user_id=owner.id)["tokens_used"] == 60
    assert usage.usage_view(db, user_id=owner.id)["tokens_reserved"] == 0


@pytest.mark.skipif(
    not hasattr(os, "O_DIRECTORY"), reason="local storage is executed in Linux workers"
)
def test_file_writes_are_immutable_and_symlink_escape_is_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "STORAGE_DIR", str(tmp_path / "objects"))
    monkeypatch.setattr(storage, "check_free_space", lambda n: None)
    uri = "local://owner/object.txt"
    storage.store_object(io.BytesIO(b"original"), uri)
    with pytest.raises(FileExistsError):
        storage.store_object(io.BytesIO(b"replacement"), uri)
    with storage.open_local_object(uri) as source:
        assert source.read() == b"original"
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "objects" / "redirect").symlink_to(outside, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        storage.store_object(io.BytesIO(b"escape"), "local://redirect/payload")
    assert not list(outside.iterdir())
