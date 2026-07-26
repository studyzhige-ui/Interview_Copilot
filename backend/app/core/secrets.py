"""Small shared Fernet wrapper for secrets stored in the database."""

from __future__ import annotations

import base64
import hashlib
from typing import Iterable

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


def _key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _secrets() -> list[str]:
    primary = (settings.SECRET_KEY or "").strip()
    old: Iterable[str] = (
        value.strip() for value in (settings.SECRET_KEYS_OLD or "").split(",")
    )
    if not primary:
        return []
    return [primary, *(value for value in old if value and value != primary)]


def _fernet() -> MultiFernet | None:
    values = _secrets()
    if not values:
        return None
    return MultiFernet([Fernet(_key(value)) for value in values])


def encrypt_secret(plaintext: str) -> str:
    cipher = _fernet()
    if cipher is None:
        raise RuntimeError("Encryption is unavailable: SECRET_KEY not configured")
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str | None:
    cipher = _fernet()
    if cipher is None:
        return None
    try:
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def encrypted_with_primary(ciphertext: str) -> bool:
    primary = (settings.SECRET_KEY or "").strip()
    if not primary:
        return True
    try:
        Fernet(_key(primary)).decrypt(ciphertext.encode("utf-8"))
        return True
    except InvalidToken:
        return False
