"""User-account persistence operations for the auth endpoints.

The router keeps the HTTP/auth-protocol flow (token minting, code
verification, status mapping); the direct ``users``-table work lives here.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_and_maybe_rehash
from app.db.types import utc_now
from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def get_by_email(db: Session, email: str) -> User | None:
    normalized = email.strip().lower()
    return db.query(User).filter(func.lower(User.email) == normalized).first()


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Verify credentials; None on unknown user OR wrong password.

    Constant-ish work on the unknown-user branch: still hash something so
    that branch isn't dramatically faster than the wrong-password branch.
    (Argon2id is ~300ms; the difference is the dominant signal an attacker
    could exploit to enumerate users.)

    On success, persists a lazy hash upgrade when pwdlib decided the stored
    hash used a legacy algorithm (bcrypt today, maybe argon2-old-params
    tomorrow) — best-effort, a write failure doesn't break login.
    """
    user = get_by_username(db, username)
    if not user:
        verify_and_maybe_rehash(password, "$argon2id$v=19$m=65536,t=3,p=4$bm9uZQ$x")
        return None

    valid, new_hash = verify_and_maybe_rehash(password, user.hashed_password)
    if not valid:
        return None

    if new_hash is not None:
        try:
            user.hashed_password = new_hash
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    return user


def create_user(db: Session, *, username: str, email: str, password: str) -> User:
    """Create a verified user row (caller has already verified the email code)."""
    user = User(
        username=username,
        email=email.strip().lower(),
        hashed_password=get_password_hash(password),
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def apply_password_change(db: Session, user: User, new_password: str) -> None:
    """Rehash, bump ``token_version`` (kills ALL outstanding tokens), stamp.

    One commit — see the /change-password endpoint docstring for the UX
    contract (the user re-logs in; no fresh pair is returned).
    """
    user.hashed_password = get_password_hash(new_password)
    user.token_version = (user.token_version or 0) + 1
    # Naive UTC to match the model's created_at/updated_at convention and the
    # TIMESTAMP (without-tz) column. ``updated_at`` auto-stamps via onupdate.
    user.password_changed_at = utc_now()
    db.add(user)
    db.commit()


def update_profile(
    db: Session,
    user: User,
    *,
    nickname: str | None,
    avatar_url: str | None,
    bio: str | None,
    global_memory_enabled: bool | None,
) -> bool:
    """Apply the PATCH /me fields; returns True iff something changed."""
    changed = False
    if nickname is not None:
        user.nickname = nickname.strip() or None
        changed = True
    if avatar_url is not None:
        user.avatar_url = avatar_url.strip() or None
        changed = True
    if bio is not None:
        user.bio = bio.strip() or None
        changed = True
    if global_memory_enabled is not None:
        # Pydantic already gave us a real bool, just persist it. ``False`` is
        # a legitimate write (the opt-in default) — no truthiness filtering.
        user.global_memory_enabled = bool(global_memory_enabled)
        changed = True
    if changed:
        db.add(user)
        db.commit()
        db.refresh(user)
    return changed
