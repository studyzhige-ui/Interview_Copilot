"""Gmail-specific secret-store boundary tests."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from app.services.gmail_credential_store import (
    EncryptedFileGmailCredentialStore,
    GmailCredentialConflictError,
    GmailCredentialNotFoundError,
    GmailCredentialStoreUnavailableError,
    InMemoryGmailCredentialStore,
)


STORE_KEY = "gmail-credential-recovery-key-with-at-least-32-characters"


def _put(store, *, user_pk: int = 7, refresh_token: str | None = "refresh-secret"):
    return store.put_grant(
        user_pk=user_pk,
        google_subject="google-subject",
        scopes=frozenset({"openid", "gmail.readonly"}),
        access_token="access-secret",
        refresh_token=refresh_token,
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def test_encrypted_file_store_round_trips_without_plaintext_and_reopens(tmp_path):
    path = tmp_path / "gmail-credentials.enc"
    store = EncryptedFileGmailCredentialStore(
        path.resolve(),
        encryption_secret=STORE_KEY,
    )
    created = _put(store)

    assert "access-secret" not in repr(created)
    assert "refresh-secret" not in repr(created)
    assert created.handle not in repr(created)
    ciphertext = path.read_bytes()
    assert b"access-secret" not in ciphertext
    assert b"refresh-secret" not in ciphertext
    assert created.handle.encode() not in ciphertext
    assert not list(tmp_path.glob("*.tmp"))

    reopened = EncryptedFileGmailCredentialStore(
        path.resolve(),
        encryption_secret=STORE_KEY,
    )
    loaded = reopened.get_grant(created.handle, user_pk=7)
    assert loaded == created
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


def test_wrong_recovery_key_fails_closed_without_rewriting_store(tmp_path):
    path = (tmp_path / "gmail-credentials.enc").resolve()
    store = EncryptedFileGmailCredentialStore(path, encryption_secret=STORE_KEY)
    _put(store)
    original = path.read_bytes()

    with pytest.raises(GmailCredentialStoreUnavailableError):
        EncryptedFileGmailCredentialStore(
            path,
            encryption_secret="different-recovery-key-with-at-least-32-characters",
        )

    assert path.read_bytes() == original


def test_reauthorization_rotates_handle_and_stale_refresh_cannot_overwrite():
    store = InMemoryGmailCredentialStore()
    first = _put(store)
    second = _put(store, refresh_token="new-refresh-secret")

    assert second.handle != first.handle
    assert second.generation == first.generation + 1
    with pytest.raises(GmailCredentialNotFoundError):
        store.compare_and_swap_refresh(
            first.handle,
            user_pk=7,
            expected_generation=first.generation,
            access_token="stale-access-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    assert store.get_grant(second.handle, user_pk=7).access_token == "access-secret"


def test_refresh_compare_and_swap_checks_generation_and_owner():
    store = InMemoryGmailCredentialStore()
    grant = _put(store)

    refreshed = store.compare_and_swap_refresh(
        grant.handle,
        user_pk=7,
        expected_generation=grant.generation,
        access_token="fresh-access-token",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert refreshed.generation == grant.generation + 1
    with pytest.raises(GmailCredentialConflictError):
        store.compare_and_swap_refresh(
            grant.handle,
            user_pk=7,
            expected_generation=grant.generation,
            access_token="stale-access-token",
            access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    with pytest.raises(GmailCredentialNotFoundError):
        store.get_grant(grant.handle, user_pk=8)


def test_same_subject_may_inherit_refresh_token_but_rotates_handle():
    store = InMemoryGmailCredentialStore()
    first = _put(store)
    second = _put(store, refresh_token=None)

    assert second.handle != first.handle
    assert second.refresh_token == "refresh-secret"
    assert store.snapshot_for_test() == (second,)


def test_file_store_requires_explicit_absolute_path_and_strong_recovery_key(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        EncryptedFileGmailCredentialStore(
            "gmail-credentials.enc",
            encryption_secret=STORE_KEY,
        )
    with pytest.raises(ValueError, match="32"):
        EncryptedFileGmailCredentialStore(
            (tmp_path / "gmail-credentials.enc").resolve(),
            encryption_secret="short",
        )
