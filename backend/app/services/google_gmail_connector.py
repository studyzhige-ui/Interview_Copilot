"""Real Google OAuth credential broker and Gmail read adapter.

This module is the sole execution boundary allowed to see Google client
credentials or decrypted user tokens.  It deliberately implements one
provider-specific connector instead of introducing a generic Connection or
Secret domain.  Public APIs and Tool results receive only safe account facts
and bounded Gmail message summaries.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.secrets import decrypt_secret, encrypt_secret
from app.db.database import SessionLocal
from app.db.types import as_utc, utc_now
from app.models.gmail_integration import GmailOAuthState
from app.schemas.gmail_integration import GmailMessageSummary
from app.schemas.gmail_observation import (
    GmailIncrementalBatch,
    GmailIncrementalMessage,
)
from app.services.gmail_integration_service import (
    GMAIL_READONLY_SCOPE,
    GmailGrantInspection,
    GmailIntegrationError,
    GmailProviderAdapterError,
)
from app.services.gmail_credential_store import (
    EncryptedFileGmailCredentialStore,
    GmailCredentialConflictError,
    GmailCredentialGrant,
    GmailCredentialNotFoundError,
    GmailCredentialStore,
    GmailCredentialStoreError,
    GmailCredentialStoreUnavailableError,
    GmailRefreshTokenMissingError,
)


_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
_GMAIL_HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"
_GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
_IDENTITY_SCOPES = frozenset({"openid", "email"})
_REQUESTED_SCOPES = frozenset({GMAIL_READONLY_SCOPE, *_IDENTITY_SCOPES})
_ACCESS_EXPIRY_SKEW = timedelta(seconds=60)
_MAX_PROVIDER_JSON_BYTES = 1_000_000
_OAUTH_OUTCOMES = frozenset({"connected", "failed"})
_OAUTH_ERROR_CODES = frozenset(
    {
        "credential_store_unavailable",
        "gmail_readonly_scope_required",
        "google_email_unverified",
        "invalid_grant",
        "oauth_authorization_denied",
        "oauth_code_invalid",
        "oauth_exchange_failed",
        "oauth_state_expired",
        "oauth_state_invalid",
        "provider_error",
        "provider_timeout",
        "provider_unavailable",
        "refresh_token_missing",
    }
)

SessionFactory = Callable[[], Session]
HttpClientFactory = Callable[[], httpx.AsyncClient]


class GmailOAuthFlowError(GmailIntegrationError):
    """A bounded OAuth lifecycle failure safe for API error projection."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = bool(retryable)
        super().__init__(code)


@dataclass(frozen=True)
class GmailOAuthAuthorization:
    authorization_url: str
    expires_in_seconds: int
    # Internal browser binding for the callback cookie. It is the same
    # high-entropy OAuth state already embedded in ``authorization_url`` and
    # is never copied into the JSON response model.
    state_binding: str = field(repr=False)


@dataclass(frozen=True)
class GmailOAuthCompletion:
    """Internal callback result; never serialize this object to a client."""

    user_pk: int
    credential_handle: str = field(repr=False)


@dataclass(frozen=True)
class _ClaimedOAuthState:
    user_pk: int
    code_verifier: str = field(repr=False)


