from sqlalchemy import Boolean, CheckConstraint, Column, Integer, String, Text

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "default_execution_mode IN ('standard', 'auto')",
            name="ck_users_default_execution_mode",
        ),
    )

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    # ── Token invalidation baseline ──────────────────────────────────
    # Stamped into every access/refresh JWT at issuance (see
    # ``security.token_claims_for``) and re-checked in ``get_current_user``
    # / ``/auth/refresh``. Incrementing it (on password change / reset)
    # makes EVERY previously-issued token fail the version check on its
    # next use — instant logout-everywhere without enumerating jti's into
    # the Redis blacklist. Starts at 0; only ever moves forward.
    token_version = Column(Integer, default=0, nullable=False, server_default="0")
    # When the password was last changed. NULL = never changed since
    # registration. Audit / display only — the security guarantee is
    # carried by ``token_version``, not this timestamp.
    password_changed_at = Column(DateTime, nullable=True)
    nickname = Column(String(64), nullable=True)
    # Stores an object-storage URI, local fallback URI, or public HTTP URL.
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    # Default for newly created Conversations only. Existing Conversations and
    # admitted Turns keep their own snapshots, so changing this cannot widen a
    # PersistentTask or an already-running task.
    default_execution_mode = Column(
        String(16), nullable=False, default="standard", server_default="standard"
    )
    # Per-user model-role selection moved out to the ``user_model_selections``
    # table (one row per role, keyed by the stable users.id) — see
    # app.models.user_model_selections / app.core.user_model_selection.
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)
