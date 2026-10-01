# 证据与复现说明

本目录记录 2026-09-23 审计结果。探针是故障复现，不是修复；通过代表当前错误行为仍存在。不要直接把它们并入“正确性回归”后宣称通过，应先反转到期望的业务不变量再修复。

## 六个探针

| 测试 | 对应发现 | 注入与证明边界 |
|---|---|---|
| test_refresh_token_can_be_consumed_twice | F05 | 两个协程通过屏障同时完成未撤销读取；直接调用去装饰端点，非真实 HTTP 压测 |
| test_sse_redis_failure_bypasses_db_recovery | F04 | Redis read 抛 ConnectionError，确认未调用数据库终态恢复 |
| test_revoke_returns_success_after_write_failure | F06 | 模拟 Redis 写失败，撤销调用仍正常返回 |
| test_async_client_cache_returns_same_object_to_distinct_loops | F02 | 模拟客户端，两个不同 loop 得到同一对象；不证明真实网络已报错 |
| test_unstarted_pending_turn_is_failed_after_queue_delay | F03 | 隔离 SQLite，创建61秒前未启动 Turn，再执行清扫 |
| test_expired_outbox_owner_overwrites_new_owner_success | F07 | 隔离 SQLite、受控时间和两个 Session，复现旧 owner 覆盖成功；不含外部副作用 |

## 安全复现命令

在项目根目录使用 PowerShell 7。下面只注入测试值；不要把 DATABASE_URL 换成业务数据库。审计探针自行创建隔离测试表/内存数据库，无需真实 LLM 服务。

```powershell
$env:PYTHONIOENCODING = 'utf-8'
$env:DATABASE_URL = 'sqlite://'
$env:SECRET_KEY = 'test-secret-key-not-for-production-32-bytes'
$env:DEEPSEEK_API_KEY = 'test-key-not-real'
$env:TEST_PG_ADMIN_URL = 'postgresql://postgres:postgres@127.0.0.1:1/postgres'
& 'D:/WorkSoftware/anaconda3/envs/Interview_Copilot/python.exe' -m pytest docs/reports/handbook-audit-2026-09-23/evidence/test_audit_probes.py -q -p no:cacheprovider --basetemp=data/runtime/audit-probe-repro
```

广泛后端运行使用 `backend/tests -m 'not integration and not slow'`；在标准入口发现收集错误后，额外使用 `--ignore=backend/tests/test_prompts.py` 继续审计，这不是建议永久忽略。临时目录权限错误通过 `--basetemp` 工作区目录重跑对应56项解决。两个场景失败仍然保留在日志中。

真实数据库运行使用临时 `interview-copilot-postgres:15.18-pgvector0.8.6` 容器、127.0.0.1:55439、无业务卷和仅用于临时容器的测试口令，执行 `backend/tests/test_db backend/tests/test_rag/test_pgvector_hybrid.py`。测试结束已停止容器，`--rm` 自动移除；本报告不建议复用生产服务运行这些测试。

## 可追溯性

- source-manifest.json：手册固定版本的路径、SHA、原文链接与标题元数据。
- workspace-file-hashes.json：920 个非秘密源码/契约文件的 SHA-256，补充有未提交更改的 HEAD 基线；不包含 .env 私密内容。
- code-inventory.json：AST 结构扫描，不等于所有记录都是缺陷。
- interview-question-index.json：3,360 个编号条目的来源行链接、主题与候选证据；不复制整份面经正文，不宣称逐条候选关系均经人工验证。
- verify_artifacts.py：检查报告内部文件链接、统计覆盖并刷新文件指纹，写入时明确 UTF-8。

日志反映本地环境。发布仍需在锁定依赖的干净镜像中运行全部必需检查。前端57文件183测试、PostgreSQL25测试和后端1557个通过结果存在不同范围或交集，不应相加制造总测试数量。
