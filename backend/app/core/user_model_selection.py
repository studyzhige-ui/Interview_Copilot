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
from app.core.model_catalog import ROLE_DEFAULTS, USER_SELECTABLE_ROLES, ModelProfile

logger = logging.getLogger(__name__)


# Single lock for selection-state writes. The LLM caches in
# ``llm_client_factory`` carry their own lock; ``persist_runtime_selection``
# triggers the cache clear via a lazy import to avoid a circular dep.
_selection_lock = Lock()


def _normalize_selection(raw: dict[str, str]) -> dict[str, str]:
    """Clamp a raw selection dict to known-valid profile ids.

    Unknown ids fall back to ROLE_DEFAULTS for that role. Retired alias
    safeguards (the legacy ``deepseek-chat`` / ``deepseek-reasoner`` short ids
    from pre-P6-L) are still dropped so old persisted selections
    upgrade cleanly without surfacing as "missing profile" errors.
    """
    profiles = model_catalog._get_all_profiles()
    selection = dict(ROLE_DEFAULTS)
    # Only user-facing roles are read from input. Platform-owned internal
    # roles never enter the per-user selection map.
    for role in USER_SELECTABLE_ROLES:
        candidate = raw.get(role)
        # Drop pre-P6-L bare ids (no "provider/" prefix). They aren't
        # valid in the new "provider/model" id scheme.
        if not candidate or "/" not in candidate:
            continue
        if candidate in profiles:
            selection[role] = candidate

    return selection


def _load_user_selection(user_id: str) -> dict[str, str]:
    """Read a user's role→profile_id selection rows from the DB.

    ``user_id`` is the runtime principal (username); we join to ``users`` so
    the actual filter is on the stable id. A partial result is fine —
    ``_normalize_selection`` fills any unset role from ROLE_DEFAULTS.
    (Legacy ``role='fast'`` rows may linger here; normalize ignores them and
    the next save full-replaces the user's rows.)
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
            "Failed to load model selection for user=%s: %s",
            user_id,
            exc,
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
        db.add_all(
            [
                UserModelSelection(user_id=user_pk, role=role, profile_id=pid)
                for role, pid in selection.items()
            ]
        )
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
    selection: dict[str, str],
    user_id: str,
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
    updates: dict[str, str],
    user_id: str,
) -> dict[str, str]:
    current = get_runtime_selection(user_id)
    current.update({k: v for k, v in updates.items() if v is not None})
    return persist_runtime_selection(current, user_id)


def get_profile_for_role(role: str, user_id: str | None = None) -> ModelProfile:
    """Resolve role → ModelProfile, preferring profiles the CALLER is ready
    for (their key or an env key resolves).

    One ordered candidate walk, two passes:
      pass 1 (ready-only):  user's selection → role default → user's primary
                            → rest of the catalog (function-calling first)
      pass 2 (anything):    same order, readiness ignored — the historical
                            behaviour for a caller with zero keys, so the
                            provider call surfaces a visible auth error
                            instead of failing here.
    Agent-mode compatibility is checked when Agent mode starts.

    Pre-MDL-1 this ignored readiness entirely: a new user with only an
    OpenAI key kept resolving to the deepseek defaults and every chat
    401'd while the Models page showed green.
    """
    if role not in USER_SELECTABLE_ROLES:
        raise ValueError(f"Unknown user-selectable model role: {role}")

    # Lazy import — llm_client_factory imports this module at its top, so
    # the reverse edge must stay function-local (same pattern as the cache
    # clear in persist_runtime_selection).
    from app.core.llm_client_factory import ready_profile_ids

    profiles = model_catalog._get_all_profiles()
    selection = get_runtime_selection(user_id)
    ready = ready_profile_ids(profiles, user_id)

    selected_pid = selection.get(role) or ROLE_DEFAULTS.get(role)
    catalog_rest = sorted(
        profiles.values(),
        key=lambda p: (not p.supports_function_calling, p.id),
    )
    candidates: list[tuple[str | None, str]] = [
        (selected_pid, "selection"),
        (ROLE_DEFAULTS.get(role), "role default"),
        (selection.get("primary"), "user primary selection"),
        *[(p.id, "first usable catalog profile") for p in catalog_rest],
    ]

    def _pick(require_ready: bool) -> tuple[ModelProfile, str] | None:
        for pid, why in candidates:
            if not pid or pid not in profiles:
                continue
            profile = profiles[pid]
            if require_ready and pid not in ready:
                continue
            return profile, why
        return None

    hit = _pick(require_ready=True) or _pick(require_ready=False)
    if hit is None:
        raise ValueError(
            f"No profile available for role={role!r} — catalog is empty. "
            "Run scripts/refresh_models.py or wait for the daily Celery beat.",
        )
    profile, why = hit
    if why != "selection":
        logger.warning(
            "model selection degraded: role=%s user=%s wanted=%s -> %s (%s)",
            role,
            user_id,
            selected_pid,
            profile.id,
            why,
        )
    return profile


__all__ = [
    "get_runtime_selection",
    "persist_runtime_selection",
    "update_runtime_selection",
    "get_profile_for_role",
]
