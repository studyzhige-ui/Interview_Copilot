"""Private OAuth credential boundary for the closed Canva/Notion set.

Community deployments may use the encrypted file implementation. Cloud must
inject a durable secret-store implementation; neither tokens nor the store
document belong in the application database.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock, Timeout


_MAX_STORE_BYTES = 5_000_000
_SCHEMA_VERSION = 1


class PluginCredentialStoreError(RuntimeError):
    pass


class PluginCredentialNotFoundError(PluginCredentialStoreError):
    pass


class PluginCredentialConflictError(PluginCredentialStoreError):
    pass


class PluginCredentialStoreUnavailableError(PluginCredentialStoreError):
    pass


@dataclass(frozen=True)
class PluginCredentialGrant:
    handle: str = field(repr=False)
    user_pk: int
    provider: str
    external_account_id: str
    scopes: frozenset[str]
    access_token: str = field(repr=False)
    refresh_token: str | None = field(repr=False)
    access_token_expires_at: datetime | None
    generation: int
    created_at: datetime
    updated_at: datetime


class PluginCredentialStore(Protocol):
    def put_grant(
        self,
        *,
        user_pk: int,
        provider: str,
        external_account_id: str,
        scopes: frozenset[str],
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime | None,
    ) -> PluginCredentialGrant: ...

    def get_grant(
        self, handle: str, *, user_pk: int, provider: str
    ) -> PluginCredentialGrant: ...

    def compare_and_swap_refresh(
        self,
        handle: str,
        *,
        user_pk: int,
        provider: str,
        expected_generation: int,
        access_token: str,
        refresh_token: str | None,
        access_token_expires_at: datetime | None,
        scopes: frozenset[str] | None = None,
    ) -> PluginCredentialGrant: ...

    def delete_grant(
        self,
        handle: str,
        *,
        user_pk: int,
        provider: str,
        expected_generation: int,
    ) -> None: ...


class InMemoryPluginCredentialStore:
    """Deterministic test fake; never selected by production composition."""

    def __init__(self) -> None:
        self._records: dict[str, PluginCredentialGrant] = {}
        self._lock = threading.RLock()

    def put_grant(self, **values: object) -> PluginCredentialGrant:
        with self._lock:
            user_pk = int(values["user_pk"])
            provider = str(values["provider"])
            previous = next(
                (
                    item
                    for item in self._records.values()
                    if item.user_pk == user_pk and item.provider == provider
                ),
                None,
            )
            now = datetime.now(UTC)
            grant = PluginCredentialGrant(
                handle=f"pch_{secrets.token_urlsafe(24)}",
                user_pk=user_pk,
                provider=provider,
                external_account_id=str(values["external_account_id"]),
                scopes=frozenset(values["scopes"]),  # type: ignore[arg-type]
                access_token=str(values["access_token"]),
                refresh_token=(
                    str(values["refresh_token"])
                    if values.get("refresh_token")
                    else None
                ),
                access_token_expires_at=values.get("access_token_expires_at"),  # type: ignore[arg-type]
                generation=(previous.generation + 1 if previous else 1),
                created_at=now,
                updated_at=now,
            )
            if previous:
                self._records.pop(previous.handle, None)
            self._records[grant.handle] = grant
            return grant

    def get_grant(
        self, handle: str, *, user_pk: int, provider: str
    ) -> PluginCredentialGrant:
        with self._lock:
            return _owned(self._records, handle, user_pk=user_pk, provider=provider)

    def compare_and_swap_refresh(
        self, handle: str, **values: object
    ) -> PluginCredentialGrant:
        with self._lock:
            current = _owned(
                self._records,
                handle,
                user_pk=int(values["user_pk"]),
                provider=str(values["provider"]),
            )
            if current.generation != int(values["expected_generation"]):
                raise PluginCredentialConflictError("credential_generation_changed")
            updated = replace(
                current,
                access_token=str(values["access_token"]),
                refresh_token=(
                    str(values["refresh_token"])
                    if values.get("refresh_token")
                    else current.refresh_token
                ),
                access_token_expires_at=values.get("access_token_expires_at"),  # type: ignore[arg-type]
                scopes=(
                    frozenset(values["scopes"])
                    if values.get("scopes")
                    else current.scopes
                ),  # type: ignore[arg-type]
                generation=current.generation + 1,
                updated_at=datetime.now(UTC),
            )
            self._records[handle] = updated
            return updated

    def delete_grant(self, handle: str, **values: object) -> None:
        with self._lock:
            current = _owned(
                self._records,
                handle,
                user_pk=int(values["user_pk"]),
                provider=str(values["provider"]),
            )
            if current.generation != int(values["expected_generation"]):
                raise PluginCredentialConflictError("credential_generation_changed")
            del self._records[handle]


class EncryptedFilePluginCredentialStore(InMemoryPluginCredentialStore):
    """Atomic, inter-process encrypted Community credential store."""

    def __init__(self, file_path: str | Path, *, encryption_secret: str) -> None:
        self._path = Path(file_path)
        if not self._path.is_absolute() or not self._path.name:
            raise ValueError("plugin credential store path must be absolute")
        if len(encryption_secret) < 32:
            raise ValueError(
                "plugin credential store key must contain at least 32 characters"
            )
        self._path = self._path.absolute()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file_lock = FileLock(f"{self._path}.lock", timeout=10)
        digest = hashlib.sha256(
            b"interview-copilot:external-plugin-credential-store:v1\0"
            + encryption_secret.encode("utf-8")
        ).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))
        super().__init__()
        self._records = self._read_records()

    def put_grant(self, **values: object) -> PluginCredentialGrant:
        return self._mutate(
            lambda: super(EncryptedFilePluginCredentialStore, self).put_grant(**values)
        )

    def get_grant(
        self, handle: str, *, user_pk: int, provider: str
    ) -> PluginCredentialGrant:
        return self._inspect(
            lambda: super(EncryptedFilePluginCredentialStore, self).get_grant(
                handle, user_pk=user_pk, provider=provider
            )
        )

    def compare_and_swap_refresh(
        self, handle: str, **values: object
    ) -> PluginCredentialGrant:
        return self._mutate(
            lambda: super(
                EncryptedFilePluginCredentialStore, self
            ).compare_and_swap_refresh(handle, **values)
        )

    def delete_grant(self, handle: str, **values: object) -> None:
        self._mutate(
            lambda: super(EncryptedFilePluginCredentialStore, self).delete_grant(
                handle, **values
            )
        )

    def _inspect(self, operation):  # type: ignore[no-untyped-def]
        try:
            with self._file_lock:
                self._records = self._read_records()
                return operation()
        except Timeout as exc:
            raise PluginCredentialStoreUnavailableError(
                "credential_store_lock_timeout"
            ) from exc

    def _mutate(self, operation):  # type: ignore[no-untyped-def]
        try:
            with self._file_lock:
                self._records = self._read_records()
                result = operation()
                self._write_records()
                return result
        except Timeout as exc:
            raise PluginCredentialStoreUnavailableError(
                "credential_store_lock_timeout"
            ) from exc

    def _read_records(self) -> dict[str, PluginCredentialGrant]:
        if not self._path.exists():
            return {}
        if self._path.is_symlink() or self._path.stat().st_size > _MAX_STORE_BYTES:
            raise PluginCredentialStoreUnavailableError(
                "credential_store_boundary_invalid"
            )
        try:
            raw = self._cipher.decrypt(self._path.read_bytes())
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("version") != _SCHEMA_VERSION or not isinstance(
                payload.get("grants"), list
            ):
                raise ValueError
            records = [_grant_from_json(item) for item in payload["grants"]]
            return {record.handle: record for record in records}
        except (
            InvalidToken,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
            OSError,
        ) as exc:
            raise PluginCredentialStoreUnavailableError(
                "credential_store_invalid"
            ) from exc

    def _write_records(self) -> None:
        payload = {
            "version": _SCHEMA_VERSION,
            "grants": [_grant_to_json(item) for item in self._records.values()],
        }
        encrypted = self._cipher.encrypt(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        if len(encrypted) > _MAX_STORE_BYTES:
            raise PluginCredentialStoreUnavailableError("credential_store_too_large")
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self._path.name}.", dir=self._path.parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def _owned(
    records: dict[str, PluginCredentialGrant],
    handle: str,
    *,
    user_pk: int,
    provider: str,
) -> PluginCredentialGrant:
    current = records.get(handle)
    if current is None or current.user_pk != user_pk or current.provider != provider:
        raise PluginCredentialNotFoundError("credential_not_found")
    return current


def _grant_to_json(grant: PluginCredentialGrant) -> dict[str, object]:
    return {
        "handle": grant.handle,
        "user_pk": grant.user_pk,
        "provider": grant.provider,
        "external_account_id": grant.external_account_id,
        "scopes": sorted(grant.scopes),
        "access_token": grant.access_token,
        "refresh_token": grant.refresh_token,
        "access_token_expires_at": grant.access_token_expires_at.isoformat()
        if grant.access_token_expires_at
        else None,
        "generation": grant.generation,
        "created_at": grant.created_at.isoformat(),
        "updated_at": grant.updated_at.isoformat(),
    }


def _grant_from_json(value: object) -> PluginCredentialGrant:
    if not isinstance(value, dict):
        raise ValueError
    expires = value.get("access_token_expires_at")
    return PluginCredentialGrant(
        handle=str(value["handle"]),
        user_pk=int(value["user_pk"]),
        provider=str(value["provider"]),
        external_account_id=str(value["external_account_id"]),
        scopes=frozenset(str(item) for item in value["scopes"]),
        access_token=str(value["access_token"]),
        refresh_token=(
            str(value["refresh_token"]) if value.get("refresh_token") else None
        ),
        access_token_expires_at=(
            datetime.fromisoformat(str(expires)) if expires else None
        ),
        generation=int(value["generation"]),
        created_at=datetime.fromisoformat(str(value["created_at"])),
        updated_at=datetime.fromisoformat(str(value["updated_at"])),
    )


__all__ = [
    "EncryptedFilePluginCredentialStore",
    "InMemoryPluginCredentialStore",
    "PluginCredentialConflictError",
    "PluginCredentialGrant",
    "PluginCredentialNotFoundError",
    "PluginCredentialStore",
    "PluginCredentialStoreError",
    "PluginCredentialStoreUnavailableError",
]
