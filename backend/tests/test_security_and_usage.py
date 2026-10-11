"""Ownership, credentials, approval and consumption are independent boundaries."""

import io
import os
import pytest
from app.core import passwords, storage
from app.core.config import settings
from app.agent_runtime.tool_policy import (
    ToolEffect,
    ToolPolicyContext,
    evaluate_tool_policy,
)
from app.usage import service as usage


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
