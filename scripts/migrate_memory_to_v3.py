#!/usr/bin/env python3
"""One-shot migration: legacy ``memory_items`` rows → v3 knowledge_doc topics.

Run after ``alembic upgrade head`` has created the v3 tables. Idempotent —
re-running for a user who's already been migrated is a no-op (we check for
``last_dreamed_at`` markers and existing topic rows).

What it does
============
For each user that has ``memory_items WHERE type='interview_fact'`` rows
(legacy storage), we:

  1. Group rows by the prefix of ``normalized_key`` (everything before
     the second ``_``). E.g. ``ivf_redis_avalanche`` and
     ``ivf_redis_persistence`` cluster under ``redis``.
  2. For each cluster, ask the fast LLM to synthesise one
     ``knowledge_doc`` body in the canonical format (just "已掌握的认知"
     / "学习进展" sections; no QA paste).
  3. Upsert the topic via ``knowledge_doc_service.upsert_user_edit``
     so the audit log records source="migration".

Notes
=====
* user_profile rows in memory_items were retired by an earlier migration
  (the source-of-truth is now ``users.user_profile_doc``), so we only
  touch ``interview_fact`` rows here.
* We do NOT delete the old memory_items rows in this script — the
  Phase 8 cleanup migration handles table teardown after a verification
  period. Use ``--commit`` to actually write; default is dry-run.
* The Milvus memory collection is unrelated to this script's work —
  Phase 8 drops it separately.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

# Make ``app.*`` importable when run as a script.
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("migrate_memory_v3")


_SYNTHESIS_PROMPT = """你正在把一个用户的旧"面试事实记忆"片段合并成新的主题知识文档。

旧片段如下（每条是一句 1-2 句的短记录，来自该用户过去的面试讨论）：

{snippets}

请把这些片段综合成关于「{topic}」的主题文档。**只**输出 markdown 正文（不要解释、不要 JSON），结构必须是：

## 已掌握的认知
- <用户当前确认理解的事实/概念。每行一条，正向陈述>
- ...

## 学习进展
- <用户已完成的学习行为：读完了什么、做了多少 mock、参加了什么练习。带时间最好>
- ...

规则：
- 用**当前认知状态**陈述，不要写历史错误（不要说"以前以为 X 是 Y"，而是"已理解 X = Z"）
- 一次性承诺、AI 单方面建议不要保留
- 旧片段里的题目原文、单题评分都不要复述（那些 SQL 里有）
- 不需要的 section 留空即可，但 ``## 已掌握的认知`` 和 ``## 学习进展`` 两行标题必须保留
"""


def _cluster_key(normalized_key: str) -> str:
    """Map ``ivf_redis_avalanche`` → ``redis``. Falls back to the full
    key for atypical patterns."""
    parts = (normalized_key or "").split("_")
    if len(parts) >= 2 and parts[0] == "ivf":
        return parts[1] if parts[1] else "general"
    if len(parts) >= 2:
        return parts[0]
    return normalized_key or "general"


def _topic_name_from_key(cluster_key: str) -> str:
    """Cluster key → human topic name. Mostly identity; we capitalise
    common acronyms because LLMs match against them."""
    overrides = {
        "redis": "Redis",
        "tcp": "TCP",
        "ip": "IP",
        "http": "HTTP",
        "https": "HTTPS",
        "java": "Java",
        "python": "Python",
        "go": "Go",
        "react": "React",
        "vue": "Vue",
        "mysql": "MySQL",
        "postgres": "Postgres",
        "postgresql": "Postgres",
        "mongodb": "MongoDB",
        "kafka": "Kafka",
        "rabbitmq": "RabbitMQ",
        "docker": "Docker",
        "kubernetes": "Kubernetes",
        "k8s": "Kubernetes",
        "linux": "Linux",
    }
    return overrides.get(cluster_key.lower(), cluster_key)


_MEMORY_ITEMS_TABLE_CACHE: "sa.Table | None" = None


def _memory_items_table(bind):
    """Return a reflected ``memory_items`` table — the ORM model was deleted
    in Phase 8, but the migration script still needs to read the legacy
    table BEFORE alembic ``0003_drop_memory_items`` runs. Reflect on demand
    so this works against any DB that still carries the table.
    """
    global _MEMORY_ITEMS_TABLE_CACHE
    if _MEMORY_ITEMS_TABLE_CACHE is not None:
        return _MEMORY_ITEMS_TABLE_CACHE
    import sqlalchemy as sa

    md = sa.MetaData()
    try:
        _MEMORY_ITEMS_TABLE_CACHE = sa.Table(
            "memory_items", md, autoload_with=bind,
        )
    except sa.exc.NoSuchTableError as exc:
        raise RuntimeError(
            "memory_items table not found — it was already dropped by "
            "alembic 0003. There is nothing to migrate."
        ) from exc
    return _MEMORY_ITEMS_TABLE_CACHE


def _list_users_with_legacy(db) -> list[str]:
    """Distinct user_ids with at least one ``type='interview_fact'`` row."""
    import sqlalchemy as sa

    tbl = _memory_items_table(db.get_bind())
    rows = db.execute(
        sa.select(tbl.c.user_id)
        .where(tbl.c.type == "interview_fact")
        .distinct()
    ).all()
    return [r[0] for r in rows]


def _load_user_clusters(db, user_id: str) -> dict[str, list]:
    """Cluster the user's legacy rows by ``_cluster_key``."""
    import sqlalchemy as sa

    tbl = _memory_items_table(db.get_bind())
    rows = db.execute(
        sa.select(tbl)
        .where(tbl.c.user_id == user_id, tbl.c.type == "interview_fact")
        .order_by(tbl.c.updated_at.asc())
    ).mappings().all()
    clusters: dict[str, list] = defaultdict(list)
    for row in rows:
        clusters[_cluster_key(row["normalized_key"])].append(row)
    return dict(clusters)


