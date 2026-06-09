"""Resolve an authenticated principal to the stable ``users.id``.

The per-user model-config tables (``user_model_credentials`` /
``user_model_provider_settings`` / ``user_model_selections``) key on the
stable ``users.id`` FK. The chat/agent runtime currently threads the
``username`` as its principal, and the user-facing API passes
``current_user.username`` too — so the model-config services accept that
username and map it here to the ``users.id`` they store and query by.

A username is unique, so this is an exact 1:1 lookup. Keeping the mapping in
one place means that when the rest of the runtime later threads ``users.id``
directly, only this resolver (and its call sites' argument) changes.
"""
from sqlalchemy.orm import Session

from app.models.user import User


def resolve_user_pk(db: Session, username: str) -> int | None:
    """Return ``users.id`` for ``username``, or ``None`` if no such user."""
    return db.query(User.id).filter(User.username == username).scalar()
