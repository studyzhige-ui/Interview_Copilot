"""Gmail-only credential broker port and local encrypted implementation.

OAuth tokens are deliberately outside the application database.  This module
is provider-specific: it is not a generic Connection or Secret domain and no
product schema exposes its records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock, Timeout


_SCHEMA_VERSION = 1
_MAX_STORE_BYTES = 5_000_000
_HANDLE_PREFIX = "gch_"


class GmailCredentialStoreError(RuntimeError):
    """Base error for the private Gmail credential boundary."""


class GmailCredentialNotFoundError(GmailCredentialStoreError):
    """The handle does not exist or is not owned by the supplied user."""


class GmailCredentialConflictError(GmailCredentialStoreError):
    """The expected grant generation is no longer current."""


class GmailRefreshTokenMissingError(GmailCredentialStoreError):
    """A new grant omitted the refresh token and none can be inherited."""


class GmailCredentialStoreUnavailableError(GmailCredentialStoreError):
    """The configured broker cannot safely read or durably write grants."""


@dataclass(frozen=True)
class GmailCredentialGrant:
    handle: str = field(repr=False)
    user_pk: int
    google_subject: str
    scopes: frozenset[str]
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_token_expires_at: datetime
    generation: int
    created_at: datetime
    updated_at: datetime


class GmailCredentialStore(Protocol):
    """Provider-specific port used by the Google Gmail adapter only."""

    def put_grant(
        self,
        *,
        user_pk: int,
        google_subject: str,
        scopes: frozenset[str],
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime,
    ) -> GmailCredentialGrant: ...

    def get_grant(self, handle: str, *, user_pk: int) -> GmailCredentialGrant: ...

    def compare_and_swap_refresh(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
        access_token: str,
        access_token_expires_at: datetime,
        scopes: frozenset[str] | None = None,
    ) -> GmailCredentialGrant: ...

    def delete_grant(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
    ) -> None: ...


class InMemoryGmailCredentialStore:
    """Deterministic process-local fake for focused tests only."""

    def __init__(self) -> None:
        self._records: dict[str, GmailCredentialGrant] = {}
        self._generations_by_user: dict[int, int] = {}
        self._lock = threading.RLock()

    def put_grant(
        self,
        *,
        user_pk: int,
        google_subject: str,
        scopes: frozenset[str],
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime,
    ) -> GmailCredentialGrant:
        with self._lock:
            previous = _grant_for_user(self._records, user_pk)
            resolved_refresh = _resolved_refresh_token(
                previous,
                google_subject=google_subject,
                refresh_token=refresh_token,
            )
            now = datetime.now(UTC)
            generation = self._generations_by_user.get(user_pk, 0) + 1
            grant = GmailCredentialGrant(
                handle=_new_handle(),
                user_pk=user_pk,
                google_subject=google_subject,
                scopes=frozenset(scopes),
                access_token=access_token,
                refresh_token=resolved_refresh,
                access_token_expires_at=_as_utc(access_token_expires_at),
                generation=generation,
                created_at=now,
                updated_at=now,
            )
            if previous is not None:
                self._records.pop(previous.handle, None)
            self._records[grant.handle] = grant
            self._generations_by_user[user_pk] = generation
            return grant

    def get_grant(self, handle: str, *, user_pk: int) -> GmailCredentialGrant:
        with self._lock:
            return _owned_grant(self._records, handle, user_pk=user_pk)

    def compare_and_swap_refresh(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
        access_token: str,
        access_token_expires_at: datetime,
        scopes: frozenset[str] | None = None,
    ) -> GmailCredentialGrant:
        with self._lock:
            current = _owned_grant(self._records, handle, user_pk=user_pk)
            _require_generation(current, expected_generation)
            updated = replace(
                current,
                access_token=access_token,
                access_token_expires_at=_as_utc(access_token_expires_at),
                scopes=frozenset(scopes) if scopes else current.scopes,
                generation=current.generation + 1,
                updated_at=datetime.now(UTC),
            )
            self._records[handle] = updated
            self._generations_by_user[user_pk] = updated.generation
            return updated

    def delete_grant(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
    ) -> None:
        with self._lock:
            current = _owned_grant(self._records, handle, user_pk=user_pk)
            _require_generation(current, expected_generation)
            del self._records[handle]

    def snapshot_for_test(self) -> tuple[GmailCredentialGrant, ...]:
        """Return immutable test visibility without exposing a production API."""

        with self._lock:
            return tuple(self._records.values())


class EncryptedFileGmailCredentialStore:
    """Recoverable Community broker stored outside the application database.

    The entire versioned document is Fernet-encrypted.  Mutations hold an
    inter-process lock and replace the file atomically in its own directory;
    corrupt or wrongly-keyed files fail closed and are never overwritten.
    """

    def __init__(
        self,
        file_path: str | Path,
        *,
        encryption_secret: str,
        lock_timeout_seconds: float = 10.0,
    ) -> None:
        configured_path = Path(file_path)
        if not configured_path.is_absolute() or configured_path.name in {"", ".", ".."}:
            raise ValueError(
                "Gmail credential store path must be an absolute file path"
            )
        if len(encryption_secret) < 32:
            raise ValueError(
                "Gmail credential store key must contain at least 32 characters"
            )
        self._path = configured_path.absolute()
        self._lock_path = Path(f"{self._path}.lock")
        self._lock_timeout_seconds = lock_timeout_seconds
        digest = hashlib.sha256(
            b"interview-copilot:gmail-credential-store:v1\0"
            + encryption_secret.encode("utf-8")
        ).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))
        self._prepare_boundary()
        # Validate an existing document at construction so connector
        # availability is honest before a user starts an OAuth flow.
        self._with_records(lambda records: None, write=False)

    @property
    def file_path(self) -> Path:
        return self._path

    def put_grant(
        self,
        *,
        user_pk: int,
        google_subject: str,
        scopes: frozenset[str],
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime,
    ) -> GmailCredentialGrant:
        result: GmailCredentialGrant | None = None

        def mutate(records: dict[str, GmailCredentialGrant]) -> None:
            nonlocal result
            previous = _grant_for_user(records, user_pk)
            resolved_refresh = _resolved_refresh_token(
                previous,
                google_subject=google_subject,
                refresh_token=refresh_token,
            )
            now = datetime.now(UTC)
            generation = (
                max(
                    (grant.generation for grant in records.values()),
                    default=0,
                )
                + 1
            )
            result = GmailCredentialGrant(
                handle=_new_handle(),
                user_pk=user_pk,
                google_subject=google_subject,
                scopes=frozenset(scopes),
                access_token=access_token,
                refresh_token=resolved_refresh,
                access_token_expires_at=_as_utc(access_token_expires_at),
                generation=generation,
                created_at=now,
                updated_at=now,
            )
            if previous is not None:
                records.pop(previous.handle, None)
            records[result.handle] = result

        self._with_records(mutate, write=True)
        assert result is not None
        return result

    def get_grant(self, handle: str, *, user_pk: int) -> GmailCredentialGrant:
        result: GmailCredentialGrant | None = None

        def read(records: dict[str, GmailCredentialGrant]) -> None:
            nonlocal result
            result = _owned_grant(records, handle, user_pk=user_pk)

        self._with_records(read, write=False)
        assert result is not None
        return result

    def compare_and_swap_refresh(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
        access_token: str,
        access_token_expires_at: datetime,
        scopes: frozenset[str] | None = None,
    ) -> GmailCredentialGrant:
        result: GmailCredentialGrant | None = None

        def mutate(records: dict[str, GmailCredentialGrant]) -> None:
            nonlocal result
            current = _owned_grant(records, handle, user_pk=user_pk)
            _require_generation(current, expected_generation)
            result = replace(
                current,
                access_token=access_token,
                access_token_expires_at=_as_utc(access_token_expires_at),
                scopes=frozenset(scopes) if scopes else current.scopes,
                generation=current.generation + 1,
                updated_at=datetime.now(UTC),
            )
            records[handle] = result

        self._with_records(mutate, write=True)
        assert result is not None
        return result

    def delete_grant(
        self,
        handle: str,
        *,
        user_pk: int,
        expected_generation: int,
    ) -> None:
        def mutate(records: dict[str, GmailCredentialGrant]) -> None:
            current = _owned_grant(records, handle, user_pk=user_pk)
            _require_generation(current, expected_generation)
            del records[handle]

        self._with_records(mutate, write=True)

    def _prepare_boundary(self) -> None:
        try:
            if self._path.is_symlink() or (
                self._path.exists() and not self._path.is_file()
            ):
                raise ValueError("Gmail credential store path must be a regular file")
            parent = self._path.parent
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not parent.is_dir():
                raise ValueError("Gmail credential store parent must be a directory")
            _restrict_permissions(self._path)
        except OSError:
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_boundary_unavailable"
            ) from None

    def _with_records(self, operation, *, write: bool) -> None:
        lock = FileLock(str(self._lock_path), timeout=self._lock_timeout_seconds)
        try:
            with lock:
                _restrict_permissions(self._lock_path)
                records = self._read_unlocked()
                operation(records)
                if write:
                    self._write_unlocked(records)
        except Timeout:
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_lock_timeout"
            ) from None
        except GmailCredentialStoreError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_unavailable"
            ) from None

    def _read_unlocked(self) -> dict[str, GmailCredentialGrant]:
        if not self._path.exists():
            return {}
        if self._path.is_symlink() or not self._path.is_file():
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_boundary_invalid"
            )
        if self._path.stat().st_size > _MAX_STORE_BYTES:
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_too_large"
            )
        try:
            plaintext = self._cipher.decrypt(self._path.read_bytes())
        except InvalidToken:
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_decryption_failed"
            ) from None
        payload = json.loads(plaintext.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _SCHEMA_VERSION
        ):
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_schema_invalid"
            )
        raw_grants = payload.get("grants")
        if not isinstance(raw_grants, list):
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_schema_invalid"
            )
        records: dict[str, GmailCredentialGrant] = {}
        users: set[int] = set()
        for raw in raw_grants:
            grant = _decode_grant(raw)
            if grant.handle in records or grant.user_pk in users:
                raise GmailCredentialStoreUnavailableError(
                    "gmail_credential_store_schema_invalid"
                )
            records[grant.handle] = grant
            users.add(grant.user_pk)
        return records

    def _write_unlocked(self, records: dict[str, GmailCredentialGrant]) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "grants": [_encode_grant(grant) for grant in records.values()],
        }
        plaintext = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        ciphertext = self._cipher.encrypt(plaintext)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.chmod(temporary_path, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
            _restrict_permissions(self._path)
            _fsync_directory(self._path.parent)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()


def _new_handle() -> str:
    return _HANDLE_PREFIX + secrets.token_urlsafe(32)


def _grant_for_user(
    records: dict[str, GmailCredentialGrant], user_pk: int
) -> GmailCredentialGrant | None:
    return next((grant for grant in records.values() if grant.user_pk == user_pk), None)


def _owned_grant(
    records: dict[str, GmailCredentialGrant],
    handle: str,
    *,
    user_pk: int,
) -> GmailCredentialGrant:
    grant = records.get(handle)
    if grant is None or grant.user_pk != user_pk:
        raise GmailCredentialNotFoundError("invalid_grant")
    return grant


def _require_generation(grant: GmailCredentialGrant, expected: int) -> None:
    if grant.generation != expected:
        raise GmailCredentialConflictError("credential_changed")


def _resolved_refresh_token(
    previous: GmailCredentialGrant | None,
    *,
    google_subject: str,
    refresh_token: str | None,
) -> str:
    if refresh_token:
        return refresh_token
    if previous is None or previous.google_subject != google_subject:
        raise GmailRefreshTokenMissingError("refresh_token_missing")
    return previous.refresh_token


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _encode_grant(grant: GmailCredentialGrant) -> dict[str, object]:
    raw = asdict(grant)
    raw["scopes"] = sorted(grant.scopes)
    raw["access_token_expires_at"] = _as_utc(grant.access_token_expires_at).isoformat()
    raw["created_at"] = _as_utc(grant.created_at).isoformat()
    raw["updated_at"] = _as_utc(grant.updated_at).isoformat()
    return raw


def _decode_grant(raw: object) -> GmailCredentialGrant:
    if not isinstance(raw, dict):
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        )
    expected = {
        "handle",
        "user_pk",
        "google_subject",
        "scopes",
        "access_token",
        "refresh_token",
        "access_token_expires_at",
        "generation",
        "created_at",
        "updated_at",
    }
    if set(raw) != expected:
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        )
    string_fields = (
        "handle",
        "google_subject",
        "access_token",
        "refresh_token",
        "access_token_expires_at",
        "created_at",
        "updated_at",
    )
    if (
        not all(isinstance(raw[field], str) for field in string_fields)
        or isinstance(raw["user_pk"], bool)
        or not isinstance(raw["user_pk"], int)
        or isinstance(raw["generation"], bool)
        or not isinstance(raw["generation"], int)
    ):
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        )
    scopes = raw["scopes"]
    if not isinstance(scopes, list) or not all(
        isinstance(scope, str) for scope in scopes
    ):
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        )
    try:
        grant = GmailCredentialGrant(
            handle=str(raw["handle"]),
            user_pk=int(raw["user_pk"]),
            google_subject=str(raw["google_subject"]),
            scopes=frozenset(scopes),
            access_token=str(raw["access_token"]),
            refresh_token=str(raw["refresh_token"]),
            access_token_expires_at=_as_utc(
                datetime.fromisoformat(str(raw["access_token_expires_at"]))
            ),
            generation=int(raw["generation"]),
            created_at=_as_utc(datetime.fromisoformat(str(raw["created_at"]))),
            updated_at=_as_utc(datetime.fromisoformat(str(raw["updated_at"]))),
        )
    except (TypeError, ValueError):
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        ) from None
    if (
        not grant.handle.startswith(_HANDLE_PREFIX)
        or grant.user_pk <= 0
        or grant.generation <= 0
        or not grant.google_subject
        or not grant.access_token
        or not grant.refresh_token
    ):
        raise GmailCredentialStoreUnavailableError(
            "gmail_credential_store_schema_invalid"
        )
    return grant


def _restrict_permissions(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, 0o600)
        except OSError:
            raise GmailCredentialStoreUnavailableError(
                "gmail_credential_store_permissions_failed"
            ) from None


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "EncryptedFileGmailCredentialStore",
    "GmailCredentialConflictError",
    "GmailCredentialGrant",
    "GmailCredentialNotFoundError",
    "GmailCredentialStore",
    "GmailCredentialStoreError",
    "GmailCredentialStoreUnavailableError",
    "GmailRefreshTokenMissingError",
    "InMemoryGmailCredentialStore",
]
