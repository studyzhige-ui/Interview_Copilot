# Interview Copilot 核心系统审查报告

日期：2026-07-27
分支：`main`

## 结论

本轮审查覆盖了 RAG、模拟面试、会话与 Agent、记忆、简历、异步任务、
模型边界、提示词和部署拓扑。项目已从“功能基本可用”收口为结构清晰、失败
状态可见、具备 Community 发布与 Cloud 受控 Beta 的工程版本。

这里的“可以继续做 Beta”不等于“已经证明回答质量达到商业上线标准”：

- 代码正确性和状态一致性已有完整自动化回归；
- RAG 已用真实语料跑出 835 条检索基线；
- 模拟面试已建立自动质量门禁，但更广岗位覆盖仍需要人工标注；
- Cloud 已具备技术侧健康探针、用户级限流、备份恢复、故障演练和成本观测
  边界；公网发布仍需要经营者确定隐私条款、预算与 SLA。

## 1. 架构边界

当前边界为“一套核心、两个发行策略”：

| 能力 | Cloud | Community |
|---|---|---|
| 用户回答模型、个人 Key | 用户选择 | 用户选择 |
| Chat、Agent、模拟面试回答 | 共用同一个用户回答模型 | 共用同一个用户回答模型 |
| Router、Worker 模型 | 平台提供 | 部署者提供 |
| 当前内部模型 | `deepseek/deepseek-v4-flash` | 默认相同，可由部署者改 |
| Embedding、Reranker、ASR、说话人分离 | 平台负责 | 部署者可选本地或远程 |
| Skill、远程 MCP | 用户配置 | 用户配置 |
| stdio MCP | 禁止 | 部署者显式启用 |

用户模型表中已废弃的 `agent`、`mock_interview` 等选择由迁移
`0050_single_answer_model` 清理。内部模型不读取用户选择、用户 Endpoint 或
用户密钥。

## 2. RAG

### 已修复

- 知识文档先提交数据库再派发任务，避免 Worker 抢先读取不到记录；
- 派发失败进入明确的 `failed` 终态，不再留下永久 `processing`；
- 只有 `ready` 文档中的 `indexed` chunk 才能被 hydrate；
- 多查询并发检索允许局部失败，保留其他子查询的有效候选；
- Milvus 命中后以 PostgreSQL 事实表重新校验文本、文档状态和归属；
- 保存面试优质回答时，文档状态遵循 `processing → ready/failed`；
- 删除知识文档时，数据库删除、Milvus 清理和对象存储清理通过事务 Outbox
  协调，不再出现半删除状态；
- 评测 Runner 已适配当前 `dense_query/sparse_query/source_kind` 接口、
  `RetrievalResult` 返回类型及稳定用户主键；
- 评测会在用户或语料未准备时直接失败，而不是输出误导性的全零指标。

### 当前成熟度

检索代码路径、租户过滤、阈值分支、Reranker 降级、引用来源和生命周期已经
具备较强工程完整性。通过 `evaluation.prepare_corpus` 使用生产链路导入 5 份
真实 PDF，共 902 个 chunk；完整执行 835 条检索问题后：

- Hit@3 / Recall@3 `0.9461`，Precision@3 `0.7549`；
- MRR@5 `0.9293`，nDCG@5 `0.9399`；
- 平均延迟 `478.43 ms`，P95 `512.36 ms`；
- 租户隔离违规 `0`，现有阈值全部通过。

## 3. 模拟面试与复盘

### 已修复

- 阶段状态机只允许停留在当前阶段或前进一个阶段，拒绝回退和跳阶段；
- `ready_to_finish` 只接受真正的 JSON 布尔值，字符串 `"false"` 不再被误判；
- 用户回答长度设置明确上限；
- 模拟面试复盘从语音转写队列拆出，进入轻量控制队列；
- 上传面试分析与模拟面试复盘共享统一分析编排，但各自保留正确的入口状态；
- 处理超时的记录由周期任务收口为可见失败状态；
- API 不再把内部异常和供应商错误原文直接返回给用户。

### 当前成熟度

流程状态、持久化、失败收口和结构化输出已经成熟。新增 8 类固定自动评测场景，
覆盖自我介绍衔接、项目追问、信息不足、候选人提问、结束语、提示词注入、压力
面尊重和避免重复。最终结果为 8/8 通过、Judge 均值 `4.9/5`、安全与事实约束
通过率均为 `100%`。

内容质量下一步仍应扩展：

1. 不同岗位和难度的固定面试脚本集；
2. 专家对“追问相关性、覆盖度、难度递进、评分一致性”的人工标注；
3. 模型版本升级前后的成对回归；
4. 复盘建议与原始回答的事实一致性检查。

## 4. Worker 与长任务

Worker 现按负载隔离为四条队列：

| 队列 | 职责 | 默认并发模型 |
|---|---|---|
| `turns` | Chat / Agent 长 turn、Redis 事件流 | threads，2 |
| `transcription` | ASR、说话人分离、上传面试分析 | solo |
| `pipeline` | 文档解析、Embedding、简历解析、Outbox | solo |
| `default` | 模拟复盘、目录刷新、记忆、清理任务 | threads，4 |

