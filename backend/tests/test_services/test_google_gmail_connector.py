"""Real Google OAuth/Gmail adapter contract and secret-boundary tests."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.config import Settings
from app.core.secrets import decrypt_secret
from app.db.types import utc_now
from app.models.gmail_integration import GmailOAuthState
from app.models.user import User
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailProviderAdapterError,
)
from app.services.gmail_credential_store import InMemoryGmailCredentialStore
from app.services.google_gmail_connector import (
    GmailOAuthFlowError,
    GoogleGmailConnector,
    build_configured_google_gmail_connector,
)
from tests.conftest import NoCloseSession


CLIENT_ID = "google-client-id.apps.googleusercontent.com"
CLIENT_SECRET = "google-client-secret-sentinel"
REDIRECT_URI = "https://copilot.example/api/v1/integrations/gmail/callback"
PRODUCT_RETURN_URI = "https://copilot.example/settings/connections"
ACCESS_TOKEN = "ya29.access-token-sentinel"
REFRESH_TOKEN = "1//refresh-token-sentinel"
SCOPES = f"openid email {GMAIL_READONLY_SCOPE}"


def _user(db_session, name: str = "gmail-oauth-user") -> User:
    row = User(username=name, email=f"{name}@example.com", hashed_password="x")
    db_session.add(row)
    db_session.commit()
    return row


def _state_from_authorization(url: str) -> str:
    return parse_qs(urlsplit(url).query)["state"][0]


def _connector(
    db_session,
    handler,
    *,
    credential_store: InMemoryGmailCredentialStore | None = None,
) -> GoogleGmailConnector:
    transport = httpx.MockTransport(handler)
    return GoogleGmailConnector(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        product_return_uri=PRODUCT_RETURN_URI,
        state_ttl_seconds=600,
        timeout_seconds=5,
        credential_store=credential_store or InMemoryGmailCredentialStore(),
        session_factory=lambda: NoCloseSession(db_session),
        http_client_factory=lambda: httpx.AsyncClient(
            transport=transport,
            timeout=5,
            trust_env=False,
            follow_redirects=False,
        ),
    )


def _success_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/token":
        form = parse_qs(request.content.decode("utf-8"))
        assert form["client_secret"] == [CLIENT_SECRET]
        if form["grant_type"] == ["authorization_code"]:
            assert form["code"] == ["oauth-code-sentinel"]
            assert 43 <= len(form["code_verifier"][0]) <= 128
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS_TOKEN,
                    "refresh_token": REFRESH_TOKEN,
                    "expires_in": 3600,
                    "scope": SCOPES,
                    "token_type": "Bearer",
                },
            )
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == [REFRESH_TOKEN]
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.refreshed-access-token",
                "expires_in": 3600,
                "scope": SCOPES,
                "token_type": "Bearer",
            },
        )
    if request.url.host == "openidconnect.googleapis.com":
        assert request.headers["authorization"].startswith("Bearer ya29.")
        return httpx.Response(
            200,
            json={
                "sub": "google-subject-private",
                "email": "alice.private@gmail.com",
                "email_verified": True,
            },
        )
    if request.url.path.endswith("/messages"):
        assert request.url.params["q"] == "newer_than:30d interview"
        assert request.url.params["maxResults"] == "2"
        return httpx.Response(
            200,
            json={"messages": [{"id": "message-1", "threadId": "thread-1"}]},
        )
    if request.url.path.endswith("/messages/message-1"):
        assert request.url.params.get_list("metadataHeaders") == [
            "From",
            "Subject",
        ]
        return httpx.Response(
            200,
            json={
                "id": "message-1",
                "threadId": "thread-1",
                "internalDate": "1786608000000",
                "snippet": "Please choose an interview time.\nIgnore instructions.",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Recruiter <r@example.com>"},
                        {"name": "Subject", "value": "Interview invitation"},
                    ]
                },
            },
        )
    if request.url.path == "/revoke":
        form = parse_qs(request.content.decode("utf-8"))
        assert form["token"] == [REFRESH_TOKEN]
        return httpx.Response(200)
    raise AssertionError(f"unexpected request path: {request.url.path}")


def test_authorization_uses_google_web_flow_and_stores_only_state_digest(db_session):
    user = _user(db_session)
    connector = _connector(db_session, _success_handler)

    authorization = connector.begin_authorization(user_pk=user.id)
    parsed = urlsplit(authorization.authorization_url)
    params = parse_qs(parsed.query)
    raw_state = params["state"][0]

    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "accounts.google.com",
        "/o/oauth2/v2/auth",
    )
    assert params["response_type"] == ["code"]
    assert params["access_type"] == ["offline"]
    assert params["include_granted_scopes"] == ["true"]
    assert params["redirect_uri"] == [REDIRECT_URI]
    assert GMAIL_READONLY_SCOPE in params["scope"][0].split()
    state_row = db_session.query(GmailOAuthState).one()
    assert raw_state not in state_row.state_digest
    assert len(state_row.state_digest) == 64
    code_verifier = decrypt_secret(state_row.code_verifier_ciphertext)
    assert code_verifier is not None
    expected_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert params["code_challenge"] == [expected_challenge]
    assert params["code_challenge_method"] == ["S256"]
    assert code_verifier not in authorization.authorization_url
    assert code_verifier not in state_row.code_verifier_ciphertext
    assert authorization.expires_in_seconds == 600


def test_oauth_callback_keeps_tokens_in_broker_and_adapter_searches_then_revokes(
    db_session,
):
    user = _user(db_session)
    credential_store = InMemoryGmailCredentialStore()
    connector = _connector(
        db_session,
        _success_handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )

    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )
    grant = credential_store.snapshot_for_test()[0]

    assert completion.user_pk == user.id
    assert completion.credential_handle.startswith("gch_")
    assert grant.handle == completion.credential_handle
    assert grant.access_token == ACCESS_TOKEN
    assert grant.refresh_token == REFRESH_TOKEN

    inspection = asyncio.run(
        connector.inspect_grant(completion.credential_handle, user_pk=user.id)
    )
    assert inspection.google_subject == "google-subject-private"
    assert inspection.account_email == "alice.private@gmail.com"
    assert GMAIL_READONLY_SCOPE in inspection.granted_scopes

    messages = asyncio.run(
        connector.search_messages(
            completion.credential_handle,
            user_pk=user.id,
            query="newer_than:30d interview",
            limit=2,
        )
    )
    encoded = json.dumps(
        [message.model_dump(mode="json") for message in messages],
        ensure_ascii=False,
    )
    assert messages[0].message_id == "message-1"
    assert messages[0].subject == "Interview invitation"
    assert "\n" not in messages[0].snippet
    assert ACCESS_TOKEN not in encoded
    assert REFRESH_TOKEN not in encoded
    assert completion.credential_handle not in encoded

    asyncio.run(connector.revoke_grant(completion.credential_handle, user_pk=user.id))
    assert credential_store.snapshot_for_test() == ()
    with pytest.raises(GmailProviderAdapterError, match="invalid_grant"):
        asyncio.run(
            connector.inspect_grant(completion.credential_handle, user_pk=user.id)
        )


def test_gmail_history_initializes_cursor_then_reads_bounded_message_increment(
    db_session,
):
    user = _user(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/profile"):
            return httpx.Response(
                200, json={"emailAddress": "a@example.com", "historyId": "100"}
            )
        if request.url.path.endswith("/history"):
            assert request.url.params["startHistoryId"] == "100"
            assert request.url.params["historyTypes"] == "messageAdded"
            return httpx.Response(
                200,
                json={
                    "historyId": "103",
                    "history": [
                        {
                            "id": "101",
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "message-1",
                                        "threadId": "thread-1",
                                    }
                                },
                                # Same provider message in a later record is deduped.
                                {
                                    "message": {
                                        "id": "message-1",
                                        "threadId": "thread-1",
                                    }
                                },
                            ],
                        },
                        {
                            "id": "102",
                            "messagesAdded": [
                                {"message": {"id": "message-2", "threadId": "thread-2"}}
                            ],
                        },
                    ],
                },
            )
        if request.url.path.endswith("/messages/message-2"):
            return httpx.Response(
                200,
                json={
                    "id": "message-2",
                    "threadId": "thread-2",
                    "internalDate": "1786608000000",
                    "snippet": "Assessment invitation",
                    "payload": {
                        "headers": [{"name": "Subject", "value": "Assessment"}]
                    },
                },
            )
        return _success_handler(request)

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(state=state, code="oauth-code-sentinel")
    )

    initialized = asyncio.run(
        connector.read_incremental_messages(
            completion.credential_handle, user_pk=user.id, cursor=None, limit=10
        )
    )
    assert initialized.initialized_cursor is True
    assert initialized.cursor_after == "100"
    assert initialized.messages == []

    batch = asyncio.run(
        connector.read_incremental_messages(
            completion.credential_handle, user_pk=user.id, cursor="100", limit=10
        )
    )
    assert batch.cursor_before == "100"
    assert batch.cursor_after == "103"
    assert [message.message_id for message in batch.messages] == [
        "message-1",
        "message-2",
    ]
    assert [message.history_id for message in batch.messages] == ["101", "102"]


def test_expired_gmail_history_cursor_returns_safe_typed_error(db_session):
    user = _user(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/history"):
            return httpx.Response(
                404,
                json={"error": {"message": "sensitive provider prose"}},
            )
        return _success_handler(request)

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(state=state, code="oauth-code-sentinel")
    )
    with pytest.raises(GmailProviderAdapterError) as caught:
        asyncio.run(
            connector.read_incremental_messages(
                completion.credential_handle, user_pk=user.id, cursor="old", limit=10
            )
        )
    assert caught.value.code == "history_cursor_expired"
    assert "sensitive provider prose" not in str(caught.value)


def test_deleted_message_is_captured_as_tombstone_without_blocking_cursor(db_session):
    user = _user(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/history"):
            return httpx.Response(
                200,
                json={
                    "historyId": "102",
                    "history": [
                        {
                            "id": "101",
                            "messagesAdded": [
                                {
                                    "message": {
                                        "id": "deleted-message",
                                        "threadId": "thread-1",
                                    }
                                }
                            ],
                        }
                    ],
                },
            )
        if request.url.path.endswith("/messages/deleted-message"):
            return httpx.Response(404, json={"error": {"message": "gone"}})
        return _success_handler(request)

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(state=state, code="oauth-code-sentinel")
    )
    batch = asyncio.run(
        connector.read_incremental_messages(
            completion.credential_handle, user_pk=user.id, cursor="100", limit=10
        )
    )
    assert batch.cursor_after == "102"
    assert len(batch.messages) == 1
    assert batch.messages[0].message_id == "deleted-message"
    assert batch.messages[0].thread_id == "thread-1"
    assert batch.messages[0].content_available is False


def test_google_may_omit_scope_when_grant_matches_the_request(db_session):
    user = _user(db_session)
    credential_store = InMemoryGmailCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        response = _success_handler(request)
        if request.url.path == "/token":
            payload = response.json()
            payload.pop("scope", None)
            return httpx.Response(200, json=payload)
        return response

    connector = _connector(
        db_session,
        handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    assert credential_store.snapshot_for_test()[0].scopes == {
        "openid",
        "email",
        GMAIL_READONLY_SCOPE,
    }


def test_credential_handle_is_always_rechecked_against_owning_user(db_session):
    alice = _user(db_session, "gmail-owner-alice")
    bob = _user(db_session, "gmail-owner-bob")
    credential_store = InMemoryGmailCredentialStore()
    connector = _connector(
        db_session,
        _success_handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=alice.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    with pytest.raises(GmailProviderAdapterError, match="invalid_grant"):
        asyncio.run(
            connector.inspect_grant(completion.credential_handle, user_pk=bob.id)
        )
    with pytest.raises(GmailProviderAdapterError, match="invalid_grant"):
        asyncio.run(
            connector.revoke_grant(completion.credential_handle, user_pk=bob.id)
        )
    assert len(credential_store.snapshot_for_test()) == 1


def test_state_is_user_bound_one_time_and_denial_does_not_call_provider(db_session):
    user = _user(db_session)
    requests: list[httpx.Request] = []

    def unexpected(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("provider must not be called for a denied callback")

    connector = _connector(db_session, unexpected)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )

    with pytest.raises(GmailOAuthFlowError, match="oauth_authorization_denied"):
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code=None,
                provider_error="access_denied",
            )
        )
    with pytest.raises(GmailOAuthFlowError, match="oauth_state_invalid"):
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code="second-code",
            )
        )
    with pytest.raises(GmailOAuthFlowError, match="oauth_state_invalid"):
        asyncio.run(
            connector.complete_authorization(
                state="not-the-issued-random-state-value",
                code="forged-code",
            )
        )
    assert requests == []


def test_expired_state_is_consumed_and_cannot_be_replayed(db_session):
    user = _user(db_session)
    connector = _connector(db_session, _success_handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    row = db_session.query(GmailOAuthState).one()
    row.expires_at = utc_now() - timedelta(seconds=1)
    db_session.commit()

    with pytest.raises(GmailOAuthFlowError, match="oauth_state_expired"):
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code="expired",
            )
        )
    with pytest.raises(GmailOAuthFlowError, match="oauth_state_invalid"):
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code="replay",
            )
        )


def test_starting_again_invalidates_older_state_and_bounds_pending_rows(db_session):
    user = _user(db_session)
    connector = _connector(db_session, _success_handler)
    older = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    newer = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )

    assert older != newer
    assert db_session.query(GmailOAuthState).count() == 1
    with pytest.raises(GmailOAuthFlowError, match="oauth_state_invalid"):
        asyncio.run(
            connector.complete_authorization(
                state=older,
                code="old-code",
            )
        )


def test_expiring_access_token_is_refreshed_without_exposing_refresh_token(
    db_session,
):
    user = _user(db_session)
    refresh_calls = 0
    credential_store = InMemoryGmailCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal refresh_calls
        if request.url.path == "/token":
            form = parse_qs(request.content.decode("utf-8"))
            if form["grant_type"] == ["refresh_token"]:
                refresh_calls += 1
            response = _success_handler(request)
            if form["grant_type"] == ["authorization_code"]:
                payload = response.json()
                payload["expires_in"] = 30
                return httpx.Response(200, json=payload)
            return response
        return _success_handler(request)

    connector = _connector(
        db_session,
        handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    asyncio.run(connector.inspect_grant(completion.credential_handle, user_pk=user.id))
    grant = credential_store.snapshot_for_test()[0]
    assert refresh_calls == 1
    assert grant.access_token == "ya29.refreshed-access-token"
    assert REFRESH_TOKEN not in repr(connector)


def test_reauthorization_preserves_existing_refresh_token_when_google_omits_it(
    db_session,
):
    user = _user(db_session)
    exchange_count = 0
    credential_store = InMemoryGmailCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal exchange_count
        response = _success_handler(request)
        if request.url.path == "/token":
            form = parse_qs(request.content.decode("utf-8"))
            if form["grant_type"] == ["authorization_code"]:
                exchange_count += 1
                if exchange_count == 2:
                    payload = response.json()
                    payload.pop("refresh_token")
                    return httpx.Response(200, json=payload)
        return response

    connector = _connector(
        db_session,
        handler,
        credential_store=credential_store,
    )
    first_state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    first = asyncio.run(
        connector.complete_authorization(
            state=first_state,
            code="oauth-code-sentinel",
        )
    )
    second_state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    second = asyncio.run(
        connector.complete_authorization(
            state=second_state,
            code="oauth-code-sentinel",
        )
    )

    grant = credential_store.snapshot_for_test()[0]
    assert first.credential_handle != second.credential_handle
    assert grant.generation == 2
    assert grant.refresh_token == REFRESH_TOKEN


def test_provider_errors_are_folded_to_bounded_codes_without_response_body(
    db_session,
):
    user = _user(db_session)
    leaked = "provider-body-secret-sentinel"

    def failing(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/token"
        return httpx.Response(
            400,
            json={"error": "invalid_grant", "error_description": leaked},
        )

    connector = _connector(db_session, failing)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    with pytest.raises(GmailOAuthFlowError) as caught:
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code="oauth-code-sentinel",
            )
        )
    assert caught.value.code == "invalid_grant"
    assert str(caught.value) == "invalid_grant"
    assert leaked not in str(caught.value)
    assert CLIENT_SECRET not in str(caught.value)


def test_already_invalid_google_token_is_idempotent_revoke_readback(db_session):
    user = _user(db_session)
    credential_store = InMemoryGmailCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        response = _success_handler(request)
        if request.url.path == "/revoke":
            return httpx.Response(400, json={"error": "invalid_token"})
        return response

    connector = _connector(
        db_session,
        handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    asyncio.run(connector.revoke_grant(completion.credential_handle, user_pk=user.id))
    assert credential_store.snapshot_for_test() == ()


def test_revoke_does_not_delete_a_concurrently_reauthorized_grant(db_session):
    user = _user(db_session)
    replacement_refresh_token = "1//concurrent-new-refresh-token"
    credential_store = InMemoryGmailCredentialStore()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/revoke":
            current = credential_store.snapshot_for_test()[0]
            credential_store.put_grant(
                user_pk=user.id,
                google_subject=current.google_subject,
                scopes=current.scopes,
                access_token="ya29.concurrent-new-access-token",
                refresh_token=replacement_refresh_token,
                access_token_expires_at=current.access_token_expires_at,
            )
            return httpx.Response(200)
        return _success_handler(request)

    connector = _connector(
        db_session,
        handler,
        credential_store=credential_store,
    )
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    with pytest.raises(GmailProviderAdapterError) as caught:
        asyncio.run(
            connector.revoke_grant(
                completion.credential_handle,
                user_pk=user.id,
            )
        )
    assert caught.value.code == "credential_changed"
    remaining = credential_store.snapshot_for_test()[0]
    assert remaining.refresh_token == replacement_refresh_token
    assert remaining.generation == 2


def test_oversized_provider_json_is_rejected_before_parsing(db_session):
    user = _user(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(
                200,
                content=b'{"padding":"' + (b"x" * 1_000_001) + b'"}',
                headers={"Content-Type": "application/json"},
            )
        raise AssertionError("oversized token response must stop the flow")

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    with pytest.raises(GmailProviderAdapterError, match="provider_response_too_large"):
        asyncio.run(
            connector.complete_authorization(
                state=state,
                code="oauth-code-sentinel",
            )
        )


def test_untrusted_provider_message_id_cannot_change_gmail_request_path(db_session):
    user = _user(db_session)
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gmail/v1/users/me/messages":
            observed_paths.append(request.url.path)
            return httpx.Response(200, json={"messages": [{"id": "../userinfo"}]})
        if request.url.path.startswith("/gmail/v1/users/me/messages/"):
            raise AssertionError("unsafe provider id reached a second HTTP request")
        return _success_handler(request)

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    with pytest.raises(GmailProviderAdapterError, match="provider_response_invalid"):
        asyncio.run(
            connector.search_messages(
                completion.credential_handle,
                user_pk=user.id,
                query="from:example.com",
                limit=1,
            )
        )
    assert observed_paths == ["/gmail/v1/users/me/messages"]


def test_nested_google_scope_error_is_folded_to_reconnect_code(db_session):
    user = _user(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/gmail/v1/users/me/messages":
            return httpx.Response(
                403,
                json={
                    "error": {
                        "code": 403,
                        "status": "PERMISSION_DENIED",
                        "message": "provider prose must not cross the boundary",
                        "details": [
                            {
                                "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                                "domain": "googleapis.com",
                            }
                        ],
                    }
                },
            )
        return _success_handler(request)

    connector = _connector(db_session, handler)
    state = _state_from_authorization(
        connector.begin_authorization(user_pk=user.id).authorization_url
    )
    completion = asyncio.run(
        connector.complete_authorization(
            state=state,
            code="oauth-code-sentinel",
        )
    )

    with pytest.raises(GmailProviderAdapterError) as caught:
        asyncio.run(
            connector.search_messages(
                completion.credential_handle,
                user_pk=user.id,
                query="from:example.com",
                limit=1,
            )
        )
    assert caught.value.code == "insufficient_scope"
    assert "provider prose" not in str(caught.value)


def test_configuration_gate_requires_complete_valid_https_or_loopback_settings(
    tmp_path,
):
    base = {
        "_env_file": None,
        "APP_EDITION": "community",
        "SECRET_KEY": "test-encryption-key",
        "GMAIL_GOOGLE_OAUTH_CLIENT_ID": CLIENT_ID,
        "GMAIL_GOOGLE_OAUTH_CLIENT_SECRET": CLIENT_SECRET,
        "GMAIL_GOOGLE_OAUTH_REDIRECT_URI": REDIRECT_URI,
        "GMAIL_OAUTH_PRODUCT_RETURN_URI": PRODUCT_RETURN_URI,
        "GMAIL_CREDENTIAL_STORE_FILE": str(tmp_path / "gmail-credentials.enc"),
        "GMAIL_CREDENTIAL_STORE_KEY": "gmail-store-recovery-key-with-32-characters",
    }
    complete = Settings(**base)
    assert build_configured_google_gmail_connector(complete) is not None
    assert CLIENT_SECRET not in repr(complete)
    assert (
        build_configured_google_gmail_connector(
            Settings(**{**base, "GMAIL_GOOGLE_OAUTH_CLIENT_SECRET": ""})
        )
        is None
    )

    cloud = Settings(**{**base, "APP_EDITION": "cloud"})
    assert build_configured_google_gmail_connector(cloud) is None
    assert (
        build_configured_google_gmail_connector(
            cloud,
            credential_store=InMemoryGmailCredentialStore(),
        )
        is not None
    )
    assert (
        build_configured_google_gmail_connector(
            Settings(**{**base, "GMAIL_OAUTH_PRODUCT_RETURN_URI": ""})
        )
        is None
    )
    assert (
        build_configured_google_gmail_connector(
            Settings(
                **{
                    **base,
                    "GMAIL_GOOGLE_OAUTH_REDIRECT_URI": "http://example.com/callback",
                }
            )
        )
        is None
    )
    for unsafe_return_uri in (
        "https://@copilot.example/settings",
        "https://copilot.example/settings#",
        "https://copilot.example:not-a-port/settings",
        "https://copilot.example/set tings",
    ):
        assert (
            build_configured_google_gmail_connector(
                Settings(
                    **{
                        **base,
                        "GMAIL_OAUTH_PRODUCT_RETURN_URI": unsafe_return_uri,
                    }
                )
            )
            is None
        )
    assert (
        build_configured_google_gmail_connector(
            Settings(
                **{
                    **base,
                    "GMAIL_GOOGLE_OAUTH_REDIRECT_URI": (
                        "http://localhost:8000/api/v1/integrations/gmail/callback"
                    ),
                }
            )
        )
        is not None
    )
    assert (
        build_configured_google_gmail_connector(
            Settings(
                **{
                    **base,
                    "ENVIRONMENT": "prod",
                    "GMAIL_GOOGLE_OAUTH_REDIRECT_URI": (
                        "http://localhost:8000/api/v1/integrations/gmail/callback"
                    ),
                }
            )
        )
        is None
    )
    assert (
        build_configured_google_gmail_connector(
            Settings(
                **{
                    **base,
                    "GMAIL_OAUTH_PRODUCT_RETURN_URI": (
                        "https://user:password@copilot.example/settings#fragment"
                    ),
                }
            )
        )
        is None
    )


def test_product_return_url_allows_only_fixed_outcome_and_error_codes(db_session):
    connector = _connector(db_session, _success_handler)
    success = connector.product_return_url(outcome="connected")
    failure = connector.product_return_url(
        outcome="failed",
        error_code="oauth_state_expired",
    )
    folded = connector.product_return_url(
        outcome="../../evil",
        error_code="secret-provider-prose",
    )

    assert parse_qs(urlsplit(success).query) == {"gmail_oauth_outcome": ["connected"]}
    assert parse_qs(urlsplit(failure).query) == {
        "gmail_oauth_outcome": ["failed"],
        "gmail_oauth_error": ["oauth_state_expired"],
    }
    assert parse_qs(urlsplit(folded).query) == {
        "gmail_oauth_outcome": ["failed"],
        "gmail_oauth_error": ["provider_error"],
    }
    assert "secret-provider-prose" not in folded


def test_default_http_client_disables_environment_proxy_and_redirects(
    db_session,
    monkeypatch,
):
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, _method, _url, **_kwargs):
            return httpx.Response(200, json={})

    monkeypatch.setattr(
        "app.services.google_gmail_connector.httpx.AsyncClient",
        FakeClient,
    )
    connector = GoogleGmailConnector(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        product_return_uri=PRODUCT_RETURN_URI,
        state_ttl_seconds=600,
        timeout_seconds=5,
        credential_store=InMemoryGmailCredentialStore(),
        session_factory=lambda: NoCloseSession(db_session),
    )
    asyncio.run(connector._request("GET", "https://gmail.googleapis.com/test"))

    assert captured["trust_env"] is False
    assert captured["follow_redirects"] is False
    assert isinstance(captured["timeout"], httpx.Timeout)
