"""Focused Gmail account/credential lifecycle tests."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.models.gmail_integration import GmailIntegrationAccount
from app.models.user import User
from app.schemas.gmail_integration import (
    GmailIntegrationAccountView,
    GmailMessageSummary,
)
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailAccountNotFoundError,
    GmailConnectionRequiredError,
    GmailCredentialHandleError,
    GmailGrantInspection,
    GmailProviderAdapterError,
    bind_verified_grant,
    revoke_account,
    search_messages,
    test_account as verify_account,
)


NOW = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
HANDLE = "gch_" + "opaque_handle_sentinel_1234567890"


class FakeGmailAdapter:
    def __init__(self) -> None:
        self.inspection = GmailGrantInspection(
            google_subject="google-subject-1",
            account_email="alice.private@gmail.com",
            granted_scopes=frozenset({GMAIL_READONLY_SCOPE}),
        )
        self.inspect_error: GmailProviderAdapterError | None = None
        self.search_error: GmailProviderAdapterError | None = None
        self.inspected_handles: list[tuple[str, int]] = []
        self.revoked_handles: list[tuple[str, int]] = []
        self.search_calls: list[tuple[str, int, str, int]] = []

    async def inspect_grant(
        self,
        credential_handle: str,
        *,
        user_pk: int,
    ) -> GmailGrantInspection:
        self.inspected_handles.append((credential_handle, user_pk))
        if self.inspect_error is not None:
            raise self.inspect_error
        return self.inspection

    async def revoke_grant(self, credential_handle: str, *, user_pk: int) -> None:
        self.revoked_handles.append((credential_handle, user_pk))

    async def search_messages(
        self,
        credential_handle: str,
        *,
        user_pk: int,
        query: str,
        limit: int,
    ) -> list[GmailMessageSummary]:
        self.search_calls.append((credential_handle, user_pk, query, limit))
        if self.search_error is not None:
            raise self.search_error
        return [
            GmailMessageSummary(
                message_id="gmail-message-1",
                thread_id="gmail-thread-1",
                received_at=NOW,
                from_hint="recruiter@example.com",
                subject="Interview invitation",
                snippet="Please choose an interview time.",
            )
        ]


def _user(db, name: str = "alice") -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db.add(row)
    db.flush()
    return row


def _bind(db, user: User, adapter: FakeGmailAdapter, handle: str = HANDLE):
    return asyncio.run(
        bind_verified_grant(
            db,
            user_pk=user.id,
            credential_handle=handle,
            adapter=adapter,
        )
    )


def test_bind_stores_only_encrypted_handle_and_safe_account_view(db_session):
    user = _user(db_session)
    adapter = FakeGmailAdapter()
    row = _bind(db_session, user, adapter)

    assert row.status == "active"
    assert row.account_hint == "a***@gmail.com"
    assert row.scopes_json == [GMAIL_READONLY_SCOPE]
    assert HANDLE not in row.credential_handle_ciphertext
    assert adapter.inspected_handles == [(HANDLE, user.id)]

    payload = GmailIntegrationAccountView.model_validate(row).model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False)
    assert payload["provider"] == "gmail"
    assert payload["account_hint"] == "a***@gmail.com"
    assert "credential" not in encoded
    assert HANDLE not in encoded


def test_raw_token_shape_and_missing_read_scope_never_create_account(db_session):
    user = _user(db_session)
    adapter = FakeGmailAdapter()

    with pytest.raises(GmailCredentialHandleError):
        _bind(db_session, user, adapter, "ya29.a-real-token-must-not-be-accepted")
    assert adapter.inspected_handles == []

    adapter.inspection = GmailGrantInspection(
        google_subject="google-subject-1",
        account_email="alice@gmail.com",
        granted_scopes=frozenset({"openid"}),
    )
    with pytest.raises(GmailConnectionRequiredError):
        _bind(db_session, user, adapter)
    assert db_session.query(GmailIntegrationAccount).count() == 0


def test_connection_test_persists_only_safe_error_code(db_session):
    user = _user(db_session)
    adapter = FakeGmailAdapter()
    row = _bind(db_session, user, adapter)
    secret_in_error = "refresh-token-sentinel-must-not-persist"
    adapter.inspect_error = GmailProviderAdapterError(
        f"invalid grant: {secret_in_error}"
    )

    checked = asyncio.run(verify_account(db_session, user_pk=user.id, adapter=adapter))

    assert checked.id == row.id
    assert checked.status == "active"
    assert checked.last_error_code == "provider_error"
    assert secret_in_error not in json.dumps(
        GmailIntegrationAccountView.model_validate(checked).model_dump(mode="json")
    )
    assert secret_in_error not in checked.credential_handle_ciphertext


def test_search_is_bounded_and_invalid_grant_forces_reconnect(db_session):
    user = _user(db_session)
    adapter = FakeGmailAdapter()
    row = _bind(db_session, user, adapter)

    result = asyncio.run(
        search_messages(
            db_session,
            user_pk=user.id,
            query="newer_than:30d interview",
            limit=5,
            adapter=adapter,
        )
    )
    payload = result.model_dump(mode="json")
    assert payload["account_id"] == row.id
    assert payload["messages"][0]["message_id"] == "gmail-message-1"
    assert adapter.search_calls == [(HANDLE, user.id, "newer_than:30d interview", 5)]
    assert HANDLE not in json.dumps(payload, ensure_ascii=False)

    adapter.search_error = GmailProviderAdapterError("invalid_grant")
    with pytest.raises(GmailConnectionRequiredError):
        asyncio.run(
            search_messages(
                db_session,
                user_pk=user.id,
                query="newer_than:7d offer",
                limit=5,
                adapter=adapter,
            )
        )
    assert row.status == "invalid"
    assert row.last_error_code == "invalid_grant"


def test_read_preflight_rechecks_persisted_gmail_scope(db_session):
    user = _user(db_session)
    adapter = FakeGmailAdapter()
    row = _bind(db_session, user, adapter)
    row.scopes_json = ["openid"]
    db_session.flush()

    with pytest.raises(GmailConnectionRequiredError):
        asyncio.run(
            search_messages(
                db_session,
                user_pk=user.id,
                query="interview",
                limit=5,
                adapter=adapter,
            )
        )
    assert adapter.search_calls == []


def test_revoke_is_provider_confirmed_owned_and_idempotent(db_session):
    alice = _user(db_session, "alice")
    bob = _user(db_session, "bob")
    adapter = FakeGmailAdapter()
    row = _bind(db_session, alice, adapter)

    with pytest.raises(GmailAccountNotFoundError):
        asyncio.run(revoke_account(db_session, user_pk=bob.id, adapter=adapter))

    revoked = asyncio.run(revoke_account(db_session, user_pk=alice.id, adapter=adapter))
    retry = asyncio.run(revoke_account(db_session, user_pk=alice.id, adapter=adapter))

    assert revoked.id == row.id == retry.id
    assert revoked.status == "revoked"
    assert revoked.credential_handle_ciphertext is None
    assert revoked.scopes_json == []
    assert adapter.revoked_handles == [(HANDLE, alice.id)]
    with pytest.raises(GmailConnectionRequiredError):
        asyncio.run(
            search_messages(
                db_session,
                user_pk=alice.id,
                query="interview",
                limit=5,
                adapter=adapter,
            )
        )
