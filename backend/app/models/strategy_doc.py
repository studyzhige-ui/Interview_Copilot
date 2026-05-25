"""Single-doc-per-user "interview answering strategy" memory.

Stores cross-topic methodology the user has either committed to trying
or actually internalised. Two sections (enforced by extraction prompt):

  ## 已内化
  - 先分析根因后给方案（2026-03-22 验证有效）
  - STAR 框架用于行为面试
  ...

  ## 尝试中
  - 反问环节尝试技术问题而不是 work-life balance（2026-04-10 起）
  ...

The "尝试中 → 已内化" promotion happens during dreaming when the user
reports the method actually worked across multiple uses.

One row per user. Loaded in two layers (Phase A redesign):

  * Universal pass: ONLY the ``one_liner`` description goes into every
    chat turn's prompt. Cheap (~50 chars).
  * On-demand: when the selection LLM marks ``load_strategy=true``
    for the current query, the full ``body`` is loaded.

This mirrors knowledge_doc's index-then-body pattern and matches
Claude Code's "expose description, let LLM decide if it wants the
content".
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text

from app.db.database import Base


def _generate_strategy_doc_id() -> str:
    return f"sdoc_{uuid.uuid4().hex[:12]}"


class StrategyDoc(Base):
    __tablename__ = "strategy_docs"
    # Single source of truth for the uniqueness contract: one row per
    # user, enforced as a unique INDEX (not a column-level constraint).
    # Pre-0010 the migration created BOTH a column-level unique constraint
    # AND a non-unique index — redundant and made every insert pay two
    # index writes. 0010 drops the constraint and promotes the index
    # to unique; the ORM matches that shape now.
    __table_args__ = (
        Index("ix_strategy_docs_user_id", "user_id", unique=True),
    )

    id = Column(String, primary_key=True, default=_generate_strategy_doc_id)
    user_id = Column(String, nullable=False)

    body = Column(Text, nullable=False, default="")
    # One-line description exposed in the universal pass so the
    # selection LLM can decide whether to load the full body for
    # this turn. Maintained by ``SingleDocService._derive_one_liner``;
    # falls back to a short summary of the doc when LLM hasn't
    # provided one. Empty = no doc yet.
    one_liner = Column(String, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
