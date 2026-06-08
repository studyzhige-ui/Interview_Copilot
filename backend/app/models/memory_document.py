"""``memory_documents``: global long-term user state as markdown documents.

One row per ``(user, doc_type)``. Holds the two *global* memory documents
(as opposed to per-topic ability states, which live in
``memory_ability_states``):

* ``user_profile``     — background, goals, preferences, expression style,
                         stable behavioural tendencies.
* ``learning_strategy``— long-term training / review / answering strategy.

This table supersedes the old split of ``users.user_profile_doc`` (column),
``strategy_docs`` and ``habit_docs`` (tables): ``habit`` is no longer its own
type — expression/behaviour traits fold into ``user_profile`` and training
methods fold into ``learning_strategy``.

The ``body`` is a markdown blob patched in place via the exact-line patch
protocol (see ``app.services.memory._doc_patch_protocol``); ``one_liner`` is a
denormalised preview surfaced in the always-loaded universal pass so the
prompt doesn't have to carry the full body every turn.

``user_id`` is the stable ``users.id`` (the runtime threads a username and the
service resolves it via ``app.core.user_identity.resolve_user_pk``).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.database import Base

# The only two document types Memory keeps as global state. ``knowledge`` and
# ``habit`` from the old design are gone — knowledge/ability now lives in
# ``memory_ability_states``; habit folds into the two below.
DOC_TYPES = ("user_profile", "learning_strategy")


def generate_memory_document_id() -> str:
    return f"mdoc_{uuid.uuid4().hex[:12]}"


class MemoryDocument(Base):
    __tablename__ = "memory_documents"
    __table_args__ = (
        # One document per type per user.
        UniqueConstraint("user_id", "doc_type", name="uq_memory_document_user_type"),
    )

    id = Column(String, primary_key=True, default=generate_memory_document_id)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # user_profile / learning_strategy (see DOC_TYPES).
    doc_type = Column(String, nullable=False)
    # Markdown body, patched in place. Empty string for a freshly-created doc.
    body = Column(Text, nullable=False, default="")
    # Denormalised preview for the always-loaded universal pass; recomputed on
    # every body write.
    one_liner = Column(String, nullable=False, default="")
    # When this document's subject was last discussed (lags — only bumped on
    # extraction, not every turn).
    last_discussed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
