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
  1. user_api_keys row for (user_id, provider) — encrypted DB storage
  2. OS env var ``profile.api_key_env`` — legacy .env path
First non-empty wins. Existing call sites that don't pass user_id keep
working (they only see #2).
"""

from __future__ import annotations

import base64
import hashlib
import logging
from contextlib import contextmanager
from typing import Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.core.user_identity import resolve_user_pk
from app.models.user_model_credentials import UserModelCredential

logger = logging.getLogger(__name__)


# ── Fernet key derivation ──────────────────────────────────────────────


def _derive_fernet_key(secret: str) -> bytes:
    """SHA-256(secret) → 32 bytes → urlsafe-b64 → valid Fernet key."""
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _collect_secrets() -> list[str]:
    """Primary first, then any retired keys from SECRET_KEYS_OLD.

    Order matters: ``MultiFernet`` encrypts with the FIRST key and decrypts
    by trying every key in order. So primary stays primary.
    """
    primary = (settings.SECRET_KEY or "").strip()
    olds: Iterable[str] = (
        s.strip() for s in (settings.SECRET_KEYS_OLD or "").split(",")
    )
    if not primary:
        return []
    return [primary, *(s for s in olds if s and s != primary)]


def _build_fernet() -> Optional[MultiFernet]:
    secrets_list = _collect_secrets()
    if not secrets_list:
        logger.error(
            "SECRET_KEY is empty — user API key encryption disabled. "
            "Configure SECRET_KEY in .env before storing any provider keys."
        )
        return None
    return MultiFernet([Fernet(_derive_fernet_key(s)) for s in secrets_list])


# Built once at import. Tests can monkey-patch ``_fernet`` if needed.
_fernet: Optional[MultiFernet] = _build_fernet()


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


# Tiny in-process cache so resolve_api_key doesn't hit DB + decrypt on every
# LLM call. Cleared on set / delete. Bounded by LRU + TTL because the
# values are PLAINTEXT API keys — long-lived caching of decrypted
# secrets is a memory-disclosure risk if a process gets cored/dumped.
# TTL also bounds staleness in the unlikely event that an external
# process rotates the underlying row (e.g. another worker's set call
# would invalidate this worker's cache via _decrypt_cache.pop — but
# cross-process invalidation isn't wired). 5 min is short enough that
# any externally-rotated key reaches the new worker quickly, long
# enough that a chatty LLM-call burst still benefits from caching.
import time as _time  # noqa: E402
from collections import OrderedDict as _OrderedDict  # noqa: E402
from threading import Lock as _Lock  # noqa: E402

_DECRYPT_CACHE_MAX = 256
_DECRYPT_CACHE_TTL_S = 300

# Entries are (plaintext, expires_at_monotonic). monotonic() so a system
# clock jump doesn't corrupt expiry math.
_decrypt_cache: "_OrderedDict[tuple[str, str], tuple[str, float]]" = _OrderedDict()
# OrderedDict operations are individually GIL-atomic but the composite
# sequences ``get → branch → pop/move_to_end`` and ``set → while-evict``
# inside _cache_get / _cache_put are not. Without this lock, a worker
# thread calling ``asyncio.to_thread(resolve_api_key, ...)`` while
# another thread is over the cap and evicting can race into a
# ``KeyError`` on move_to_end (the entry it just observed got popped
# by the eviction loop). The fix is the explicit lock held across the
# whole observe-then-mutate sequence (not just the individual dict ops).
_decrypt_cache_lock = _Lock()


def _cache_get(key: tuple[str, str]) -> Optional[str]:
    with _decrypt_cache_lock:
        entry = _decrypt_cache.get(key)
        if entry is None:
            return None
        plaintext, exp = entry
        if _time.monotonic() > exp:
            _decrypt_cache.pop(key, None)
            return None
        _decrypt_cache.move_to_end(key)  # MRU
        return plaintext


def _cache_put(key: tuple[str, str], plaintext: str) -> None:
    with _decrypt_cache_lock:
        _decrypt_cache[key] = (plaintext, _time.monotonic() + _DECRYPT_CACHE_TTL_S)
        _decrypt_cache.move_to_end(key)
        while len(_decrypt_cache) > _DECRYPT_CACHE_MAX:
            _decrypt_cache.popitem(last=False)  # evict LRU


def _encrypt(plaintext: str) -> str:
    if _fernet is None:
        raise RuntimeError("Encryption is unavailable: SECRET_KEY not configured")
    return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt(ciphertext: str) -> Optional[str]:
    """Decrypt with the primary key or any legacy key. Returns None on failure."""
    if _fernet is None:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def _is_encrypted_with_primary(ciphertext: str) -> bool:
    """True iff the ciphertext was produced with the *current* primary key.

    Used by the lazy-re-encrypt path: if a payload decrypted with an old
    key we want to re-encrypt under the new one. ``MultiFernet`` doesn't
    expose "which key won?" directly, so we check by trying decrypt with
    a single-key Fernet built from the primary alone.
    """
    primary = (settings.SECRET_KEY or "").strip()
    if not primary:
        return True  # nothing better we can do
    try:
        Fernet(_derive_fernet_key(primary)).decrypt(ciphertext.encode("utf-8"))
        return True
    except InvalidToken:
        return False


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

    ciphertext = _encrypt(plaintext)
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
    _cache_put((user_id, provider), plaintext)
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
    # Hold the lock for the cache invalidation so this delete-on-revoke
    # path doesn't race against a concurrent _cache_get (GIL-atomic dict
    # ops were safe, but the lock guarantees ordering: callers can't see
    # plaintext for a key that's already been deleted from the DB).
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
    cached = _cache_get(cache_key)
    if cached:
        return cached

    with _session(db) as s:
        user_pk = resolve_user_pk(s, user_id)
        if user_pk is None:
            return None
        row = (
            s.query(UserModelCredential)
            .filter(
                UserModelCredential.user_id == user_pk,
                UserModelCredential.provider == provider,
            )
            .first()
        )
        if row is None:
            return None

        plaintext = _decrypt(row.key_ciphertext)
        if plaintext is None:
            logger.error(
                "Failed to decrypt API key for user=%s provider=%s — "
                "SECRET_KEY rotated without a SECRET_KEYS_OLD entry?",
                user_id, provider,
            )
            return None

        # Lazy migration: if a legacy key decrypted us, re-write under the
        # current primary. Best-effort — even if the commit fails we still
        # return the plaintext for the caller.
        if not _is_encrypted_with_primary(row.key_ciphertext):
            try:
                row.key_ciphertext = _encrypt(plaintext)
                s.commit()
                logger.info(
                    "Re-encrypted user_api_key under new SECRET_KEY: user=%s provider=%s",
                    user_id, provider,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Lazy re-encrypt failed for user=%s provider=%s: %s",
                    user_id, provider, exc,
                )
                s.rollback()

        _cache_put(cache_key, plaintext)
        return plaintext


__all__ = [
    "set_user_api_key",
    "delete_user_api_key",
    "list_user_api_keys",
    "get_user_api_key_plaintext",
]
