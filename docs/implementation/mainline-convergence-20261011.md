# 项目主线收敛（2026-10-11）

本轮以功能归属和运行路径一致为目标，不以代码行数衡量清理。
当前工作目录采用 `codex/mainline-convergence`，从已完成 BGE 与规范检索投影改造的
`codex/integrate-local-work-20261001` / `c980b22` 建立。

## 根因与恢复点

先前在原目录整理的是旧架构，而较新的运行架构和 RAG 成果保存在另一个工作树。
只继续修改原目录，会重复整理已经被新架构替代的所有者，并遗漏已经完成的功能。

- 第一轮清理完整保留在 `codex/cleanup-round1` / `8d6ef1f`，另有
  `codex/checkpoint-before-mainline-convergence-20261011` 标签。
- 集成基线有 `codex/checkpoint-integrated-base-20261011` 标签。
- 清理前全部非忽略文件检查点 `2c599a1` 与此前 `a364152` 的树内容完全一致。
  原检查点相对 `f9bf80a` 的 333 项改动均出现在
  [原迁入清单](local-work-integration-20261001.json) 中。
- 本地 `refactor/product-runtime-convergence`、本地 `origin/main` 引用都是集成基线的
  祖先，没有额外独有提交需要从这些引用迁入；本轮没有访问远端更新引用。
- `.env`、模型、下载语料和业务数据库保持原状，不属于 Git 代码检查点。

## 独有成果的处理

| 原目录成果 | 当前处理与归属 |
| --- | --- |
| 工具结果预算、可回读引用、上下文压缩与恢复 | 集成版本已经迁入；保持其共享上下文与规范 Turn 合同，不复制旧 service 实现。 |
| BGE、中文词法、HNSW | 使用集成版本的 BGE、规范 `retrieval_entries` 及按用户/代次维护的 HNSW；保留已支持的词法配置。旧 `rag_vec_*` 写入器和 Qwen 专用适配不迁回。 |
| 资料入库、删除、发布、重建、附件引用 | 保持规范文档事实、源快照、代次与可见性约束，共用现有应用所有者。旧 outbox 任务名、旧迁移链不恢复。 |
| Agent 工具批次执行 | 从集成版本当前函数抽取到 `conversation/tool_batch.py`，保留新版 dispatch generation、资源身份、策略预检、批次屏障、并发和恢复合同。 |
| Agent 恢复状态读取 | 从集成版本抽取到 `conversation/agent_turn_state.py`；5 个函数的语法树与迁移前完全一致。 |
| 回合状态与执行监督分离 | `conversation/application/turn_store.py` 承接状态、租约、队列交接；`turn_executor.py` 保留异步执行、取消、心跳和完成事件。移动的 26 个定义与集成基线语法树一致。 |
| 集成版本已有 FIFO 入队 | 保持 `turn_admission.py` 为唯一锁内领取实现，删除 executor 的旧转导出，调用者直接导入所有者。 |
| 无用兼容代码 | 删除空 `mark_consumed`、未用工具配对包装与历史重建包装；dispatcher 明确实现 `plan_call`/`policy_traits`，Engine 明确提供 outcome，不用诊断事件猜测结果。 |
| 第一轮测试修复 | 迁入批次测试与取消回归，诊断事件测试覆盖 blocked/completed。集成版本已具备的 `source_turn_id` 和测试隔离不重复覆盖，也不恢复旧租约参数合同。 |
| 已发布的前端、认证、自动化、邀请与使用量成果 | 保留集成版本所有者及已有功能，通过完整回归核验；不逐文件粘回旧代码。 |
| 历史评测与资料 | 保留报告及基准评测用途；修正当前文档中 Milvus、失效 Qwen 命令、旧矩阵数量等指引。离线排名基准不作为生产 RAG 替代路径。 |

[本轮可复核审计](mainline-convergence-audit-20261011.json) 记录检查点、333 项覆盖及
语法树一致的定义。覆盖清单证明没有未登记路径；功能是否正确仍以实际回归为依据。

## 唯一生产主线

资料命令 → 共享入库流程 → 规范文档/分块 → `hybrid_index` 写入 `retrieval_entries`。
Chat、Agent、诊断接口和产品评测 → `rag_service` → 同一个 retrieval pipeline →
BGE dense + BM25 → RRF → BGE 重排 → 证据筛选 → 原文补全与引用。

精确检索/HNSW 是同一投影的物理策略；本地/远程模型提供者、文档格式解析器是同一合同下的
适配器。它们不是历史实现的旁路。生产路径不导入离线评测或运维迁移模块。
架构回归禁止旧 service 包、旧 RAG 存储和 Qwen 专用适配重新成为运行所有者，
并约束异步回合监督与数据库状态处理的依赖方向。

MTRAG 官方片段对照保留独立于产品分块和证据门的基准语义，否则旧 qrel 和指标不再成立。
它只用于离线排名研究；产品验收使用 `evaluation.rag_release` / `compare_local_models`
调用生产服务，不把基准分数冒充生产链路验证。

## 验证与限制

测试使用一次性 Linux 容器、PostgreSQL/pgvector 与 Redis；代码快照只包含非忽略源码，
不包含业务 `.env`、模型、语料或数据库。

- 最终完整后端：**2415 passed、5 skipped、0 failed**，约 548 秒。按 CI 后端命令排除
  9 项独立浏览器测试；含真实 PostgreSQL 迁移、HNSW 算子与隔离、Celery 中断恢复、
  音频解码、取消、邀请决策恢复和使用量合同。
- 首轮完整回归的 3 项失败均为迁入测试适配：取消测试缺有效用户 ID，邀请恢复测试
  将模型客户端补丁错误地打到状态读取模块。修正后的定向回归 **47 passed**，上述完整
  复测也全部通过。首轮收集时 FFmpeg 尚未准备好的 13 项测试已在最终复测中通过。
- `jieba_search` 下真实 PostgreSQL 与词法合同：**12 passed**。
- MTRAG 离线回归：**21 passed**。
- 前端：**93 个文件、381 项测试通过**；类型检查、Lint、生产构建通过。
- 空隔离库 `alembic upgrade head`、`alembic check` 通过；共享协议快照检查通过。
- Ruff 0.16.2 全范围 Lint、921 个 Python 文件格式检查、编译和 Git 差异检查通过。

5 项跳过分别为下载语料、真实本地 embedding/reranker、可选 aiortc/WebRTC、2 项真实
S3 HTTP 测试；没有将它们计作已验收。具体环境、源码身份与 HNSW 测试属性见
[验证记录](mainline-convergence-validation-20261011.json)。

自动审批拦截了旧 `services` 目录字节码缓存的递归删除，未给出具体原因，因此保留这些
忽略文件。它们没有源码，不进入 Git 或干净测试快照；架构检查检查实际源码所有者，
避免把残留缓存目录误判为另一套实现。

本轮不迁移业务数据库、不启动业务服务、不调用付费模型、不发布远端。
旧本地数据库若使用自定义迁移链，仍须核对真实 revision 和资料后单独迁移，不能直接 stamp。
真实 GPU 检索质量、浏览器端到端、真实 Supabase 登录及外部服务效果不由离线测试代替。
集成基线已有的 TTS 默认 disabled、实时本地合成不可用等边界保持原状，
没有因代码收敛而声称补齐这些能力。
