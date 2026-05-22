"""Single-doc-per-user "habit & mindset" memory.

Stores the user's stable practice routines, emotional patterns, and
mental-state coping strategies — the things that aren't about specific
interview content but about how the user shows up day-to-day.

Two sections (enforced by extraction prompt):

  ## 稳定的练习节奏
  - 每周一三五各 1 次 mock，二四六休息（持续 3 周稳定）
  ...

  ## 心态与应对
  - 紧张时通过深呼吸缓解
  - 答题超时焦虑已减弱（最近 5 次未提）
  ...

Single row per user, like strategy_doc. The two doc types are
structurally identical — different prompts, different content domain,
same storage shape, both expose ``one_liner`` in the universal pass
(Phase A redesign) and gate full-body load behind the selection LLM.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base


def _generate_habit_doc_id() -> str:
    return f"hdoc_{uuid.uuid4().hex[:12]}"


class HabitDoc(Base):
    __tablename__ = "habit_docs"

    id = Column(String, primary_key=True, default=_generate_habit_doc_id)
    user_id = Column(String, nullable=False, unique=True, index=True)

    body = Column(Text, nullable=False, default="")
    # See strategy_doc.one_liner — same semantics.
    one_liner = Column(String, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
