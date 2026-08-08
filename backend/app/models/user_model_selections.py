"""Per-user answer-model selection.

The only current role is ``primary``. Chat, Agent and mock interview share
that answer model; platform-owned router/worker models never enter this table.
A missing row falls back to ``ROLE_DEFAULTS``.

Keyed by the stable ``users.id`` (FK, ON DELETE CASCADE) with a unique
(user_id, role) constraint so each role resolves to exactly one model. The
system model catalog is NOT in the DB — ``profile_id`` is validated against
the live catalog (code / Redis) at read/write time.
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)

from app.db.database import Base
from app.db.types import UTCDateTime as DateTime
from app.db.types import utc_now


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
    # Reserved for the canonical "primary" answer role.
    role = Column(String(32), nullable=False)
    # "{provider}/{model}" — the runtime catalog key. The provider/model split
    # is derivable from this; we store the single canonical id the resolver
    # uses rather than a denormalised copy that could drift.
    profile_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