核心改变是：Web API 不再直接运行 Chat/Agent。API 只持久化 turn、派发任务、
订阅 Redis Stream 和处理取消；独立 `turns` Worker 原子领取任务。派发失败会
立即把 turn 置为失败并释放会话，不会形成僵尸任务。

其他可靠性改造包括：

- Celery 使用 late ack、worker lost 重投、prefetch=1 和大于硬超时的 Redis
  visibility timeout；
- Worker 只加载当前队列需要的模型，控制 Worker 不加载 Whisper 或 Embedding；
- `turns` Worker 延迟初始化 Embedding 和 Reranker；
- Outbox 有领取锁、过期租约回收、尝试次数和最终失败；
- 文档、简历、索引、上传和面试记录均有 stale sweeper；
- 简历写入按用户行加锁，保证“最多两份、唯一默认”在并发请求下成立；
- 简历解析与 Milvus 重建通过 Outbox 串联，数据库状态不会提前标为 ready。

### “步骤正确”的真实含义

系统不能数学保证大模型的每个判断都正确。当前能保证的是：

- turn 工具视图不可变，执行期间配置变化不会污染它；
- Session Task 有依赖图、循环检测、验收条件、证据和 verifier 状态；
- 工具调用有参数、超时、取消、结果和审计；
- Agent 有步数、字符、工具参数和响应预算；
- Checkpoint 保存当前任务、摘要和下一步；
- Worker 丢失租约后不能提交终态；
- 外部失败进入显式失败状态，不会伪装成功。

进程在一个 turn 中途被强杀时，当前策略是把过期 turn 可靠地关闭为失败，并让
用户基于已保存的 Task/Checkpoint 在新 turn 继续；系统不会自动重放任意外部
副作用。要做到完全自动恢复，还需要为每一种有副作用的工具定义业务幂等键和
补偿协议，不能靠通用 Agent 循环安全猜测。

## 5. 会话、记忆和能力隔离

- assistant 回复与实时记忆提取任务在同一数据库事务中提交；
- 记忆提取失败由 Outbox 重试，不再依赖进程内 fire-and-forget；
- 降级或保存失败的 turn 不进入长期记忆；
- 删除了旧 `post_turn_maintenance.py` 和分散的旧 memory prompts；
- 用户 Skill/MCP 从不写入全局工具注册表；
- MCP Client 按 `(user_id, server_id)` 隔离；
- 会话保存发现结果和权限；
- turn 保存不可变能力快照、延迟 Schema 和预算；
- tool call 保存独立审计、超时与取消状态。

## 6. 提示词与模型职责

生产提示词集中在 `backend/app/prompts/`，按 Agent、Chat、规划、面试、记忆、
简历、任务和语音分析分组。调用处只负责提供结构化变量，不再维护重复的大段
规则文本。

模型职责为：

- 用户回答模型：Chat、Agent 最终回答、模拟面试互动和用户可见生成；
- `router`：查询规划；
- `worker`：摘要、结构化抽取、诊断、记忆合并和后台分析；
- `router` 与 `worker` 均固定走部署方 `deepseek-v4-flash` 配置。

## 7. 删除和收口

- 删除旧 turn 后处理协程和旧 memory prompt 模块；
- 清除多回答模型角色的前后端逻辑与数据库残留；
- 删除最佳努力式简历向量化路径，统一到 Outbox；
- 删除知识删除流程中的跨系统即时写入；
- 清理旧模型名称、过时环境示例和错误部署说明；
- 启动脚本、Docker Compose、英文/中文文档统一为四队列 Worker 拓扑。

## 8. 验证结果

- 后端：`1025 passed, 1 skipped`；
- Ruff：`backend/app`、`backend/tests`、`evaluation` 零错误；
- Alembic：单一 Head，新增消息级联迁移；
- 前端：TypeScript 通过、ESLint 零 warning；
- 前端测试：7 个文件、34 项通过；
- 前端生产构建：通过；
- Docker Compose：配置解析通过；
- Python compileall：通过；
- Cloud wheel 在全新 Python venv 中完成依赖安装与导入；
- 部署 API 冒烟覆盖健康、登录、资料、Edition、会话增删改查；
- 真实备份恢复到临时 PostgreSQL 后校验迁移版本及核心表计数；
- 8 路并发、Redis 断网恢复与 Worker 强杀租约回收全部通过。

## 9. 仍需人工或真实生产环境完成

以下事项无法由本地代码诚实替代：

1. 招聘/面试专家扩展模拟面试人工标注集；
2. 在目标云账号配置告警接收人、Provider 硬预算、备份保留期和跨区策略；
3. 法务/经营者确定隐私协议、数据保留期、导出/删除 SLA 和事件响应联系人；
4. 使用真实生产拓扑执行 PostgreSQL、Milvus 与对象存储区域级灾备；
5. 对新增的每一种外部副作用工具定义业务幂等键和补偿协议。

当前推荐定位仍是 Community 发布候选与 Cloud 受控 Beta；公开商业 SLA 必须
由真实部署数据和运营责任支撑。
