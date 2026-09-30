"""Per-user, per-provider API-key storage with at-rest encryption.

Design
======
- Plaintext API keys live ONLY in:
    1. the in-flight HTTP request body (TLS in production)
    2. the in-memory `_decrypt_cache` keyed by user_id+provider for fast resolve
    3. the OS env var fallback (existing behavior, no change)
- DB stores ONLY:
    * Fernet ciphertext (AES-128-CBC + HMAC-SHA256, prevents tampering)
    * a "masked" hint string like ``sk-****abcd`` for the UI

Key rotation
------------
The Fernet key is derived from ``settings.SECRET_KEY`` via SHA-256. To
rotate without invalidating every stored key:
  1. Move the current ``SECRET_KEY`` into ``SECRET_KEYS_OLD`` (comma-sep).
  2. Set a fresh ``SECRET_KEY``.
  3. Restart the app. Stored ciphertexts encrypted under the old key still
     decrypt (``MultiFernet`` tries every key in order) and are *lazily
     re-encrypted* under the new key on the next read.
  4. Once you're confident every active key has been touched, drop the old
     entry from ``SECRET_KEYS_OLD``.

Resolution order at request time (``resolve_api_key``)
------------------------------------------------------
  1. user_model_credentials row for (user_id, provider) — encrypted DB storage
  2. OS env var ``profile.api_key_env`` — legacy .env path
First non-empty wins. Existing call sites that don't pass user_id keep
working (they only see #2).
"""

from __future__ import annotations

import logging
import hashlib
from contextlib import contextmanager
from typing import Optional

from sqlalchemy.orm import Session

from app.core.model_connection_error import ModelConnectionUnavailable
from app.core.secrets import decrypt_secret, encrypt_secret, encrypted_with_primary
from app.core.user_identity import resolve_user_pk
from app.db.database import SessionLocal
from app.models.user_model_credentials import UserModelCredential

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────


def _mask(plaintext: str) -> str:
    """Show first 3 + last 4 chars; everything else is asterisks."""
    plaintext = plaintext.strip()
    if len(plaintext) <= 8:
        return "****"
    return f"{plaintext[:3]}…{plaintext[-4:]}"


@contextmanager
def _session(db: Session | None):
    """Use the caller's session if given; otherwise spin up a short-lived one.

    Keeps the service callable from both FastAPI endpoints (which pass
    ``Depends(get_db)``) and ad-hoc places (Celery tasks, CLI) without
    duplicating lifecycle code.
    """
    if db is not None:
        yield db
        return
    owned = SessionLocal()
    try:
        yield owned
    finally:
        owned.close()


# The DB row is read on every resolution: another process may rotate/delete it.
# This LRU only avoids repeated Fernet decryption of the exact same ciphertext;
# it never grants permission to reuse a secret without checking current storage.
import time as _time  # noqa: E402
from collections import OrderedDict as _OrderedDict  # noqa: E402
from threading import Lock as _Lock  # noqa: E402

_DECRYPT_CACHE_MAX = 256
_DECRYPT_CACHE_TTL_S = 300

# Entries are (plaintext, expires_at_monotonic, ciphertext_digest). monotonic() so a system
# clock jump doesn't corrupt expiry math.
_decrypt_cache: "_OrderedDict[tuple[str, str], tuple[str, float, str]]" = _OrderedDict()
# OrderedDict operations are individually GIL-atomic but the composite
# sequences ``get → branch → pop/move_to_end`` and ``set → while-evict``
# inside _cache_get / _cache_put are not. Without this lock, a worker
# thread calling ``asyncio.to_thread(resolve_api_key, ...)`` while
# another thread is over the cap and evicting can race into a
# ``KeyError`` on move_to_end (the entry it just observed got popped
# by the eviction loop). The fix is the explicit lock held across the
# whole observe-then-mutate sequence (not just the individual dict ops).
_decrypt_cache_lock = _Lock()


def _cache_get(key: tuple[str, str], ciphertext: str) -> Optional[str]:
    with _decrypt_cache_lock:
        entry = _decrypt_cache.get(key)
        if entry is None:
            return None
        plaintext, exp, digest = entry
        if (
            _time.monotonic() > exp
            or digest != hashlib.sha256(ciphertext.encode()).hexdigest()
        ):
            _decrypt_cache.pop(key, None)
            return None
        _decrypt_cache.move_to_end(key)  # MRU
        return plaintext


def _cache_put(key: tuple[str, str], plaintext: str, ciphertext: str) -> None:
    with _decrypt_cache_lock:
        _decrypt_cache[key] = (
            plaintext,
            _time.monotonic() + _DECRYPT_CACHE_TTL_S,
            hashlib.sha256(ciphertext.encode()).hexdigest(),
        )
        _decrypt_cache.move_to_end(key)
        while len(_decrypt_cache) > _DECRYPT_CACHE_MAX:
            _decrypt_cache.popitem(last=False)  # evict LRU


# ── Public API ─────────────────────────────────────────────────────────


