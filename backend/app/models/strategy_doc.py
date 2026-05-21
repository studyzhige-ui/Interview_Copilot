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

This is one row per user. Loaded fully into context — no index layer
needed because the doc is small.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from app.db.database import Base


def _generate_strategy_doc_id() -> str:
    return f"sdoc_{uuid.uuid4().hex[:12]}"


class StrategyDoc(Base):
    __tablename__ = "strategy_docs"

    id = Column(String, primary_key=True, default=_generate_strategy_doc_id)
    # Unique by user — one strategy doc per user. We don't add a
    # UniqueConstraint because the service enforces single-row
    # semantics via upsert anyway.
    user_id = Column(String, nullable=False, unique=True, index=True)

    body = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )
