from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
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
    # Widened to Text so we can inline ~1MB image as `data:` URL (≈1.4MB
    # base64). Plain http(s) URLs still fit fine.
    avatar_url = Column(Text, nullable=True)
    bio = Column(Text, nullable=True)
    # Per-user default for the GLOBAL (cross-session) memory toggle.
    # When False, the LLM does NOT see the v3 memory bundle
    # (user_profile + ability states + learning_strategy) — only
    # session-local context (recent_turns, debrief reference) reaches
    # the prompt. Matches Claude Code's
    # ``isAutoMemoryEnabled`` semantics — global memdir off; per-
    # session context untouched.
    #
    # Storage is unaffected: this is an INJECTION gate. The user's
    # personalization page can still read memory_documents /
    # memory_ability_states directly to render their memory inventory.
    #
    # Opt-in (default False) for new users — they get vanilla chat
    # until they curate their memory and explicitly opt in.
    #
    # A per-session override lives in the
    # ``conversations.global_memory_enabled`` column; service code reads the
    # session value first and falls back here.
    global_memory_enabled = Column(Boolean, default=False, nullable=False)
    # When the nightly dreaming worker last consolidated this user's
    # memory docs. NULL = never dreamed. Used as the "cursor" by the
    # autoDream gate logic: the next nightly run only fires for this
    # user if (a) it's been >=24h since this timestamp AND (b) the
    # user has accumulated enough new chat activity since then. See
    # ``app.services.memory.dreaming_worker``.
    last_dreamed_at = Column(DateTime, nullable=True)
    # Per-user model-role selection moved out to the ``user_model_selections``
    # table (one row per role, keyed by the stable users.id) — see
    # app.models.user_model_selections / app.core.user_model_selection.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
