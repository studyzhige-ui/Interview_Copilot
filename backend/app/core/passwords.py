"""Shared password primitives with no identity/session dependencies."""

from __future__ import annotations

from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

# ── Password hashing (pwdlib: Argon2id default + bcrypt legacy verify) ──
#
# pwdlib is FastAPI's currently-recommended password-hashing library
# (the official docs at fastapi.tiangolo.com/tutorial/security use it
# now — passlib's maintainer effectively stopped shipping releases in
# 2020 and the bcrypt>=5.x incompatibility is a ticking timebomb).
#
# Algorithm choice:
#   * Argon2id is the 2015 Password Hashing Competition winner — the
#     current best-in-class against GPU/ASIC attackers. Default
#     parameters from pwdlib are calibrated for ~300ms hash time on
#     modern server hardware, which dominates the password-bruteforce
#     economy.
#   * BcryptHasher is kept in the verifier list ONLY so users whose
#     password rows still carry the legacy bcrypt hash from the
#     pre-pwdlib era can log in. ``verify_and_update`` below upgrades
#     their hash to Argon2id on the next successful login — within a
#     few weeks of active users the table will be entirely Argon2id
#     and we can drop BcryptHasher.
#
# pwdlib's hashers list is order-sensitive: the FIRST entry is what
# new hashes use; subsequent entries are tried in order for verify.
# So new accounts produce Argon2id; existing bcrypt rows verify
# through the second hasher and get re-hashed.
_password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verify against any pwdlib-supported algorithm.

    Returns False (instead of raising) when the hash is malformed,
    unrecognised, or the password isn't a string — matches the
    legacy bcrypt-only helper's contract. The 14 tests in
    test_security.py pin this.

    pwdlib raises ``UnknownHashError`` when the hash prefix doesn't
    match any configured hasher (argon2id / bcrypt) — for our API
    that's just "wrong password" because the hash is garbage data.
    """
    from pwdlib.exceptions import UnknownHashError

    try:
        if isinstance(hashed_password, bytes):
            hashed_password = hashed_password.decode("utf-8")
        return _password_hash.verify(plain_password, hashed_password)
    except (ValueError, TypeError, UnknownHashError):
        return False


def get_password_hash(password: str) -> str:
    """Hash with Argon2id — the first hasher in the recommended list."""
    return _password_hash.hash(password)


def verify_and_maybe_rehash(
    plain_password: str,
    hashed_password: str,
) -> tuple[bool, str | None]:
    """Verify AND upgrade legacy hashes in one step.

    Returns ``(valid, new_hash)``. ``new_hash`` is non-None when the
    stored hash was a legacy form (e.g. bcrypt) — callers should
    persist it via ``UPDATE users SET hashed_password = <new_hash>``
    so the next login uses the upgraded algorithm. Failure mode
    matches ``verify_password`` (returns ``(False, None)``).
    """
    from pwdlib.exceptions import UnknownHashError

    try:
        if isinstance(hashed_password, bytes):
            hashed_password = hashed_password.decode("utf-8")
        return _password_hash.verify_and_update(plain_password, hashed_password)
    except (ValueError, TypeError, UnknownHashError):
        return False, None
