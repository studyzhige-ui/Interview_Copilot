"""Per-user model-role selection (one row per role).

Replaces the old ``users.model_selection_json`` blob: each role the user has
chosen a model for (``primary`` / ``fast`` / ``agent`` / ``mock_interview`` /
...) is one row mapping to a ``profile_id`` (``"{provider}/{model}"``), the
key the runtime catalog resolves. A missing role row = fall back to
``ROLE_DEFAULTS``.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE) with a unique
(user_id, role) constraint so each role resolves to exactly one model. The
system model catalog is NOT in the DB — ``profile_id`` is validated against
the live catalog (code / Redis) at read/write time.
"""
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.database import Base


class UserModelSelection(Base):
    __tablename__ = "user_model_selections"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_user_model_selections_user_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Role this selection drives: primary / fast / agent / mock_interview / ...
    role = Column(String(32), nullable=False)
    # "{provider}/{model}" — the runtime catalog key. The provider/model split
    # is derivable from this; we store the single canonical id the resolver
    # uses rather than a denormalised copy that could drift.
    profile_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
