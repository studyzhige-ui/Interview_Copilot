# Postgres 调优速查

Postgres 默认配置是为 90 年代末硬件调的。在现代 VPS（4–16 GB RAM、SSD）上，下面的参数通常能让本项目实际跑的查询（聊天历史列表、面试记录 dashboard、RAG 检索规划）快 2–10 倍。

## 生产环境 `postgresql.conf` 覆盖

把下面的 snippet 放进 `postgresql.conf`（或用 `ALTER SYSTEM`）。数值假设给 DB **8 GB RAM**；按比例缩放即可。

```ini
# ── 内存 ──────────────────────────────────────────────────────────────
shared_buffers              = 2GB     # RAM 的 25%。Postgres 自己的 page 缓存。
effective_cache_size        = 6GB     # 提示规划器：OS + PG 缓存大概多少。
                                       # 只用于估算成本，不会真分配。
work_mem                    = 32MB    # 每个 sort / JOIN / hash 的临时空间。
                                       # 上限约 = 并发连接 × 2 × work_mem。
maintenance_work_mem        = 512MB   # VACUUM / CREATE INDEX。越大越快，
                                       # 但同时只能跑一个。

# ── 连接数 ────────────────────────────────────────────────────────────
max_connections             = 200     # 必须 ≥ workers × (POOL+OVERFLOW)
                                       # + celery + 20 留给运维 psql。
                                       # 默认 100 在多 worker uvicorn 下太挤。

# ── 磁盘 / WAL ────────────────────────────────────────────────────────
wal_buffers                 = 16MB
checkpoint_completion_target = 0.9    # 把 checkpoint 写入摊匀，避免 IO 尖峰。
random_page_cost            = 1.1     # SSD 必改！默认 4.0 是机械盘的成本，
                                       # 会劝退规划器使用索引。
effective_io_concurrency    = 200     # SSD 并行度提示（Linux）。

# ── 日志 — 找慢查询 ─────────────────────────────────────────────────
log_min_duration_statement  = 500     # 毫秒。慢于此值的查询会写日志。
log_lock_waits              = on
log_temp_files              = 0       # 抓 work_mem 溢出到磁盘的查询。

# ── Autovacuum ────────────────────────────────────────────────────────
autovacuum_vacuum_scale_factor = 0.05 # 默认 0.2 对 chat_messages /
                                       # interview_qa 这种写多的表太慢。
autovacuum_analyze_scale_factor = 0.02

# ── 统计 / 可观测 ─────────────────────────────────────────────────────
track_io_timing             = on      # pg_stat_statements 拿 I/O 数据。
shared_preload_libraries    = 'pg_stat_statements'
pg_stat_statements.track    = top
```

改完重启 Postgres（大部分参数热加载，但 `shared_buffers` 和 `max_connections` 必须重启）：

```bash
sudo systemctl restart postgresql
# 或者 Docker:
docker compose restart db
```

## 推荐扩展

对你的 DB 跑一次：

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- 用于 ILIKE / 模糊搜索
```

`pg_stat_statements` 解锁「最慢的 10 条 SQL」视图（见下文 SQL）。`pg_trgm` 加速模糊文本搜索（如果你后续要在 Library / 记录里加搜索框）。

## 找出真正慢的查询

线上跑一段时间后：

```sql
-- 总耗时最高的 20 条
SELECT
  round(total_exec_time::numeric, 2) AS total_ms,
  calls,
  round(mean_exec_time::numeric, 2)  AS avg_ms,
  round((100 * total_exec_time / sum(total_exec_time) OVER ())::numeric, 1) AS pct,
  query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;

-- 调用次数最高的 20 条（抓 N+1）
SELECT calls, round(mean_exec_time::numeric, 2) AS avg_ms, query
FROM pg_stat_statements
ORDER BY calls DESC
LIMIT 20;

-- 重置统计快照
SELECT pg_stat_statements_reset();
```

对任何慢查询，`EXPLAIN (ANALYZE, BUFFERS) <query>` 显示真实执行计划。如果看到大表的 `Seq Scan` 就是确凿证据 → 加一个匹配 WHERE / ORDER BY 形状的索引（一般是复合索引）。

## 当前索引审计

迁移 `0001_baseline`（历史 0001–0019 的 squash 合并）已经覆盖了所有
高频查询形状的复合索引。后续增量迁移（`0012`、`0013`）只增加每用户
模型选择列 + provider settings 表，没有新增复合索引。

| 索引名                              | 表                | 索引列                                       | 用途                                  |
|-------------------------------------|-------------------|---------------------------------------------|---------------------------------------|
| `ix_chat_messages_session_seq`      | chat_messages     | (session_id, seq)                           | 按渲染顺序拉历史                       |
| `ix_interview_records_user_created` | interview_records | (user_id, created_at)                       | Dashboard 分页                         |
| `ix_chat_sessions_user_type_arch`   | chat_sessions     | (user_id, session_type, archived_at)        | 模拟面试 in-progress 检测              |
| `ix_knowledge_docs_user_category`   | knowledge_documents | (user_id, category)                       | Library 分类筛选                       |
| `ix_memory_items_user_type_key`     | memory_items      | (user_id, type, normalized_key)             | Memory upsert-by-key                   |
| `ix_user_uploads_user_purpose`      | user_uploads      | (user_id, purpose)                          | 简历 / JD 选择器                       |
| `ix_interview_qa_record_order`      | interview_qa      | (record_id, order_idx)                      | QAPanel 按序渲染                       |

在 psql 里跑 `\d+ <表名>` 看每张表的所有索引。如果某条查询经常出现在 `pg_stat_statements` 顶部但没在上表覆盖范围里，那就是新复合索引的候选。

## 不要乱加索引

每个索引让该表的 INSERT / UPDATE 变慢一个固定百分比。写最频繁的两张表（chat_messages、interview_qa）只各加一个复合索引就是这个原因。"以防万一加上"是个坑。

## 真的不够用怎么办

如果 `pg_stat_statements` 显示 DB CPU 接近 100%，并且上面这些都做完了：

1. **垂直扩容**（更大机器）—— 一般够用到当前规模 ×8
2. 加只读副本（Phase 计划里推迟到了下个阶段）
3. 把 audit / log 等大表迁到 TimescaleDB 或冷存储 —— 现在还不需要