class GoogleGmailConnector:
    """Controlled OAuth broker plus the real ``GmailProviderAdapter``."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        product_return_uri: str,
        state_ttl_seconds: int,
        timeout_seconds: float,
        credential_store: GmailCredentialStore,
        session_factory: SessionFactory = SessionLocal,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._product_return_uri = product_return_uri
        self._state_ttl_seconds = state_ttl_seconds
        self._credential_store = credential_store
        self._session_factory = session_factory
        timeout = httpx.Timeout(
            timeout_seconds,
            connect=min(timeout_seconds, 10.0),
            pool=min(timeout_seconds, 5.0),
        )
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        )

    def begin_authorization(self, *, user_pk: int) -> GmailOAuthAuthorization:
        """Persist a hashed, one-time CSRF state and return Google's URL."""

        raw_state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = _pkce_challenge(code_verifier)
        now = utc_now()
        row = GmailOAuthState(
            user_id=user_pk,
            state_digest=_state_digest(raw_state),
            code_verifier_ciphertext=encrypt_secret(code_verifier),
            expires_at=now + timedelta(seconds=self._state_ttl_seconds),
            created_at=now,
        )
        with self._session_factory() as db:
            try:
                # One pending grant attempt per user. Starting again makes the
                # older browser flow invalid and keeps abandoned state storage
                # strictly bounded even when no callback arrives.
                db.query(GmailOAuthState).filter(
                    GmailOAuthState.user_id == user_pk
                ).delete(synchronize_session=False)
                db.add(row)
                db.commit()
            except Exception:
                db.rollback()
                raise GmailOAuthFlowError("oauth_state_store_failed") from None

        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(sorted(_REQUESTED_SCOPES)),
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
                "state": raw_state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return GmailOAuthAuthorization(
            authorization_url=f"{_AUTHORIZE_URL}?{query}",
            expires_in_seconds=self._state_ttl_seconds,
            state_binding=raw_state,
        )

    @property
    def callback_cookie_path(self) -> str:
        """Exact callback path for the short-lived browser-binding cookie."""

        return urlsplit(self._redirect_uri).path or "/"

    @property
    def callback_cookie_secure(self) -> bool:
        """HTTPS deployments require Secure; loopback HTTP remains usable."""

        return urlsplit(self._redirect_uri).scheme == "https"

    def product_return_url(
        self,
        *,
        outcome: str,
        error_code: str | None = None,
    ) -> str:
        """Build the browser return URL from fixed, non-secret enum values."""

        safe_outcome = outcome if outcome in _OAUTH_OUTCOMES else "failed"
        safe_error = (
            error_code if error_code in _OAUTH_ERROR_CODES else "provider_error"
        )
        parsed = urlsplit(self._product_return_uri)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key not in {"gmail_oauth_outcome", "gmail_oauth_error"}
        ]
        query.append(("gmail_oauth_outcome", safe_outcome))
        if safe_outcome == "failed":
            query.append(("gmail_oauth_error", safe_error))
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
        )

    async def complete_authorization(
        self,
        *,
        state: str,
        code: str | None,
        provider_error: str | None = None,
    ) -> GmailOAuthCompletion:
        """Consume state exactly once, exchange code, verify and encrypt grant."""

        claimed_state = self._claim_oauth_state(state)
        if provider_error is not None:
            raise GmailOAuthFlowError("oauth_authorization_denied")
        normalized_code = _bounded_secret(code, "oauth_code_invalid", 4096)
        token_payload = await self._token_request(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": normalized_code,
                "code_verifier": claimed_state.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self._redirect_uri,
            },
            flow_error_code="oauth_exchange_failed",
        )
        access_token = _bounded_secret(
            token_payload.get("access_token"),
            "oauth_exchange_failed",
            8192,
        )
        refresh_token = _optional_secret(token_payload.get("refresh_token"), 8192)
        expires_at = _expires_at(token_payload.get("expires_in"))
        raw_scope = token_payload.get("scope")
        # OAuth permits omitting `scope` when it is identical to the request.
        # A present value remains authoritative so partial grants fail closed.
        scopes = _REQUESTED_SCOPES if raw_scope is None else _scope_set(raw_scope)
        if GMAIL_READONLY_SCOPE not in scopes:
            raise GmailOAuthFlowError("gmail_readonly_scope_required")

        identity = await self._identity_for_access_token(access_token)
        handle = self._store_grant(
            user_pk=claimed_state.user_pk,
            google_subject=identity.google_subject,
            scopes=scopes,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=expires_at,
        )
        return GmailOAuthCompletion(
            user_pk=claimed_state.user_pk,
            credential_handle=handle,
        )

    async def inspect_grant(
        self,
        credential_handle: str,
        *,
        user_pk: int,
    ) -> GmailGrantInspection:
        snapshot = self._load_grant(credential_handle, user_pk=user_pk)
        access_token = await self._access_token(snapshot)
        try:
            identity = await self._identity_for_access_token(access_token)
        except GmailProviderAdapterError as exc:
            if exc.code != "invalid_token":
                raise
            snapshot = self._load_grant(credential_handle, user_pk=user_pk)
            access_token = await self._refresh_access_token(snapshot)
            identity = await self._identity_for_access_token(access_token)
        if identity.google_subject != snapshot.google_subject:
            raise GmailProviderAdapterError("invalid_grant")
        latest = self._load_grant(credential_handle, user_pk=user_pk)
        _ensure_same_grant(snapshot, latest)
        return GmailGrantInspection(
            google_subject=identity.google_subject,
            account_email=identity.account_email,
            granted_scopes=latest.scopes,
        )

    async def revoke_grant(self, credential_handle: str, *, user_pk: int) -> None:
        snapshot = self._load_grant(credential_handle, user_pk=user_pk)
        refresh_token = snapshot.refresh_token
        if not refresh_token:
            raise GmailProviderAdapterError("invalid_grant")
        response = await self._request(
            "POST",
            _REVOKE_URL,
            data={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            error = _provider_http_error(response, default_code="revoke_failed")
            # Google's documented invalid_token response means no usable grant
            # remains. Treat that read-back as idempotent revocation success.
            if error.code != "invalid_token":
                raise error

        try:
            self._credential_store.delete_grant(
                credential_handle,
                user_pk=user_pk,
                expected_generation=snapshot.generation,
            )
        except (GmailCredentialNotFoundError, GmailCredentialConflictError):
            raise GmailProviderAdapterError(
                "credential_changed",
                retryable=True,
            ) from None
        except GmailCredentialStoreError:
            raise GmailProviderAdapterError(
                "credential_store_unavailable",
                retryable=True,
            ) from None

    async def search_messages(
        self,
        credential_handle: str,
        *,
        user_pk: int,
        query: str,
        limit: int,
    ) -> list[GmailMessageSummary]:
        if not 1 <= limit <= 10:
            raise GmailProviderAdapterError("invalid_request")
        snapshot = self._load_grant(credential_handle, user_pk=user_pk)
        listing = await self._authorized_get_json(
            snapshot,
            _GMAIL_MESSAGES_URL,
            params={"q": query, "maxResults": limit},
        )
        raw_messages = listing.get("messages", [])
        if not isinstance(raw_messages, list):
            raise GmailProviderAdapterError("provider_response_invalid")

        # A list call may have refreshed the access token. Reload once so the
        # bounded detail reads do not repeatedly refresh from a stale snapshot.
        latest = self._load_grant(credential_handle, user_pk=user_pk)
        _ensure_same_grant(snapshot, latest)
        snapshot = latest

        summaries: list[GmailMessageSummary] = []
        for raw_message in raw_messages[:limit]:
            if not isinstance(raw_message, dict):
                raise GmailProviderAdapterError("provider_response_invalid")
            # The provider response is external input. Keep its identifier a
            # single URL segment before interpolating it into the fixed Gmail
            # endpoint so a malformed response cannot alter the request path.
            message_id = _bounded_gmail_id(raw_message.get("id"))
            detail = await self._authorized_get_json(
                snapshot,
                f"{_GMAIL_MESSAGES_URL}/{message_id}",
                params=[
                    ("format", "metadata"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "Subject"),
                ],
            )
            summaries.append(_message_summary(detail))
        _ensure_same_grant(
            snapshot,
            self._load_grant(credential_handle, user_pk=user_pk),
        )
        return summaries

    async def read_incremental_messages(
        self,
        credential_handle: str,
        *,
        user_pk: int,
        cursor: str | None,
        limit: int,
    ) -> GmailIncrementalBatch:
        """Read a bounded Gmail History increment without persisting a cursor."""

        if not 1 <= limit <= 100:
            raise GmailProviderAdapterError("invalid_request")
        snapshot = self._load_grant(credential_handle, user_pk=user_pk)
        if cursor is None:
            profile = await self._authorized_get_json(
                snapshot,
                _GMAIL_PROFILE_URL,
                params={},
            )
            cursor_after = _bounded_gmail_id(profile.get("historyId"))
            _ensure_same_grant(
                snapshot,
                self._load_grant(credential_handle, user_pk=user_pk),
            )
            return GmailIncrementalBatch(
                cursor_before=None,
                cursor_after=cursor_after,
                initialized_cursor=True,
                messages=[],
            )

        cursor_before = _bounded_gmail_id(cursor)
        latest = self._load_grant(credential_handle, user_pk=user_pk)
        _ensure_same_grant(snapshot, latest)
        snapshot = latest
        occurrences, cursor_after = await self._history_occurrences(
            snapshot,
            cursor=cursor_before,
            limit=limit,
        )
        latest = self._load_grant(credential_handle, user_pk=user_pk)
        _ensure_same_grant(snapshot, latest)
        snapshot = latest

        messages: list[GmailIncrementalMessage] = []
        for message_id, thread_id, history_id in occurrences:
            try:
                detail = await self._authorized_get_json(
                    snapshot,
                    f"{_GMAIL_MESSAGES_URL}/{message_id}",
                    params=[
                        ("format", "metadata"),
                        ("metadataHeaders", "From"),
                        ("metadataHeaders", "Subject"),
                    ],
                    default_error_code="gmail_message_unavailable",
                )
            except GmailProviderAdapterError as exc:
                if exc.code != "gmail_message_unavailable":
                    raise
                # The History occurrence is still a real provider fact.  Save
                # an explicit tombstone snapshot and advance atomically rather
                # than retrying a message that was deleted after delivery.
                messages.append(
                    GmailIncrementalMessage(
                        message_id=message_id,
                        thread_id=thread_id,
                        history_id=history_id,
                        content_available=False,
                    )
                )
                continue
            summary = _message_summary(detail)
            if summary.message_id != message_id or summary.thread_id != thread_id:
                raise GmailProviderAdapterError("provider_response_invalid")
            messages.append(
                GmailIncrementalMessage(
                    message_id=summary.message_id,
                    thread_id=summary.thread_id,
                    history_id=history_id,
                    content_available=True,
                    received_at=summary.received_at,
                    from_hint=summary.from_hint,
                    subject=summary.subject,
                    snippet=summary.snippet,
                )
            )
        _ensure_same_grant(
            snapshot,
            self._load_grant(credential_handle, user_pk=user_pk),
        )
        return GmailIncrementalBatch(
            cursor_before=cursor_before,
            cursor_after=cursor_after,
            initialized_cursor=False,
            messages=messages,
        )

    async def _history_occurrences(
        self,
        snapshot: GmailCredentialGrant,
        *,
        cursor: str,
        limit: int,
    ) -> tuple[list[tuple[str, str, str]], str]:
        """Return complete History records up to a bounded message limit.

        We never advance past a partially consumed History record.  Re-reading
        an already saved record is harmless because Observation persistence is
        keyed by the provider message identity.
        """

        page_token: str | None = None
        cursor_after = cursor
        occurrences: dict[str, tuple[str, str]] = {}
        pages = 0
        provider_head: str | None = None
        while pages < 4:
            params: list[tuple[str, Any]] = [
                ("startHistoryId", cursor),
                ("historyTypes", "messageAdded"),
                ("maxResults", 100),
            ]
            if page_token is not None:
                params.append(("pageToken", page_token))
            payload = await self._authorized_get_json(
                snapshot,
                _GMAIL_HISTORY_URL,
                params=params,
                default_error_code="gmail_history_unavailable",
            )
            pages += 1
            raw_history = payload.get("history", [])
            if not isinstance(raw_history, list):
                raise GmailProviderAdapterError("provider_response_invalid")
            provider_head = _optional_gmail_id(payload.get("historyId"))
            stopped_before_record = False
            for raw_record in raw_history:
                if not isinstance(raw_record, dict):
                    raise GmailProviderAdapterError("provider_response_invalid")
                history_id = _bounded_gmail_id(raw_record.get("id"))
                record_entries = _message_added_entries(raw_record)
                new_entries = [
                    entry for entry in record_entries if entry[0] not in occurrences
                ]
                if len(new_entries) > limit:
                    # Never advance over provider data we did not snapshot.
                    # The typed failure is preferable to a silent cursor gap.
                    raise GmailProviderAdapterError("history_batch_too_large")
                if len(occurrences) + len(new_entries) > limit:
                    stopped_before_record = True
                    break
                for message_id, thread_id in new_entries:
                    occurrences[message_id] = (thread_id, history_id)
                cursor_after = history_id
            if stopped_before_record:
                break
            raw_next = payload.get("nextPageToken")
            if raw_next is None:
                if provider_head is not None:
                    cursor_after = provider_head
                break
            page_token = _bounded_identity(raw_next, 2_048)
        return [
            (message_id, thread_id, history_id)
            for message_id, (thread_id, history_id) in occurrences.items()
        ], cursor_after

    def _claim_oauth_state(self, raw_state: str) -> _ClaimedOAuthState:
        normalized = _bounded_secret(raw_state, "oauth_state_invalid", 512)
        if len(normalized) < 20:
            raise GmailOAuthFlowError("oauth_state_invalid")
        digest = _state_digest(normalized)
        now = utc_now()
        with self._session_factory() as db:
            row = (
                db.query(GmailOAuthState)
                .filter(GmailOAuthState.state_digest == digest)
                .with_for_update()
                .one_or_none()
            )
            if row is None:
                raise GmailOAuthFlowError("oauth_state_invalid")
            expired = as_utc(row.expires_at) <= now
            user_pk = int(row.user_id)
            code_verifier = decrypt_secret(row.code_verifier_ciphertext)
            # The digest has no product/history consumer. Deleting it in the
            # locked claim transaction is both the one-time-use guarantee and
            # the minimum-retention policy; a concurrent replay observes none.
            db.delete(row)
            db.commit()
        if expired:
            raise GmailOAuthFlowError("oauth_state_expired")
        if not code_verifier or not 43 <= len(code_verifier) <= 128:
            raise GmailOAuthFlowError("oauth_state_invalid")
        return _ClaimedOAuthState(
            user_pk=user_pk,
            code_verifier=code_verifier,
        )

    async def _identity_for_access_token(
        self,
        access_token: str,
    ) -> GmailGrantInspection:
        response = await self._request(
            "GET",
            _USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            raise _provider_http_error(response, default_code="identity_read_failed")
        payload = _json_object(response)
        subject = _bounded_identity(payload.get("sub"), 255)
        email = _bounded_identity(payload.get("email"), 320)
        if payload.get("email_verified") is not True:
            raise GmailOAuthFlowError("google_email_unverified")
        return GmailGrantInspection(
            google_subject=subject,
            account_email=email,
            granted_scopes=frozenset(),
        )

    def _store_grant(
        self,
        *,
        user_pk: int,
        google_subject: str,
        scopes: frozenset[str],
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime,
    ) -> str:
        try:
            grant = self._credential_store.put_grant(
                user_pk=user_pk,
                google_subject=google_subject,
                scopes=scopes,
                access_token=access_token,
                refresh_token=refresh_token,
                access_token_expires_at=access_token_expires_at,
            )
            return grant.handle
        except GmailRefreshTokenMissingError:
            raise GmailOAuthFlowError("refresh_token_missing") from None
        except GmailCredentialStoreError:
            raise GmailOAuthFlowError(
                "credential_store_unavailable",
                retryable=True,
            ) from None

    def _load_grant(
        self,
        credential_handle: str,
        *,
        user_pk: int,
    ) -> GmailCredentialGrant:
        try:
            return self._credential_store.get_grant(
                credential_handle,
                user_pk=user_pk,
            )
        except GmailCredentialNotFoundError:
            raise GmailProviderAdapterError("invalid_grant") from None
        except GmailCredentialStoreError:
            raise GmailProviderAdapterError(
                "credential_store_unavailable",
                retryable=True,
            ) from None

    async def _access_token(self, snapshot: GmailCredentialGrant) -> str:
        token = snapshot.access_token
        if not token:
            raise GmailProviderAdapterError("invalid_grant")
        if snapshot.access_token_expires_at > utc_now() + _ACCESS_EXPIRY_SKEW:
            return token
        return await self._refresh_access_token(snapshot)

    async def _refresh_access_token(self, snapshot: GmailCredentialGrant) -> str:
        refresh_token = snapshot.refresh_token
        if not refresh_token:
            raise GmailProviderAdapterError("invalid_grant")
        payload = await self._token_request(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            flow_error_code="refresh_failed",
            adapter_error=True,
        )
        access_token = _bounded_secret(
            payload.get("access_token"),
            "refresh_failed",
            8192,
        )
        try:
            expires_at = _expires_at(payload.get("expires_in"))
            refreshed_scopes = _scope_set(payload.get("scope"), required=False)
        except GmailOAuthFlowError:
            raise GmailProviderAdapterError("provider_response_invalid") from None

        try:
            self._credential_store.compare_and_swap_refresh(
                snapshot.handle,
                user_pk=snapshot.user_pk,
                expected_generation=snapshot.generation,
                access_token=access_token,
                access_token_expires_at=expires_at,
                scopes=refreshed_scopes or None,
            )
        except (GmailCredentialNotFoundError, GmailCredentialConflictError):
            # A reconnect replaced this grant while refresh was in flight.
            # The stale access token is never written over the new grant.
            raise GmailProviderAdapterError(
                "credential_changed",
                retryable=True,
            ) from None
        except GmailCredentialStoreError:
            raise GmailProviderAdapterError(
                "credential_store_unavailable",
                retryable=True,
            ) from None
        return access_token

    async def _authorized_get_json(
        self,
        snapshot: GmailCredentialGrant,
        url: str,
        *,
        params: Any,
        default_error_code: str = "gmail_request_failed",
    ) -> dict[str, Any]:
        token = await self._access_token(snapshot)
        response = await self._request(
            "GET",
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code == 401:
            snapshot = self._load_grant(
                snapshot.handle,
                user_pk=snapshot.user_pk,
            )
            token = await self._refresh_access_token(snapshot)
            response = await self._request(
                "GET",
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        if response.status_code != 200:
            raise _provider_http_error(response, default_code=default_error_code)
        return _json_object(response)

    async def _token_request(
        self,
        data: dict[str, str],
        *,
        flow_error_code: str,
        adapter_error: bool = False,
    ) -> dict[str, Any]:
        response = await self._request(
            "POST",
            _TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            error = _provider_http_error(response, default_code=flow_error_code)
            if adapter_error:
                raise error
            raise GmailOAuthFlowError(error.code, retryable=error.retryable)
        return _json_object(response)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            async with self._http_client_factory() as client:
                return await client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            raise GmailProviderAdapterError(
                "provider_timeout", retryable=True
            ) from None
        except httpx.RequestError:
            raise GmailProviderAdapterError(
                "provider_unavailable", retryable=True
            ) from None


def build_configured_google_gmail_connector(
    configured_settings: Settings = settings,
    *,
    credential_store: GmailCredentialStore | None = None,
    session_factory: SessionFactory = SessionLocal,
    http_client_factory: HttpClientFactory | None = None,
) -> GoogleGmailConnector | None:
    """Return a real connector only for a complete, valid deployment config."""

    client_id = configured_settings.GMAIL_GOOGLE_OAUTH_CLIENT_ID.strip()
    client_secret = (
        configured_settings.GMAIL_GOOGLE_OAUTH_CLIENT_SECRET.get_secret_value().strip()
    )
    redirect_uri = configured_settings.GMAIL_GOOGLE_OAUTH_REDIRECT_URI.strip()
    product_return_uri = configured_settings.GMAIL_OAUTH_PRODUCT_RETURN_URI.strip()
    state_encryption_key = configured_settings.SECRET_KEY.strip()
    present = (
        client_id,
        client_secret,
        redirect_uri,
        product_return_uri,
        state_encryption_key,
    )
    if not all(present):
        return None
    if not _safe_redirect_uri(
        redirect_uri,
        environment=configured_settings.ENVIRONMENT,
    ) or not _safe_redirect_uri(
        product_return_uri,
        environment=configured_settings.ENVIRONMENT,
    ):
        return None
    resolved_store = credential_store
    if resolved_store is None:
        # Hosted Cloud must inject a real external secret broker. A local file
        # on an ephemeral web instance is neither durable nor an honest cloud
        # credential boundary, so incomplete deployments remain unavailable.
        if configured_settings.APP_EDITION == "cloud":
            return None
        store_path = configured_settings.GMAIL_CREDENTIAL_STORE_FILE.strip()
        store_key = (
            configured_settings.GMAIL_CREDENTIAL_STORE_KEY.get_secret_value().strip()
        )
        if not store_path or not store_key:
            return None
        try:
            resolved_store = EncryptedFileGmailCredentialStore(
                store_path,
                encryption_secret=store_key,
            )
        except (ValueError, GmailCredentialStoreUnavailableError):
            return None
    return GoogleGmailConnector(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        product_return_uri=product_return_uri,
        state_ttl_seconds=configured_settings.GMAIL_OAUTH_STATE_TTL_SECONDS,
        timeout_seconds=configured_settings.GMAIL_PROVIDER_TIMEOUT_SECONDS,
        credential_store=resolved_store,
        session_factory=session_factory,
        http_client_factory=http_client_factory,
    )


def _safe_redirect_uri(value: str, *, environment: str) -> bool:
    try:
        parsed = urlsplit(value)
        # Access ``port`` as part of parsing so malformed values such as
        # ``https://host:not-a-port`` also fail the deployment gate.
        parsed.port
        if (
            parsed.username is not None
            or parsed.password is not None
            or "#" in value
            or not parsed.hostname
            or any(character.isspace() for character in value)
        ):
            return False
        if parsed.scheme == "https":
            return True
        local_environment = (environment or "local").strip().lower() == "local"
        return (
            local_environment
            and parsed.scheme == "http"
            and parsed.hostname
            in {
                "localhost",
                "127.0.0.1",
                "::1",
            }
        )
    except ValueError:
        return False


def _state_digest(raw_state: str) -> str:
    return hashlib.sha256(raw_state.encode("utf-8")).hexdigest()


def _pkce_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _ensure_same_grant(
    original: GmailCredentialGrant,
    latest: GmailCredentialGrant,
) -> None:
    if (
        latest.handle != original.handle
        or latest.google_subject != original.google_subject
    ):
        raise GmailProviderAdapterError("credential_changed", retryable=True)


def _bounded_secret(value: Any, code: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise GmailOAuthFlowError(code)
    return value


def _optional_secret(value: Any, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise GmailOAuthFlowError("oauth_exchange_failed")
    return value


def _bounded_identity(value: Any, max_length: int) -> str:
    if not isinstance(value, str):
        raise GmailProviderAdapterError("provider_response_invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > max_length:
        raise GmailProviderAdapterError("provider_response_invalid")
    return normalized


def _expires_at(value: Any) -> datetime:
    if isinstance(value, bool):
        raise GmailOAuthFlowError("oauth_token_expiry_invalid")
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        raise GmailOAuthFlowError("oauth_token_expiry_invalid") from None
    if not 30 <= seconds <= 86_400:
        raise GmailOAuthFlowError("oauth_token_expiry_invalid")
    return utc_now() + timedelta(seconds=seconds)


def _scope_set(value: Any, *, required: bool = True) -> frozenset[str]:
    if value is None and not required:
        return frozenset()
    if not isinstance(value, str):
        raise GmailOAuthFlowError("oauth_scope_invalid")
    scopes = frozenset(part for part in value.split() if part)
    if not scopes or len(scopes) > 20 or any(len(scope) > 300 for scope in scopes):
        raise GmailOAuthFlowError("oauth_scope_invalid")
    return scopes


def _json_object(response: httpx.Response) -> dict[str, Any]:
    if len(response.content) > _MAX_PROVIDER_JSON_BYTES:
        raise GmailProviderAdapterError("provider_response_too_large")
    try:
        payload = response.json()
    except ValueError:
        raise GmailProviderAdapterError("provider_response_invalid") from None
    if not isinstance(payload, dict):
        raise GmailProviderAdapterError("provider_response_invalid")
    return payload


def _provider_http_error(
    response: httpx.Response,
    *,
    default_code: str,
) -> GmailProviderAdapterError:
    provider_code = ""
    if len(response.content) <= _MAX_PROVIDER_JSON_BYTES:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                raw_error = payload.get("error")
                if isinstance(raw_error, str):
                    provider_code = raw_error.strip().lower()
                elif isinstance(raw_error, dict):
                    status = raw_error.get("status")
                    if isinstance(status, str) and status == "UNAUTHENTICATED":
                        provider_code = "invalid_token"
                    details = raw_error.get("details")
                    if isinstance(details, list):
                        reasons = {
                            detail.get("reason")
                            for detail in details[:20]
                            if isinstance(detail, dict)
                            and isinstance(detail.get("reason"), str)
                        }
                        if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in reasons:
                            provider_code = "insufficient_scope"
        except ValueError:
            pass
    authenticate = response.headers.get("www-authenticate", "")[:2048].lower()
    if "insufficient_scope" in authenticate:
        provider_code = "insufficient_scope"
    elif "invalid_token" in authenticate:
        provider_code = "invalid_token"
    elif response.status_code == 401 and default_code in {
        "gmail_request_failed",
        "identity_read_failed",
    }:
        provider_code = "invalid_token"
    if response.status_code == 404 and default_code == "gmail_history_unavailable":
        return GmailProviderAdapterError("history_cursor_expired")
    if response.status_code == 404 and default_code == "gmail_message_unavailable":
        return GmailProviderAdapterError("gmail_message_unavailable")
    if default_code == "gmail_message_unavailable":
        default_code = "gmail_request_failed"
    code_map = {
        "invalid_grant": "invalid_grant",
        "invalid_token": "invalid_token",
        "insufficient_scope": "insufficient_scope",
        "access_denied": "access_denied",
    }
    code = code_map.get(provider_code, default_code)
    retryable = response.status_code == 429 or 500 <= response.status_code < 600
    return GmailProviderAdapterError(code, retryable=retryable)


def _message_summary(payload: dict[str, Any]) -> GmailMessageSummary:
    message_id = _bounded_gmail_id(payload.get("id"))
    thread_id = _bounded_gmail_id(payload.get("threadId"))
    headers: dict[str, str] = {}
    raw_headers = (payload.get("payload") or {}).get("headers", [])
    if isinstance(raw_headers, list):
        for item in raw_headers:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and isinstance(value, str):
                headers[name.strip().lower()] = value
    received_at: datetime | None = None
    raw_internal_date = payload.get("internalDate")
    try:
        received_at = datetime.fromtimestamp(int(raw_internal_date) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    return GmailMessageSummary(
        message_id=message_id,
        thread_id=thread_id,
        received_at=received_at,
        from_hint=_external_text(headers.get("from"), 320),
        subject=_external_text(headers.get("subject"), 500),
        snippet=_external_text(payload.get("snippet"), 500),
    )


def _external_text(value: Any, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    normalized = " ".join(value.split())
    return normalized[:max_length]


def _bounded_gmail_id(value: Any) -> str:
    normalized = _bounded_identity(value, 256)
    if not all(
        character.isascii() and (character.isalnum() or character in "_-")
        for character in normalized
    ):
        raise GmailProviderAdapterError("provider_response_invalid")
    return normalized


def _optional_gmail_id(value: Any) -> str | None:
    if value is None:
        return None
    return _bounded_gmail_id(value)


def _message_added_entries(history_record: dict[str, Any]) -> list[tuple[str, str]]:
    raw_added = history_record.get("messagesAdded", [])
    if not isinstance(raw_added, list):
        raise GmailProviderAdapterError("provider_response_invalid")
    entries: list[tuple[str, str]] = []
    for item in raw_added:
        if not isinstance(item, dict) or not isinstance(item.get("message"), dict):
            raise GmailProviderAdapterError("provider_response_invalid")
        message_id = _bounded_gmail_id(item["message"].get("id"))
        thread_id = _bounded_gmail_id(item["message"].get("threadId"))
        if all(existing_id != message_id for existing_id, _ in entries):
            entries.append((message_id, thread_id))
    return entries


__all__ = [
    "GmailOAuthAuthorization",
    "GmailOAuthCompletion",
    "GmailOAuthFlowError",
    "GoogleGmailConnector",
    "build_configured_google_gmail_connector",
]
