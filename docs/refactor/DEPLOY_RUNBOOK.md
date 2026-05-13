# 模拟面试重构 — 部署 Runbook

本次重构是**有损迁移**：会 drop 老的 `interviews / transcripts / analysis_results` 三张表。
不可降级。按本文档顺序执行。

---

## 0. 前置检查

```bash
# 你在哪个分支
git status
git rev-parse HEAD

# alembic 当前 head 是 0008_drop_legacy_interview_tables
ls alembic/versions/ | tail -3
```

应看到：
```
0006_chat_memory_cursor.py
0007_unified_interview_schema.py
0008_drop_legacy_interview_tables.py
```

---

## 1. 备份数据库

```bash
# PostgreSQL（生产 / 本地）
pg_dump -h localhost -U postgres -d interview_copilot \
    > backups/interview_copilot_pre_0008_$(date +%Y%m%d_%H%M%S).sql

# 额外把三张老表单独 dump 留 30 天（删表前再做一次备份是工程纪律）
pg_dump -h localhost -U postgres -d interview_copilot \
    -t interviews -t transcripts -t analysis_results \
    > backups/legacy_tables_pre_drop_$(date +%Y%m%d_%H%M%S).sql
```

**SQLite 用户**：直接复制 db 文件。

---

## 2. 在沙盒上预演迁移（可选但强烈推荐）

```bash
cd backend
python scripts/validate_migration.py
```

期望输出：
```
[1/4] Building baseline schema
[2/4] Seeding legacy + mock fixtures
[3/4] Running alembic upgrade head (0006 → 0007 → 0008)
[4/4] Asserting post-migration schema and data
✅ Migration validation passed.
```

如果失败，**不要在真库上跑** —— 先排查 alembic 脚本错误。

---

## 3. 停掉 Celery worker

旧的 worker 期望 `process_interview_analysis(interview_id: int)`，新代码改成 `(record_id: str)`。
中间共存会让旧 worker 在新任务上崩。

```bash
# systemd
sudo systemctl stop celery-worker

# 或者直接 kill
ps aux | grep "celery -A app.worker" | awk '{print $2}' | xargs kill -TERM

# 等 5 秒确认进程退出
sleep 5
ps aux | grep -c "celery" || true
```

清空 broker 中的待处理任务（防止旧任务签名打到新代码）：

```bash
# Redis broker
redis-cli FLUSHDB

# 或更精细 —— 只清 celery 队列
redis-cli DEL celery
```

---

## 4. 把 API 服务设为只读 / 维护模式（可选）

如果用户量大、不能容忍 5 分钟停机，把 nginx/网关切到维护页。
对于个人项目跳过即可，直接进 step 5。

---

## 5. 跑 alembic 迁移

```bash
cd /path/to/Interview_Copilot
# 确认 .env / DATABASE_URL 指向生产库
echo $DATABASE_URL  # 或 cat backend/.env | grep DATABASE_URL

alembic upgrade head
```

期望日志：
```
INFO  [alembic.runtime.migration] Running upgrade 0006_chat_memory_cursor -> 0007_unified_interview_schema
INFO  [alembic.runtime.migration] Running upgrade 0007_unified_interview_schema -> 0008_drop_legacy_interview_tables
```

**如果失败**：
- 0007 失败 → 老表完好，回滚是 `alembic downgrade -1`。
- 0008 失败 → 0007 已生效但老表可能还在。**不要再跑 0008**；先看错误，必要时从 step 1 的备份恢复整个 DB。

---

## 6. 验证迁移结果

```bash
psql interview_copilot -c "
  SELECT table_name FROM information_schema.tables
  WHERE table_schema='public' AND table_name IN
    ('interview_qa','mock_interview_sessions','interviews','transcripts','analysis_results')
  ORDER BY table_name;
"
```

期望：`interview_qa`、`mock_interview_sessions` 存在，三张老表不存在。

```bash
psql interview_copilot -c "SELECT version_num FROM alembic_version;"
```
期望：`0008_drop_legacy_interview_tables`

```bash
psql interview_copilot -c "
  SELECT source, status, COUNT(*) FROM interview_records
  GROUP BY source, status ORDER BY 1, 2;
"
```
观察 record 总数应≥迁移前 `SELECT COUNT(*) FROM interviews;` 的数。

