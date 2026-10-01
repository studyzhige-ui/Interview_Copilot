# 发布修复验证结果（2026-09-23）

**发布状态：BLOCKED。** 工程回归通过，RAG 质量与若干产品级验收尚未完成。完整根因、改动、迁移及限制见 [实施账本](../../implementation/release-hardening-20260923.md)。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 后端完整回归 | 1596 passed，0 skipped，5 warnings，117.35 秒 | [测试末尾日志](backend-tests.txt) |
| 前端测试 | 60 文件、192 passed | [检查摘要](frontend-checks.txt) |
| 前端类型 / Lint / 生产构建 | 通过 | [检查摘要](frontend-checks.txt) |
| Python Ruff | backend、alembic、evaluation、scripts 通过 | 最终运行命令见下 |
| 数据库真实迁移 | fresh head 与 0051 降级/重新升级、派生向量表存在时无 schema drift | 完整后端中 test_release_schema_has_no_drift_with_a_derived_vector_generation |
| PostgreSQL 并发刷新 | 8 线程一次成功 | 完整后端中 test_postgres_refresh_has_one_winner |
| 真实 HTTP | 登录、越权拒绝、4 路刷新一次成功、登出撤销；100 请求/并发 20 | [HTTP 结果](http-smoke.json) |
| 真实备份恢复 | 80 表行数一致，3 对象逐字节一致 | [恢复结果](restore-drill.json) |
| SQL 规模诊断 | 10k/100k 行 BM25 热查询，租户隔离通过 | [规模与 EXPLAIN](lexical-scale.json) |
| RAG 真实校准 | 133 样本；无合格阈值组合，release_ready=false | [版本与指标摘要](rag-calibration-summary.json) |

后端测试在 Python 3.13 锁定依赖容器、PostgreSQL 15.18 + pgvector 0.8.6、Redis 8.10.0 下执行。5 条警告包含上游 langsmith 弃用、jieba 转义语法和测试事务夹具警告，测试未跳过。

最后的完整后端命令是：`pytest backend/tests -q`。Ruff 对 backend、alembic、evaluation、scripts 执行 check 和 format --check。前端依次执行 `npm run test:run`、`npm run typecheck`、`npm run lint`、`npm run build`，每步检查退出码。

证据边界：HTTP 是真实 Uvicorn + SQL/Redis，但不是完整浏览器旅程；恢复针对静止隔离语料、0051 schema，不是生产数据；规模测试是单独 BM25 热查询而非 ANN 召回率或模型吞吐；RAG 使用本机 CUDA 环境，其依赖版本单独记载，校准不通过时未执行正式保留集。迁移验证已包含最终 0052。

本目录仅保存脱敏结果。可复现的回归测试位于 backend/tests/test_release_invariants.py、backend/tests/test_db/test_release_concurrency.py 及相应服务/API/前端测试；临时容量与恢复实验原始材料保留在忽略的 data/runtime/ 中。
