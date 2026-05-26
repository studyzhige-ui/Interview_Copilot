"""Tests for app.core.security — password hashing, JWT issuance/decode, blacklist guard."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import bcrypt as _bcrypt
import pytest
from jose import JWTError, jwt as jose_jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_and_maybe_rehash,
    verify_password,
)


# ── bcrypt password hashing ──────────────────────────────────────────────
def test_password_hash_round_trip():
    plain = "my_secure_password_123"
    hashed = get_password_hash(plain)

    assert hashed != plain
    assert verify_password(plain, hashed)
    assert not verify_password("wrong_password", hashed)


def test_password_hash_is_salted_each_time():
    """Two hashes of the same password must differ because of fresh salts."""
    pw = "the-same-password"
    h1 = get_password_hash(pw)
    h2 = get_password_hash(pw)
    assert h1 != h2
    assert verify_password(pw, h1)
    assert verify_password(pw, h2)


def test_verify_password_handles_malformed_hash_without_raising():
    assert verify_password("anything", "not-a-real-bcrypt-hash") is False
    assert verify_password("anything", "") is False


def test_verify_password_accepts_bytes_hash():
    pw = "bytes-input"
    hashed = get_password_hash(pw)
    assert verify_password(pw, hashed.encode("utf-8"))


def test_new_hashes_use_argon2id():
    """Pin the algorithm: ``get_password_hash`` must produce an
    Argon2id hash, not bcrypt. If a future contributor swaps the
    pwdlib hasher order this test fails. Argon2id is the 2015 PHC
    competition winner and the default in FastAPI's current
    security guide."""
    hashed = get_password_hash("any-password")
    assert hashed.startswith("$argon2id$"), (
        f"expected argon2id prefix, got {hashed[:20]!r} — "
        "did the pwdlib hasher order regress?"
    )


def test_verify_password_accepts_legacy_bcrypt_hash():
    """Existing user rows whose passwords were hashed by the pre-
    P6-D bcrypt-only code path must still authenticate. Pwdlib's
    verifier list includes BcryptHasher specifically for this
    backward-compat purpose."""
    pw = "legacy-from-bcrypt-era"
    legacy_hash = _bcrypt.hashpw(
        pw.encode("utf-8"), _bcrypt.gensalt(),
    ).decode("utf-8")
    assert legacy_hash.startswith("$2"), "test fixture must be a bcrypt hash"
    assert verify_password(pw, legacy_hash)
    assert not verify_password("wrong", legacy_hash)


def test_verify_and_maybe_rehash_upgrades_legacy_bcrypt():
    """The lazy-rehash path: a successful login against a legacy
    bcrypt hash returns ``(True, <new argon2id hash>)`` so the
    caller can persist the upgraded hash. New-format hashes
    return ``(True, None)`` (no upgrade needed)."""
    pw = "rehash-on-login"
    legacy = _bcrypt.hashpw(pw.encode(), _bcrypt.gensalt()).decode()

    valid, new_hash = verify_and_maybe_rehash(pw, legacy)
    assert valid is True
    assert new_hash is not None
    assert new_hash.startswith("$argon2id$"), "upgrade must produce argon2id"

    # Verify the upgraded hash works too.
    assert verify_password(pw, new_hash)

    # New-style hash should NOT trigger a re-hash.
    fresh = get_password_hash(pw)
    valid2, new_hash2 = verify_and_maybe_rehash(pw, fresh)
    assert valid2 is True
    assert new_hash2 is None

    # Wrong password against any hash returns (False, None).
    assert verify_and_maybe_rehash("nope", legacy) == (False, None)
    assert verify_and_maybe_rehash("nope", fresh) == (False, None)


# ── JWT round trips ──────────────────────────────────────────────────────
def test_access_token_round_trip_carries_expected_claims():
    token = create_access_token(data={"sub": "alice"})
    payload = decode_token(token)
    assert payload["sub"] == "alice"
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload
    assert payload.get("jti") and isinstance(payload["jti"], str)


def test_refresh_token_has_refresh_type_and_jti():
    token = create_refresh_token(data={"sub": "bob"})
    payload = decode_token(token)
    assert payload["sub"] == "bob"
    assert payload["type"] == "refresh"
    assert payload.get("jti")


def test_each_token_has_unique_jti():
    t1 = create_access_token(data={"sub": "u1"})
    t2 = create_access_token(data={"sub": "u1"})
    assert decode_token(t1)["jti"] != decode_token(t2)["jti"]


def test_create_access_token_respects_custom_expiry():
    token = create_access_token(
        data={"sub": "alice"}, expires_delta=timedelta(minutes=5),
    )
    payload = decode_token(token)
    # exp - iat ≈ 300 seconds, allow a couple seconds of slop.
    delta = payload["exp"] - payload["iat"]
    assert 295 <= delta <= 305


# ── JWT rejection paths ──────────────────────────────────────────────────
def test_decode_token_rejects_garbage():
    with pytest.raises(JWTError):
        decode_token("not.a.real.token")


def test_decode_token_rejects_expired_token():
    token = create_access_token(
        data={"sub": "ghost"}, expires_delta=timedelta(seconds=-1),
    )
    with pytest.raises(JWTError):
        decode_token(token)


def test_decode_token_rejects_wrong_signature():
    """A token signed with a different secret must not decode under ours."""
    payload = {"sub": "intruder", "type": "access", "jti": "abc"}
    forged = jose_jwt.encode(payload, "completely-different-secret", algorithm=settings.ALGORITHM)
    with pytest.raises(JWTError):
        decode_token(forged)


# ── get_current_user / blacklist integration ─────────────────────────────
async def test_get_current_user_rejects_refresh_token():
    """A refresh token must not satisfy the access-token dependency."""
    from fastapi import HTTPException

    from app.core.security import get_current_user

    refresh = create_refresh_token(data={"sub": "user-x"})
    with patch("app.core.security.is_revoked", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=refresh, db=object())
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_revoked_jti():
    """A token whose jti is in the blacklist must be rejected."""
    from fastapi import HTTPException

    from app.core.security import get_current_user

    token = create_access_token(data={"sub": "user-y"})

    async def _revoked(_jti):
        return True

    with patch("app.core.security.is_revoked", side_effect=_revoked):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, db=object())
    assert exc_info.value.status_code == 401


async def test_get_current_user_rejects_token_without_jti():
    """Pre-jti-rollout tokens must be rejected even with a valid signature."""
    from fastapi import HTTPException

    from app.core.security import get_current_user

    # Hand-craft a valid-signature access token that lacks jti.
    payload = {"sub": "legacy", "type": "access"}
    token = jose_jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with patch("app.core.security.is_revoked", return_value=False):
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token=token, db=object())
    assert exc_info.value.status_code == 401
