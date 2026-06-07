"""Per-user model selection: which profile drives each role.

Persists to the ``user_model_selections`` table (one row per role, keyed by
the stable users.id). Layers on top of the
catalog cache in ``app.core.model_catalog`` — selection ids are
normalised against the live catalog so a stale id (vendor retired
the model) silently degrades to ``ROLE_DEFAULTS`` instead of
returning an unusable profile.

What lives here:
  * ``get_runtime_selection`` / ``persist_runtime_selection`` /
    ``update_runtime_selection`` — selection read/write
  * ``get_profile_for_role`` — resolve role → ModelProfile with the
    catalog fallback chain
"""
from __future__ import annotations

import logging
from threading import Lock

from app.core import model_catalog
from app.core.model_catalog import ROLE_DEFAULTS, ModelProfile

logger = logging.getLogger(__name__)


# Single lock for selection-state writes. The LLM caches in
# ``llm_client_factory`` carry their own lock; ``persist_runtime_selection``
# triggers the cache clear via a lazy import to avoid a circular dep.
_selection_lock = Lock()


def _normalize_selection(raw: dict[str, str]) -> dict[str, str]:
    """Clamp a raw selection dict to known-valid profile ids.

    Unknown ids fall back to ROLE_DEFAULTS for that role. Agent role
    additionally requires function-calling support; a non-FC selection
    is replaced by ROLE_DEFAULTS["agent"]. Retired alias safeguards
    (the legacy ``deepseek-chat`` / ``deepseek-reasoner`` short ids
    from pre-P6-L) are still dropped so old persisted selections
    upgrade cleanly without surfacing as "missing profile" errors.
    """
    profiles = model_catalog._get_all_profiles()
    selection = dict(ROLE_DEFAULTS)
    for role in ROLE_DEFAULTS:
        candidate = raw.get(role)
        # Drop pre-P6-L bare ids (no "provider/" prefix). They aren't
        # valid in the new "provider/model" id scheme.
        if not candidate or "/" not in candidate:
            continue
        if candidate in profiles:
            selection[role] = candidate

    # Agent role guard: if the selected agent profile doesn't support
    # function calling (or isn't in the cache), fall back to the role
    # default. The lookup tolerates a missing default too — we just
    # keep whatever's in selection and let downstream surface the error.
    agent_profile = profiles.get(selection["agent"])
    if agent_profile is None or not agent_profile.supports_function_calling:
        selection["agent"] = ROLE_DEFAULTS["agent"]
    return selection


def _load_user_selection(user_id: str) -> dict[str, str]:
    """Read a user's role→profile_id selection rows from the DB.

    ``user_id`` is the runtime principal (username); we join to ``users`` so
    the actual filter is on the stable id. A partial result is fine —
    ``_normalize_selection`` fills any unset role from ROLE_DEFAULTS.
    """
    from app.db.database import SessionLocal
    from app.models.user import User
    from app.models.user_model_selections import UserModelSelection

    try:
        with SessionLocal() as db:
            rows = (
                db.query(UserModelSelection.role, UserModelSelection.profile_id)
                .join(User, User.id == UserModelSelection.user_id)
                .filter(User.username == user_id)
                .all()
            )
        return {str(role): str(pid) for role, pid in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load model selection for user=%s: %s", user_id, exc,
        )
        return dict(ROLE_DEFAULTS)


def _save_user_selection(user_id: str, selection: dict[str, str]) -> None:
    """Replace the user's selection rows with ``selection`` (role→profile_id).

    The caller always hands a complete normalized dict, so we full-replace
    (delete + re-insert) rather than diff per role.
    """
    from app.core.user_identity import resolve_user_pk
    from app.db.database import SessionLocal
    from app.models.user_model_selections import UserModelSelection

    with SessionLocal() as db:
        user_pk = resolve_user_pk(db, user_id)
        if user_pk is None:
            logger.warning("Cannot save model selection: unknown user=%s", user_id)
            return
        db.query(UserModelSelection).filter(
            UserModelSelection.user_id == user_pk,
        ).delete(synchronize_session=False)
        db.add_all([
            UserModelSelection(user_id=user_pk, role=role, profile_id=pid)
            for role, pid in selection.items()
        ])
        db.commit()


def get_runtime_selection(user_id: str | None = None) -> dict[str, str]:
    """Return the active model selection for ``user_id``.

    Without ``user_id`` (startup contexts) returns ROLE_DEFAULTS. With
    it, reads the user's ``user_model_selections`` rows and falls back to
    defaults on any error.
    """
    with _selection_lock:
        if user_id is None:
            return dict(ROLE_DEFAULTS)
        return _normalize_selection(_load_user_selection(user_id))


def persist_runtime_selection(
    selection: dict[str, str], user_id: str,
) -> dict[str, str]:
    """Save ``selection`` for ``user_id``. Returns the normalized form."""
    normalized = _normalize_selection(selection)
    with _selection_lock:
        _save_user_selection(user_id, normalized)
    # Clear the (role, profile_id) → LLM-instance cache so the user's
    # next chat constructs a fresh LLM honouring the new selection.
    # Lazy import to avoid circular dep with llm_client_factory.
    from app.core.llm_client_factory import _clear_llm_instance_cache
    _clear_llm_instance_cache()
    return normalized


def update_runtime_selection(
    updates: dict[str, str], user_id: str,
) -> dict[str, str]:
    current = get_runtime_selection(user_id)
    current.update({k: v for k, v in updates.items() if v is not None})
    return persist_runtime_selection(current, user_id)


def get_profile_for_role(role: str, user_id: str | None = None) -> ModelProfile:
    """Resolve role → ModelProfile.

    Falls back to ROLE_DEFAULTS if the user's selection points at a
    profile that's no longer in the catalog (rare: vendor retired the
    model since last refresh). Falls back to "first function-calling
    profile in the catalog" if even ROLE_DEFAULTS isn't present (e.g.,
    the vendor's /v1/models temporarily dropped that id).
    """
    profiles = model_catalog._get_all_profiles()
    selection = get_runtime_selection(user_id)
    pid = selection.get(role, ROLE_DEFAULTS[role])
    if pid in profiles:
        return profiles[pid]
    # Fallback chain.
    default_pid = ROLE_DEFAULTS.get(role)
    if default_pid and default_pid in profiles:
        return profiles[default_pid]
    if role == "agent":
        for p in profiles.values():
            if p.supports_function_calling:
                return p
    for p in profiles.values():
        return p
    raise ValueError(
        f"No profile available for role={role!r} — catalog is empty. "
        "Run scripts/refresh_models.py or wait for the daily Celery beat.",
    )


__all__ = [
    "get_runtime_selection",
    "persist_runtime_selection",
    "update_runtime_selection",
    "get_profile_for_role",
]
