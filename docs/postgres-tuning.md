# Postgres Tuning Cheat-Sheet

The Postgres defaults are conservative for late-90s hardware. On a
modern VPS (4–16 GB RAM, SSD) the values below typically buy a 2–10×
speedup on the workloads this project actually runs (chat history list,
interview record dashboard, RAG retrieval planning).

## Production `postgresql.conf` overrides

Drop these into a `postgresql.conf` snippet (or apply via `ALTER SYSTEM`).
Numbers below assume **8 GB RAM** dedicated to the DB; scale linearly.

```ini
# ── Memory ────────────────────────────────────────────────────────────
shared_buffers              = 2GB     # 25% of RAM. Postgres' own page cache.
effective_cache_size        = 6GB     # Hint: how much OS+PG cache exists.
                                       # Used by the planner; doesn't allocate.
work_mem                    = 32MB    # Per sort/JOIN/hash. Multiply by max
                                       # concurrent ops (≈ connections × 2).
maintenance_work_mem        = 512MB   # VACUUM / CREATE INDEX. Higher = faster
                                       # one-shot ops; only one at a time.

# ── Connections ───────────────────────────────────────────────────────
max_connections             = 200     # Match: workers × (POOL+OVERFLOW)
                                       # + celery + 20 admin headroom.
                                       # Default 100 is too tight for any
                                       # multi-worker uvicorn deploy.

# ── Disk / WAL ────────────────────────────────────────────────────────
wal_buffers                 = 16MB
checkpoint_completion_target = 0.9    # Spread checkpoint writes evenly,
                                       # avoid IO spikes.
random_page_cost            = 1.1     # SSD! Default 4.0 assumes spinning
                                       # disk and discourages index scans.
effective_io_concurrency    = 200     # SSD parallelism hint (Linux).

# ── Logging — find slow queries ──────────────────────────────────────
log_min_duration_statement  = 500     # ms. Anything slower lands in the log.
log_lock_waits              = on
log_temp_files              = 0       # Catches work_mem spills to disk.

# ── Autovacuum ────────────────────────────────────────────────────────
autovacuum_vacuum_scale_factor = 0.05 # Vacuum more aggressively (default
                                       # 0.2 is too lazy for write-heavy tables
                                       # like chat_messages / interview_qa).
autovacuum_analyze_scale_factor = 0.02

# ── Stats / observability ─────────────────────────────────────────────
track_io_timing             = on      # pg_stat_statements gets I/O numbers.
shared_preload_libraries    = 'pg_stat_statements'
pg_stat_statements.track    = top
```

After editing, restart Postgres (most settings live-reload, but
`shared_buffers` and `max_connections` need a restart):

```bash
sudo systemctl restart postgresql
# or in Docker:
docker compose restart db
```

## Recommended extensions

Run these once against your DB:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- for ILIKE / similarity search
```

`pg_stat_statements` is what unlocks "show me the top 10 slowest queries"
view (see queries below). `pg_trgm` accelerates fuzzy text search if you
ever add it to library / records search.

## Find what's actually slow

After running for a few hours / days under real traffic:

```sql
-- Top 20 slowest queries by total time
SELECT
  round(total_exec_time::numeric, 2) AS total_ms,
  calls,
  round(mean_exec_time::numeric, 2)  AS avg_ms,
  round((100 * total_exec_time / sum(total_exec_time) OVER ())::numeric, 1) AS pct,
  query
FROM pg_stat_statements
ORDER BY total_exec_time DESC
LIMIT 20;

-- Top 20 most-called queries (catches N+1)
SELECT calls, round(mean_exec_time::numeric, 2) AS avg_ms, query
FROM pg_stat_statements
ORDER BY calls DESC
LIMIT 20;

-- Reset the snapshot to start fresh
SELECT pg_stat_statements_reset();
```

For any slow query, `EXPLAIN (ANALYZE, BUFFERS) <query>` shows the
actual plan. `Seq Scan` over a big table is the smoking gun → add an
index that matches the WHERE / ORDER BY shape (composite if both).

## Index audit (current state)

Migration `0001_baseline` (a squash of the historical 0001–0019 chain)
ships every composite that matters for the hot query shapes. New
incremental migrations (`0012`, `0013`) on top of that baseline only
add per-user model-selection columns + provider-settings tables and
do not introduce new composites.

| Index name                          | Table              | Columns                                  | Use case                              |
|-------------------------------------|--------------------|------------------------------------------|---------------------------------------|
| `ix_chat_messages_session_seq`      | chat_messages      | (session_id, seq)                        | History fetch in render order         |
| `ix_interview_records_user_created` | interview_records  | (user_id, created_at)                    | Dashboard pagination                  |
| `ix_chat_sessions_user_type_arch`   | chat_sessions      | (user_id, session_type, archived_at)     | Mock-interview "in-progress" lookup   |
| `ix_knowledge_docs_user_category`   | knowledge_documents| (user_id, category)                      | Library filter sidebar                |
| `ix_memory_items_user_type_key`     | memory_items       | (user_id, type, normalized_key)          | Memory upsert-by-key                  |
| `ix_user_uploads_user_purpose`      | user_uploads       | (user_id, purpose)                       | Resume / JD picker                    |
| `ix_interview_qa_record_order`      | interview_qa       | (record_id, order_idx)                   | QAPanel ordered render                |

Run `\d+ <table>` in psql to see all indexes per table. If a real-world
query shows up at the top of `pg_stat_statements` and isn't covered
above, that's a candidate for a new composite.

## Don't over-index

Each index slows down INSERT / UPDATE on the indexed table by a fixed
percentage. The tables that get written most often (chat_messages,
interview_qa) are kept lean intentionally — only one composite each.
Resist the urge to "index everything just in case."

## When you outgrow this

If `pg_stat_statements` shows your DB pegged near 100% CPU and you've
already done all of the above:

1. Vertical scale (bigger box) — usually the right answer up to 8× current.
2. Add a read replica (we deferred this to a separate phase).
3. Move bulky audit / log tables to TimescaleDB or a separate warm
   storage. Don't go there yet.