---

## 7. 启动新代码

```bash
# Backend API
sudo systemctl restart api-server
# 或: cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000

# Celery worker（新签名）
sudo systemctl start celery-worker
# 或: cd backend && celery -A app.worker.celery_app worker -l info
```

确认 worker 已就绪：
```bash
journalctl -u celery-worker -n 50
```
应看到 worker 注册了 `tasks.process_interview_analysis` 而无 traceback。

---

## 8. 烟测端到端

### 8.1 Upload 路径

1. 前端 `/review` → 「+」新建草稿 → 上传音频 + 简历 + JD → 开始分析
2. 观察 SSE 进度条从 0% 推到 100%
3. 完成后右侧 QAPanel 显示 `qa[]` 列表 + overall 评分
4. 后端日志应看到 `analysis_orchestrator` 走 upload 分支（transcribing → extracting → analyzing → completed）

### 8.2 Mock 路径

1. 前端 `/mock` → 上传简历 + JD → 选风格 → 选 hybrid 语音模式 → 开始
2. 第一题问出来后页面应能听到 TTS 朗读（hybrid/voice 模式）
3. 用麦克风或文字回答 2-3 题 → 点结束
4. 应跳转 `/review?id=ir_xxx` → 看到 AnalyzingState 进度卡
5. 完成后渲染 QA 列表，每条 QA 有 `grounding_refs`（在数据库里可查 `SELECT grounding_refs_json FROM interview_qa WHERE record_id=…`）

### 8.3 中途断线恢复

1. 开 mock 答 1 题 → 关浏览器（不点结束）
2. 重新打开 `/mock` → 顶部应出现「你有一个未完成的模拟面试 · 已答 1 题」黄色 banner
3. 点「继续」进入 MockLive → 看到第 2 题
4. 点「放弃」应清掉 banner，正常进入 setup

---

## 9. 监控（首小时）

```bash
# Celery 任务失败率
journalctl -u celery-worker -f | grep -E "(FAILED|status': 'failed)"

# 后端日志里的 orchestrator 错误
journalctl -u api-server -f | grep "Orchestrator failed"

# DB 健康
psql interview_copilot -c "
  SELECT status, COUNT(*) FROM interview_records
  WHERE created_at > NOW() - INTERVAL '1 hour'
  GROUP BY status;
"
```

如果新建的 `pending` 长时间不前进 → Celery 没接到任务，检查 broker。
如果大量 `failed` → 看 `error_message` 字段：
```sql
SELECT id, error_message FROM interview_records WHERE status='failed' ORDER BY created_at DESC LIMIT 5;
```

---

## 10. 回滚

**不支持自动 downgrade**（0008 是数据迁移）。如果必须回退：

1. 停 API + Celery
2. 从 step 1 的 `pg_dump` 文件**完整恢复 DB**：
   ```bash
   dropdb interview_copilot
   createdb interview_copilot
   psql interview_copilot < backups/interview_copilot_pre_0008_XXXXX.sql
   ```
3. `git checkout` 到旧代码 commit
4. 重启服务

---

## 11. 30 天后

确认线上稳定运行 30 天后，删除 legacy backup 文件以释放磁盘：

```bash
rm backups/legacy_tables_pre_drop_*.sql
# 主备份保留更久或转冷存储
```

---

## 附：本次新增的可观察字段

| 字段 | 含义 |
|------|------|
| `interview_records.status` | pending / transcribing / extracting / analyzing / completed / failed |
| `interview_records.celery_task_id` | 对应 Celery 任务 id，可用 `celery_app.control.revoke()` 取消 |
| `interview_records.analyzed_qa_count` | 已分析的 QA 数，SSE 用 |
| `interview_records.error_message` | 失败原因 |
| `interview_records.completed_at` | 完成时间戳 |
| `interview_qa.grounding_refs_json` | 该题挂载的 ref_id 列表（如 `["exp_1.h1","req_2"]` 或 `["fundamentals:gc"]`） |
| `interview_qa.is_follow_up` / `follow_up_depth` | 标记追问题及追问深度 |
| `mock_interview_sessions.qa_buffer_json` | mock 答题缓冲，finish 时变成 InterviewQA 行 |
| `chat_sessions.archived_at` | 软删时间戳，列表查询自动过滤 |
