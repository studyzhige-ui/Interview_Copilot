"""Per-topic knowledge memory document.

One row per (user, topic). The ``topic`` is a coarse subject grouping
the user actually thinks about — "Redis", "TCP", "系统设计", or
non-technical ones like "答题策略" can also live here even though
they're not pure-tech.

Body contents
-------------
A markdown blob with two sections (enforced by extraction prompts, not
by schema):

  ## 已掌握的认知
  - 理解 Redis 雪崩根因是 TTL 集中失效，解法是抖动 + 二级缓存
  - 理解主从复制（数据冗余）vs 集群（分片）是两种独立机制
  ...

  ## 学习进展
  - 已读完《Redis 设计与实现》前 6 章（2026-04-12 用户报告）
  ...

The two sections are kept separate because "认知" entries are durable
claims about understanding, while "学习进展" entries are timestamped
activity reports. Mixing them would make it hard to render a clean
"what I know" view to the user.

Index fields (``one_liner``, ``mastery_level``, ``fact_count``,
``last_discussed_at``) are denormalised from the body so the "list of
all topics" endpoint can return without parsing every body. They are
re-computed by ``knowledge_doc_service`` on every body write.

Vector retrieval was considered (see initial design discussions) and
explicitly rejected: at the small per-user scale we expect (30-50
topics max), an LLM can read the full index list in one prompt and
pick relevant ones better than embedding similarity.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint

from app.db.database import Base


def _generate_knowledge_doc_id() -> str:
    return f"kdoc_{uuid.uuid4().hex[:12]}"


class KnowledgeDoc(Base):
    __tablename__ = "knowledge_docs"

    id = Column(String, primary_key=True, default=_generate_knowledge_doc_id)
    user_id = Column(String, nullable=False, index=True)

    # Topic name. Free-text — extraction LLM is told to prefer an
    # existing topic if the new content fits, so we don't need a
    # closed taxonomy. Common ones: "Redis" / "TCP" / "系统设计" /
    # "答题策略" / "Java 并发" / etc.
    topic = Column(String, nullable=False)

    # The full body. Stable section structure enforced by prompts (see
    # module docstring).
    body = Column(Text, nullable=False, default="")

    # ── Index fields (denormalised, recomputed on every body write) ──

    # One-line summary surfaced in the always-loaded topic index.
    # Capped at ~150 chars to keep the index cheap.
    one_liner = Column(String, nullable=False, default="")

    # LLM's judgement of how well the user knows this topic:
    #   "weak" / "progressing" / "strong" / "unknown"
    # "unknown" is the default for newly-created topics where we don't
    # have enough signal. Distinct from "weak" — it means "haven't
    # judged" not "judged as weak".
    mastery_level = Column(String, nullable=False, default="unknown")

    # Rough count of facts in the body (one per ``- `` bullet line).
    # Useful for the index ("Redis | 8 facts | 强 ...") and for
    # detecting docs that have grown too large.
    fact_count = Column(Integer, nullable=False, default=0)

    # When this topic was last mentioned in any chat session, used to
    # surface staleness in the index. May lag a bit — only updated on
    # extraction, not on every chat turn.
    last_discussed_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", "topic", name="uq_knowledge_doc_user_topic"),
    )