def _row_get(row, key: str) -> str:
    """Read a column from either an ORM row or a SQLA RowMapping."""
    try:
        val = row[key]  # RowMapping (dict-like)
    except (KeyError, TypeError):
        val = getattr(row, key, None)
    return (val or "").strip() if isinstance(val, str) else ""


async def _synthesise_body(topic: str, rows: Iterable) -> str:
    """Call the fast LLM to merge legacy rows into a v3 body."""
    from app.rag.embeddings import agent_fast_llm

    snippets = "\n".join(
        f"- {_row_get(r, 'description')}: {_row_get(r, 'content')}"
        for r in rows
    )
    prompt = _SYNTHESIS_PROMPT.format(topic=topic, snippets=snippets)
    try:
        response = await agent_fast_llm.acomplete(prompt)
        return str(response.text or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("synthesise body failed for topic=%s: %s", topic, exc)
        # Fallback: drop the snippets in verbatim so we don't lose
        # information. The user can edit afterwards.
        fallback_lines = ["## 已掌握的认知", ""]
        for r in rows:
            line = (_row_get(r, "description") or _row_get(r, "content")).split("\n")[0]
            if line:
                fallback_lines.append(f"- {line[:200]}")
        fallback_lines.extend(["", "## 学习进展", ""])
        return "\n".join(fallback_lines)


async def migrate_user(user_id: str, *, commit: bool) -> dict:
    """Migrate one user's legacy memory rows. Returns counts."""
    from app.db.database import SessionLocal
    from app.services.memory import knowledge_doc_service

    stats = {
        "user_id": user_id,
        "legacy_rows": 0,
        "clusters": 0,
        "created_topics": 0,
        "skipped_existing": 0,
        "errors": 0,
    }

    db = SessionLocal()
    try:
        clusters = _load_user_clusters(db, user_id)
    finally:
        db.close()

    if not clusters:
        return stats

    stats["legacy_rows"] = sum(len(v) for v in clusters.values())
    stats["clusters"] = len(clusters)

    for cluster_key, rows in clusters.items():
        topic = _topic_name_from_key(cluster_key)
        # Idempotency check: skip if a topic doc already exists.
        existing = knowledge_doc_service.load(user_id, topic)
        if existing is not None and (existing.body or "").strip():
            logger.info(
                "[%s] skip topic=%s (already exists with %d facts)",
                user_id, topic, existing.fact_count,
            )
            stats["skipped_existing"] += 1
            continue

        body = await _synthesise_body(topic, rows)
        if not body.strip():
            logger.warning("[%s] empty body synthesised for topic=%s", user_id, topic)
            stats["errors"] += 1
            continue

        if not commit:
            logger.info(
                "[DRY-RUN %s] would create topic=%s (%d source rows). Preview:\n%s\n",
                user_id, topic, len(rows), body[:400],
            )
            stats["created_topics"] += 1
            continue

        try:
            knowledge_doc_service.upsert_user_edit(
                user_id=user_id,
                topic=topic,
                new_body=body,
            )
            stats["created_topics"] += 1
            logger.info(
                "[%s] created topic=%s from %d legacy rows",
                user_id, topic, len(rows),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[%s] failed to create topic=%s: %s", user_id, topic, exc)
            stats["errors"] += 1

    return stats


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write the new topics (default is dry-run).",
    )
    parser.add_argument(
        "--user",
        help="Migrate only this user_id (default: all users with legacy rows).",
    )
    args = parser.parse_args()

    from app.db.database import SessionLocal

    if args.user:
        users = [args.user]
    else:
        db = SessionLocal()
        try:
            users = _list_users_with_legacy(db)
        finally:
            db.close()

    if not users:
        logger.info("No users with legacy memory_items rows. Nothing to do.")
        return 0

    logger.info(
        "Migrating %d user(s), commit=%s. Dry-run is the default.",
        len(users), args.commit,
    )

    totals = {
        "users_processed": 0,
        "legacy_rows": 0,
        "clusters": 0,
        "created_topics": 0,
        "skipped_existing": 0,
        "errors": 0,
    }
    for uid in users:
        try:
            stats = await migrate_user(uid, commit=args.commit)
            totals["users_processed"] += 1
            for k in ("legacy_rows", "clusters", "created_topics",
                      "skipped_existing", "errors"):
                totals[k] += stats[k]
        except Exception as exc:  # noqa: BLE001
            logger.exception("Migration crashed for user=%s: %s", uid, exc)
            totals["errors"] += 1

    logger.info("== summary ==")
    for k, v in totals.items():
        logger.info("  %s: %s", k, v)
    return 0 if totals["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