def set_user_api_key(
    user_id: str,
    provider: str,
    api_key: str,
    *,
    db: Session | None = None,
) -> dict:
    """Encrypt + upsert. Returns the masked hint payload for the UI."""
    plaintext = (api_key or "").strip()
    if not plaintext:
        raise ValueError("API key is empty")

    ciphertext = encrypt_secret(plaintext)
    masked = _mask(plaintext)

    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            raise ValueError(f"Unknown user: {user_id}")
        row = (
            s.query(UserModelCredential)
            .filter(
                UserModelCredential.user_id == user_pk,
                UserModelCredential.provider == provider,
            )
            .first()
        )
        if row is None:
            row = UserModelCredential(
                user_id=user_pk,
                provider=provider,
                key_ciphertext=ciphertext,
                key_masked=masked,
                status="active",
            )
            s.add(row)
        else:
            row.key_ciphertext = ciphertext
            row.key_masked = masked
            # A freshly-set / rotated key is active + not-yet-revalidated.
            row.status = "active"
            row.last_validated_at = None
            row.last_validation_error = None
        s.commit()
    _cache_put((user_id, provider), plaintext, ciphertext)
    return {"provider": provider, "masked": masked, "set": True}


def delete_user_api_key(
    user_id: str,
    provider: str,
    *,
    db: Session | None = None,
) -> bool:
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            return False
        rows = (
            s.query(UserModelCredential)
            .filter(
                UserModelCredential.user_id == user_pk,
                UserModelCredential.provider == provider,
            )
            .delete(synchronize_session=False)
        )
        s.commit()
    # Invalidate this process's decryption cache. Every future lookup also reads
    # the authoritative row, including in other workers. Already-dispatched
    # provider requests cannot be retroactively cancelled by deleting a key.
    with _decrypt_cache_lock:
        _decrypt_cache.pop((user_id, provider), None)
    return bool(rows)


def list_user_api_keys(user_id: str, *, db: Session | None = None) -> dict[str, dict]:
    """Return ``{provider: {set: True, masked: '...'}}``. NEVER returns plaintext."""
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            return {}
        rows = (
            s.query(UserModelCredential)
            .filter(UserModelCredential.user_id == user_pk)
            .all()
        )
        return {
            r.provider: {"set": True, "masked": r.key_masked, "status": r.status}
            for r in rows
        }


def get_user_api_key_plaintext(
    user_id: str,
    provider: str,
    *,
    db: Session | None = None,
) -> Optional[str]:
    """Decrypt and return plaintext for backend LLM construction.

    Should ONLY be called from server-side code that immediately uses the
    key to make an outbound API call. Never exposed via any HTTP endpoint.

    Lazy re-encrypt: if the row was encrypted under a retired secret, we
    transparently re-encrypt it under the current primary key during this
    call so the migration completes without a maintenance window.
    """
    cache_key = (user_id, provider)
    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            with _decrypt_cache_lock:
                _decrypt_cache.pop(cache_key, None)
            return None
        row = (
            s.query(UserModelCredential)
            .filter(
                UserModelCredential.user_id == user_pk,
                UserModelCredential.provider == provider,
            )
            .populate_existing()
            .first()
        )
        if row is None:
            with _decrypt_cache_lock:
                _decrypt_cache.pop(cache_key, None)
            return None

        ciphertext = row.key_ciphertext
        cached = _cache_get(cache_key, ciphertext)
        if cached:
            return cached
        plaintext = decrypt_secret(row.key_ciphertext)
        if plaintext is None:
            logger.error(
                "Failed to decrypt API key for user=%s provider=%s — "
                "SECRET_KEY rotated without a SECRET_KEYS_OLD entry?",
                user_id,
                provider,
            )
            with _decrypt_cache_lock:
                _decrypt_cache.pop(cache_key, None)
            raise ModelConnectionUnavailable()

        # Lazy migration: if a legacy key decrypted us, re-write under the
        # current primary. Compare the old ciphertext so a concurrent rotation
        # cannot be overwritten with the older secret. Failure stops dispatch.
        if not encrypted_with_primary(ciphertext):
            rotated_ciphertext = encrypt_secret(plaintext)
            try:
                updated = (
                    s.query(UserModelCredential)
                    .filter(
                        UserModelCredential.id == row.id,
                        UserModelCredential.key_ciphertext == ciphertext,
                    )
                    .update(
                        {"key_ciphertext": rotated_ciphertext},
                        synchronize_session=False,
                    )
                )
                if not updated:
                    s.rollback()
                    raise ModelConnectionUnavailable()
                s.commit()
                ciphertext = rotated_ciphertext
            except ModelConnectionUnavailable:
                raise
            except Exception as exc:
                logger.warning(
                    "Credential re-encryption unavailable (%s)", type(exc).__name__
                )
                s.rollback()
                raise ModelConnectionUnavailable() from exc

        _cache_put(cache_key, plaintext, ciphertext)
        return plaintext


__all__ = [
    "set_user_api_key",
    "delete_user_api_key",
    "list_user_api_keys",
    "get_user_api_key_plaintext",
]
