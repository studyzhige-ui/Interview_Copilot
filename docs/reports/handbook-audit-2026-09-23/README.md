# Interview Copilot 全面工程审查

审查日期：2026-09-23。结论：**这是具有较多产品功能和较强局部执行契约的工程原型/产品候选，尚不具备可放心发布的成熟多租户产品证据。** 主要阻碍不在于缺少更多 Agent 框架或数据库种类，而在于运行时所有权、故障状态机、原子安全操作、资源预算与发布验证尚未闭环。

本次只新增审计材料和复现探针，没有修改业务代码，也没有覆盖已有未提交更改。后续升级应先修复责任层，再整理架构；不宜先做全面目录重排或增加微服务。

## 阅读入口与范围

- [185 章逐章审查](#课程覆盖)：每章含原文知识点提纲、项目落点、判定和关联缺陷。
- [真人面经与项目追问](面经映射.md)：深度追问链，以及 S001–S295 的来源级覆盖索引。
- [升级路线与验收](升级路线与验收.md)：按依赖安排升级顺序。
- [代码证据索引](代码证据索引.md)、[测试证据](#实测结果)、[6 个复现探针](evidence/test_audit_probes.py)。

手册固定在 commit `e5e000c1dbc3546aaea7c2730b78db33f4c7ffb5`，已读取 234 份 Markdown：185 章课程、33 份面经批次及16份导航/规范化问库等材料。[来源清单](evidence/source-manifest.json)保存路径、SHA、链接和标题。面经解析得到 295 个来源与 3,360 个编号条目；条目包含自我介绍、HR、算法、同一流程多轮问题，**不是 3,360 道去重技术题**。真实性沿用手册 HUMAN-A 标记，本次未逐一重新验证原始外站帖子。规范化旧问库停在 S279，因此额外纳入 S280–S295，未把 S288 的后续轮次重复算成新来源。

项目基线 HEAD：`f9bf80ae70e13b235da487ba7ca224a7b85bdfeb`，受审对象还包含当前未提交的 pgvector、memory 等更改。因此该 SHA 单独不足以重建本次工作区。审查方式是课程全覆盖映射、关键真实数据流阅读、结构扫描、测试与故障探针；不是对 93,706 行代码逐行形式化证明，也不是已完成生产压测或渗透测试。

## 成熟度判断

| 维度 | 判断 | 核心依据 |
|---|---|---|
| 业务建模与持久事实 | 基础较强 | Turn、工具执行账本、checkpoint、memory、索引代际有明确模型 |
| Python/FastAPI 运行时 | 尚不合格 | 同步 DB 进入 async 路径，多 loop 共享 async client |
| 数据库与一致性 | 局部成熟，恢复缺口明显 | 行锁、CAS、outbox 已有；租约终结缺 fencing |
| Redis 与流式体验 | 正常路径可用，故障未闭合 | 断连绕过 DB 恢复；连接池及共故障预算缺失 |
| 身份与会话安全 | 发布阻断 | refresh 非原子；撤销失败仍成功返回 |
| RAG | 实现有基础，质量未获当前证据 | pgvector 实测通过；旧发布报告不通过且不适用 |
| Agent harness | 强于简单 Agent demo，仍未生产成熟 | 确定性门禁与账本存在；预算、租约、恢复边界不完整 |
| 干净代码与发布治理 | 尚不合格 | 大型协调函数、收集错误、场景漂移、CI 依赖契约冲突 |
| 运维与规模 | 未证明 | 缺本次负载、恢复、成本、SLO 验收数据 |

“成熟”应由目标负载和用户旅程验收，而不是引入 Kafka/K8s/多 Agent/GraphRAG 的数量判断。项目选择 PostgreSQL 合理；MySQL 章节用于理解事务、索引和优化方法，不能把 InnoDB 的聚簇索引、undo/binlog/两阶段提交细节直接套到 PostgreSQL。

## 应保留的设计

1. **持久 Turn 与工具执行事实。** 请求接纳、执行与 SSE 传输分离，工具有 schema、preflight、策略决策、参数脱敏/摘要、审批与审计。存在 generation 防护及迟到/未知结果处理，不是单纯把 prompt 当权限系统。
2. **谨慎的工具并行。** 读操作按资源键分组并行，写入/未知操作保持保守；完成顺序与模型消息顺序分别处理，取消时有回收逻辑。
3. **上下文和记忆的生命周期。** checkpoint 锁与版本 CAS、deepcopy 隔离、两阶段记忆提取/整合、来源、人工修订、保留期均已有实现。应围绕其不变量补证据，避免另起一套 memory。
4. **检索的一致性意识。** 参数化 SQL、租户候选过滤、向量维度检查、代际发布/回填、事务和 advisory lock 已有；pgvector 数据库实测通过。替换向量引擎不应丢掉这些约束。
5. **评测与安全框架已存在。** release runtime contract、代码指纹、检索门槛、planner snapshot、Ragas、SSRF、云/社区能力边界都有基础。问题在于当前有效证据和少数关键责任层缺口。

## 实测结果

| 检查 | 本次结果 | 解释 |
|---|---|---|
| 后端标准非 integration/slow 测试入口 | 收集阶段 1 个 ImportError | [日志](evidence/backend-tests.txt)，不能视为全绿 |
| 排除失效 prompt 测试后的广泛运行 | 1501 passed / 2 failed / 17 skipped / 56 errors | [日志](evidence/backend-tests-isolated.txt)；56 errors 均是测试临时目录权限 |
| 将上述 56 项改用工作区临时目录重跑 | 56 passed | [日志](evidence/backend-tests-temp-rerun.txt)，消除环境误报；合计相关不同测试 1557 passed、2 真失败、17 skipped，但不是标准入口一次全绿 |
| 隔离 PostgreSQL + pgvector | 25 passed | [日志](evidence/postgres-tests.txt)，临时容器无业务卷，已停止并自动删除；不要与前述可能重合的测试直接累加 |
| 前端 | 57 文件 / 183 测试通过 | [日志](evidence/frontend-tests.txt)；[typecheck](evidence/frontend-typecheck.txt)、[lint](evidence/frontend-lint.txt)通过 |
| Ruff | 1 个 F401；16 个文件格式不符 | [lint](evidence/ruff.txt)、[format](evidence/ruff-format.txt) |
| 审计故障探针 | 6 passed | [日志](evidence/audit-probes.txt)；它们断言当前错误行为，因此通过代表缺陷复现成功，不代表修复 |

后端使用现有 Python 3.11 环境，FastAPI 0.135.2、Redis 5.2.1、SQLAlchemy 2.0.48、Celery 5.6.3；与项目锁定的 FastAPI 0.141.1、Redis 8.1.0、SQLAlchemy 2.0.51 有差异。只读核对本地 backend 镜像可见其使用后者版本，但没有在该镜像补装测试依赖并重跑完整套件。因此这些通过结果**不替代锁定环境发布验收**。Celery thread pool 的行为另外核对了相同版本 5.6.3 的实现。

两个真实场景失败引用了已不存在的 `frontend/src/pages/interviews/ManualInvitationForm.test.tsx` 和 `frontend/src/pages/settings/ConnectionsPage.test.tsx`。是否应迁移场景还是补回测试，应由当前用户旅程决定，不能为全绿简单删除覆盖要求。

## 具体发现

优先级：P0 为发布前必须解决；P1 为生产可靠性/安全重要缺口；P2 为规模、维护和可验证性改进。优先级是本次产品审计判断，不是 CVSS。带条件的风险只有在相应产品能力开放时成立。

### F01 · P1 · 异步入口执行同步数据库操作，连接生命周期没有按流式请求拆分

**证据强度：** 代码确认；并发退化幅度未测。

**代码定位：** backend/app/api/chat/streaming.py:473；backend/app/core/security.py；backend/app/db/database.py:27；backend/app/services/chat/turn_executor.py:1617。链接见[代码索引](代码证据索引.md)。

**根因：** async 路由/依赖/清扫协程直接调用同步 psycopg2 Session。get_db 的 yield 管理并不能把协程内部 SQL 自动移到线程池。SSE 路由还依赖请求级 Session，当前依赖清理语义下可能把认证查询后的事务和连接留到流结束。

**影响与边界：** 事件循环被 SQL 等待阻塞；慢流占用连接会放大排队。AST 扫描找到 60 个含直接 db/session 调用的 async 定义，只是筛查集合，不等于 60 个独立故障。

**责任层修复：** 统一 I/O 契约：选用 AsyncSession，或把完整同步事务单元放入受限线程执行器；不得跨线程共享 Session。SSE 握手阶段取不可变授权数据后关闭事务，事件循环不持有请求 DB 会话。

**验收：** 并发长 SSE + 慢 SQL 下记录 loop lag、pool checkout 等待、连接持有时长；用数据库活动视图确认没有随流持续的 idle-in-transaction。

### F02 · P1 · Celery 多线程中的多个事件循环共享进程级异步客户端

**证据强度：** 对象共享已复现；真实网络跨 loop 异常未复现。

**代码定位：** backend/app/core/async_runtime.py:6；backend/app/core/llm_client_factory.py；backend/app/db/redis.py；docker-compose.yml。链接见[代码索引](代码证据索引.md)。

**根因：** run_async 为每个线程建立 loop；Redis 异步连接池和原生 LLM 客户端缓存却以进程为生命周期。缓存互斥锁只保护字典访问，不赋予连接跨 loop 安全性。Compose 使用 threads worker，使这个组合实际可达。

**影响与边界：** 两个独立 loop 获得同一个缓存客户端的探针通过；连接一旦绑定 loop，跨线程使用存在异常与清理问题。不能用单线程单测或加缓存锁证明安全。

**责任层修复：** 每个 loop 独占创建/使用/关闭异步资源，或采用一个专属异步执行 loop；另一选择是进程 worker 内统一运行时。将运行时所有权做成显式依赖。

**验收：** 固定部署池类型，多线程同时跑真实本地 HTTP/Redis 请求、取消与 worker 退出；验证 loop/client 归属、无跨 loop 异常和连接泄漏。

### F03 · P1 · 尚未执行的 Turn 在排队超过 60 秒后被当成失联任务失败

**证据强度：** 已复现。

**代码定位：** backend/app/services/chat/turn_executor.py:1617；TURN_STALE_SECONDS 默认 60。链接见[代码索引](代码证据索引.md)。

**根因：** 失联清扫对 pending 使用 created_at 截止时间，对 running 使用 heartbeat。它把“已接纳但等 Celery 执行”与“执行者失联”合成同一失效时钟。

**影响与边界：** 探针创建 61 秒前、started_at 为空的 pending Turn，清扫后变成 failed。这里不是同会话的 pending submission 列表，而是已创建待执行的 Turn。拥塞会制造用户可见失败。

**责任层修复：** 分开 admission/dispatch/queued/running 状态与时钟，定义接纳预算、调度 lease、排队期限和运行心跳；清扫必须基于状态对应的不变量。

**验收：** 暂停消费者超过 60 秒后恢复：有效排队任务按策略完成或得到明确排队超时，不得报告执行者失联；同时验证真正失联运行者可回收。

### F04 · P1 · SSE 的 Redis 异常直接绕过数据库终态恢复

**证据强度：** 已复现；截断/过期恢复协议为代码风险。

**代码定位：** backend/app/api/chat/streaming.py:848；backend/app/services/chat/turn_event_buffer.py。链接见[代码索引](代码证据索引.md)。

**根因：** 事件生成器先 await Redis read，只有正常返回空批次后才查询数据库终态。ConnectionError 从读取直接逸出，使后面的恢复分支不可达。

**影响与边界：** 探针注入 Redis 断连，数据库恢复函数未被调用。Stream TTL、长度截断和 reset 还需要 generation/cursor gap 语义，否则客户端不能区分“没有新事件”和“历史已丢失”。

**责任层修复：** 把事件输送失败与 Turn 执行状态分层；定义数据库快照恢复、终态重放、generation 与 cursor gap 协议，并设置有界退避和重连预算。

**验收：** 断连/恢复、过期、截断、重置、慢消费者、页面刷新逐项测试；用户最终看到唯一正确终态，不能永远转圈或误认为回复为空。

### F05 · P0 · Refresh Token 轮换是 check-then-set，允许同一令牌并发消费

**证据强度：** 已复现。

**代码定位：** backend/app/api/auth.py:292；backend/app/core/token_blacklist.py:45。链接见[代码索引](代码证据索引.md)。

**根因：** is_revoked 与 revoke 分离，两个请求可同时看到未撤销；写入没有原子消费条件。函数注释中的“竞争者会失败”不由实现保证。

**影响与边界：** 同步屏障探针使同一 jti 两次刷新均生成令牌。轮换单次使用契约已被违反。

**责任层修复：** 用持久会话记录 CAS/事务实现消费与后继令牌关系；若用 Redis，至少原子 SET NX/Lua，并解决宕机持久性、token family 重放与失败语义。

**验收：** 同一 refresh token 并发 N 次恰好一次成功；其余拒绝。注入消费成功但响应丢失，明确可恢复策略，不得重新放行旧令牌。

### F06 · P0 · 撤销写入失败被吞掉，接口仍可声称退出成功

**证据强度：** 已复现。

**代码定位：** backend/app/core/token_blacklist.py:45；backend/app/api/auth.py:359。链接见[代码索引](代码证据索引.md)。

**根因：** 撤销遇到 Redis 异常仅记录日志并返回；鉴权 fail-closed 只覆盖 Redis 正在故障的时段，恢复后未写入的旧 token 仍可能有效。

**影响与边界：** 探针让 SET 失败，revoke 正常返回。当前代码有接受该风险的注释，但它不满足强制会话撤销的产品承诺；有效窗口由原 token 的 exp 决定。

**责任层修复：** 采用可持久化会话版本/撤销事实，或者明确失败响应与补偿；不要把“当前无法鉴权”当成“永久撤销成功”。

**验收：** 退出时存储故障，再恢复：原 access/refresh token 不能重新生效；账户级强制退出、密码重置也走同一契约。

### F07 · P1 · Outbox lease 过期后，旧执行者仍可覆盖新执行者结果

**证据强度：** 已复现；外部副作用重复尚未实测。

**代码定位：** backend/app/services/outbox.py:205；backend/app/task_queue/celery_app.py；docker-compose.yml。链接见[代码索引](代码证据索引.md)。

**根因：** claim 使用行锁并提交，执行结束却没有以 lease generation/owner 作条件更新。固定 20 分钟 lease 依赖任务时限假设；线程池不能被配置中的 hard time limit 可靠强杀。批次串行还会消耗后续任务的 lease。

**影响与边界：** 探针让第二执行者在 21 分钟后接管并成功，再让第一执行者失败；最终 succeeded 被写成 failed。SQLite 控制交错已证明状态覆盖；尚非真实 PostgreSQL 并发副作用实验。

**责任层修复：** 引入单调 fencing token，续租和终结均 CAS；逐项领取或为批次续租。外部动作采用供应商幂等键及 reconciliation，将未知结果保留为 unknown，禁止盲目重试。

**验收：** 旧 owner 无权写终态；跨租约重启故障测试覆盖成功、失败、超时和响应丢失；验证外部动作至多一次或可检测重复且可对账。

### F08 · P1 · Agent 的总资源限制目前主要是观测数据

**证据强度：** 代码确认；资源耗尽未压测。

**代码定位：** backend/app/agent_runtime/react_agent.py；backend/app/conversation/agent_strategy.py；backend/app/task_queue/celery_app.py。链接见[代码索引](代码证据索引.md)。

**根因：** 步数/token/时间不是强制停止条件，局部重复检测可被不断变化的调用绕过。线程/solo worker 的时限设置又不能替代可终止执行边界。

**影响与边界：** 用户或模型可持续占用算力、模型额度和队列；局部工具超时不构成租户总预算。已有自主执行语义应保留，但必须明确谁为资源付费、何时挂起。

**责任层修复：** 建立用户可理解的任务预算、租户配额、模型费用账本、并发接纳和可续跑 checkpoint；到预算时挂起/请求扩额，保持正确的未知副作用状态。

**验收：** 构造无限变化但合法的工具序列，验证在批准预算内暂停并可恢复；取消后不能继续产生未经授权的新副作用。

### F09 · P1 · 连接池、长连接与 worker 并发缺少统一容量模型

**证据强度：** 配置确认；上限不是实测负载。

**代码定位：** docker-compose.yml；backend/app/db/database.py；backend/app/db/redis.py。链接见[代码索引](代码证据索引.md)。

**根因：** DB pool 20+overflow20 是每进程；2 API 加多类 worker 至少 6 个可能访问数据库的进程，理论峰值至少 240，池按需创建，不能说已经用了 240。Redis 异步池、同步池、Celery 和限流连接并非一个共享预算。

**影响与边界：** SSE XREAD 和取消 BLPOP 会长期占用 Redis 连接，与其他功能争用；broker、撤销、缓存和事件共用故障域。Compose 没给出完整的 maxmemory/eviction 与降级容量论证。

**责任层修复：** 根据实际进程数、每类任务和长连接分配预算，区分控制面/事件/缓存；设置接纳上限及慢客户端策略，用内存字节预算补充 stream 条数限制。

**验收：** 阶梯与突发负载记录 SQL/Redis 实际连接、队列年龄、拒绝率、RSS 和完成率；服务过载时明确拒绝，不把超载转为随机认证/任务失败。

### F10 · P1 · CI 的 PostgreSQL 镜像与 pgvector 测试契约不一致

**证据强度：** 配置/测试代码确认；本次未执行远端 CI。

**代码定位：**  .github/workflows/ci.yml；alembic/versions/0047_pgvector_extension.py；backend/tests/test_rag/test_pgvector_hybrid.py。链接见[代码索引](代码证据索引.md)。

**根因：** CI 使用普通 postgres:15.18-alpine，测试要求 vector 扩展。迁移对扩展不可用可跳过，因此不能笼统说 migrate 一定失败；后续扩展安装/向量测试才是明确冲突点。

**影响与边界：** 本次改用项目 pgvector 镜像，25 项真实 PostgreSQL 测试通过。这证明实现有基础，也说明不能以普通 PostgreSQL 的迁移成功代替向量能力验证。

**责任层修复：** CI 统一到受控 pgvector 镜像与锁定依赖，基础设施不可达应在必需测试中 fail 而非 skip。

**验收：** 干净环境完成 migration upgrade、数据库契约和向量检索测试；日志包含 PostgreSQL/vector 版本。

### F11 · P0 · 当前测试入口不能全绿，场景清单和源码已经漂移

**证据强度：** 已实测。

**代码定位：** backend/tests/test_prompts.py:8；evaluation/career_agent_os_scenarios.json；evaluation/career_scenarios.json；backend/app/models/__init__.py:26。链接见[代码索引](代码证据索引.md)。

**根因：** prompt 重构后测试仍导入 CONVERSATION_COMPACTION_PROMPT，pytest 收集即中止；两个场景门禁引用不存在的前端测试文件。Ruff 还有 1 个 F401，16 个文件未满足格式检查。

**影响与边界：** 普通发布入口已阻断。不能用大量通过的单测掩盖收集错误；也不能仅删除失效场景条目，把缺失验证当作修复。

**责任层修复：** 对齐新的 prompt 合约；确认场景迁移到哪个用户流程后恢复有效覆盖；修复 lint/format，锁定运行环境，建立不可跳过的完整门禁。

**验收：** 标准入口一次性全绿，必需场景有真实执行证据；新的审计复现测试改成期望正确行为的回归测试后通过。

### F12 · P1 · 现有 RAG 发布报告不能证明当前 pgvector 版本达到质量门槛

**证据强度：** 已有报告不通过；当前质量未知。

**代码定位：** evaluation/rag_release.py；evaluation/retrieval_gates.py；data/evaluation/release/cuda.json。链接见[代码索引](代码证据索引.md)。

**根因：** 旧报告虽 completed，却 release_ready=false，使用 Milvus 运行契约及旧阈值；当前已切换 pgvector 与新默认阈值。评测框架存在指纹和运行契约控制，不能绕过。

**影响与边界：** 不能据此宣称召回率、正确率或成熟 RAG。测试检索 SQL 正确不代表真实问答好用，本次未调用付费模型生成新质量结果。

**责任层修复：** 以当前文档代际、embedding/reranker、阈值和代码指纹重跑离线 holdout；分开召回、重排、引用、拒答、最终任务采纳率，并加入租户隔离与对抗样本。

**验收：** 新报告 release_ready=true，保留失败样本和分桶指标；校准集与验收集分离，并展示质量/时延/成本取舍。

### F13 · P2 · SQL BM25 的查询成本缺少规模证据

**证据强度：** 查询结构确认；性能风险未量化。

**代码定位：** backend/app/rag/pgvector_hybrid.py:293。链接见[代码索引](代码证据索引.md)。

**根因：** sparse_search 每次计算租户/过滤范围的语料统计、平均长度等，并关联词项文档频率。GIN 可加速词项匹配，但不能自动消除统计扫描。

**影响与边界：** 风险随租户语料规模增长，不是“每次扫描所有租户”。不能仅因用了 PostgreSQL/HNSW 就推断大规模低延迟。

**责任层修复：** 先以真实分布 EXPLAIN ANALYZE BUFFERS；再决定维护版本化统计、缓存统计或替换稀疏引擎，保持代际一致性。

**验收：** 记录多档语料量、冷热缓存、过滤选择性下 p50/p95 与执行计划；HNSW 对 exact search 测召回/延迟，避免优化损害隔离和质量。

### F14 · P2 · 异步资源创建与关闭没有完整的同一所有者

**证据强度：** 代码确认；长期泄漏量未测。

**代码定位：** backend/app/main.py；backend/app/core/llm_client_factory.py；backend/app/db/redis.py。链接见[代码索引](代码证据索引.md)。

**根因：** lifespan 有取消后台任务和 MCP close，但 Redis/DB/原生模型客户端及 worker 自建 loop 的收尾没有形成统一生命周期；无运行 loop 时关闭协程对象并不等于执行网络客户端 aclose。

**影响与边界：** 短命测试看不到连接、线程、loop 的累积；退出期间还可能留下未交付事件。

**责任层修复：** 把 RuntimeResources 作为显式生命周期根，按依赖反序停止接纳、排空/挂起、关闭客户端、连接池和 loop。

**验收：** 重复启动/停止、取消中断及长时间运行后比较 fd/socket/thread/连接数量，退出不丢失持久终态。

### F15 · P2 · canonical chunk 回填缺少调用者租户条件作为最终防线

**证据强度：** 防御缺口；未证实跨租户泄漏。

**代码定位：** backend/app/rag/chunk_hydration.py:44；backend/app/rag/retrieval/candidates.py。链接见[代码索引](代码证据索引.md)。

**根因：** 候选检索已有 user 过滤与范围检查，但 hydrate_chunks 按 node id、状态和 generation 回填，没有 principal 参数。

**影响与边界：** 正常链路的上游约束有效，不能把缺少重复检查直接写成已泄漏。风险在未来新调用者、损坏索引或绕过候选层时扩大。

**责任层修复：** 将 principal 传到 canonical 读取层并校验文档归属；tenant 条件是数据边界的一部分，不依赖调用者记住前置步骤。

**验收：** 恶意跨租户 node id、损坏 metadata、直接 hydrate 调用和删除中并发检索全部拒绝越权。

### F16 · P2 · 核心流程的事务、策略和恢复职责过度集中

**证据强度：** 结构扫描与关键路径审查确认。

**代码定位：** backend/app/conversation/agent_strategy.py；backend/app/agent_runtime/tool_call_executor.py；backend/app/services/chat/turn_executor.py。链接见[代码索引](代码证据索引.md)。

**根因：** 382 个 backend/app Python 文件约 93,706 行。关键文件约 1,450–1,950 行，_execute_tools 约 474 行。问题不单是长，而是同一执行路径同时承担状态、授权、I/O、恢复和投影。

**影响与边界：** 改动影响面和跨层事务所有权难解释，现有 prompt/scenario 漂移正是合约治理需要加强的证据；AST 未发现可变字面量默认参数是正面结果。

**责任层修复：** 保持模块化单体，按 use case、纯状态转移、Unit of Work、外部适配器拆分；为依赖方向加静态约束，沿真实失败路径重构。

**验收：** 每个业务不变量只有一个权威写入口；核心状态转移可脱离网络测试，原完整旅程和故障回归不退化。

### F17 · P2 · 观测能力存在，但尚无本次发布的服务目标证据

**证据强度：** 已有机制确认；运行数据缺失。

**代码定位：** backend/app/services/analytics/telemetry_service.py；backend/app/core/request_id.py；backend/app/core/llm_tracing.py。链接见[代码索引](代码证据索引.md)。

**根因：** request id、LLM tracing、工具审计和 telemetry 已存在；本次没有可验证的端到端 SLO、排队/池等待/loop lag 与发布容量报表。

**影响与边界：** 只报 token 数或模型耗时无法定位 SQL 已变快但接口仍慢，也不能证明取消、恢复和清理时限。

**责任层修复：** 建立 admission→queue→planner→retrieval→LLM→tool→persist→SSE 分段 trace 与成本归因；定义用户视角的成功、首响应、完成和恢复目标。

**验收：** 仪表盘与告警能从一条失败用户请求定位到具体阶段；故障演练测出检测时间、恢复时间和用户影响。

### F18 · P1（允许不可信插件时） · 工具权限门禁不等于外部代码运行沙箱

**证据强度：** 边界确认；无未授权 RCE 结论。

**代码定位：** backend/app/agent_runtime/mcp/manager.py；backend/app/core/ssrf.py；backend/app/core/edition.py；backend/app/agent_runtime/tool_policy.py。链接见[代码索引](代码证据索引.md)。

**根因：** SSRF 防护、环境变量白名单、云版禁 stdio、非 root 运行、ask/allow/deny 与参数审计均有价值；环境过滤无法隔离本地进程的文件系统、网络和资源。

**影响与边界：** community 明确允许受信任本地 stdio 是合理产品边界。若未来接入第三方不可信能力，当前机制不足以宣称安全沙箱。

**责任层修复：** 写明信任模型；不可信插件进入受限进程/容器，限制目录、网络、CPU/内存、秘密注入和生命周期。授权在真实执行入口确定性校验。

**验收：** 能力试图越界读文件、联网、耗尽资源或篡改审批参数时被阻断；受信任本地模式在界面清楚告知权限。

### F19 · P2 · 存在备份/一致性/演练代码，但未证明完整业务恢复

**证据强度：** 工具存在；本次未执行完整恢复。

**代码定位：** scripts/backup.py；scripts/consistency_scan.py；scripts/resilience_drill.py。链接见[代码索引](代码证据索引.md)。

**根因：** 恢复需要数据库、上传文件、索引代际、任务/副作用账本、配置密钥共同一致。脚本或单测存在不代表完成过空环境恢复。

**影响与边界：** 本次临时 pgvector 数据库测试不含真实业务备份恢复，不能借它声称 RPO/RTO 达标。

**责任层修复：** 定义 canonical 与可重建数据，设计备份点一致性；从空环境恢复并执行读写、检索、取消、权限和对账旅程。

**验收：** 记录实际 RPO/RTO、丢失或未知任务数、文件完整性及索引重建时间；定期复演。

## 课程覆盖

| 模块 | 章节 | 审查 |
|---|---:|---|
| 01-python | 13 | [逐章记录](chapters/01-python.md) |
| 02-fastapi | 16 | [逐章记录](chapters/02-fastapi.md) |
| 03-backend-engineering | 22 | [逐章记录](chapters/03-backend-engineering.md) |
| 04-mysql | 23 | [逐章记录](chapters/04-mysql.md) |
| 05-redis | 24 | [逐章记录](chapters/05-redis.md) |
| 06-vector-db | 16 | [逐章记录](chapters/06-vector-db.md) |
| 07-llm-foundation | 14 | [逐章记录](chapters/07-llm-foundation.md) |
| 08-rag | 14 | [逐章记录](chapters/08-rag.md) |
| 09-agent | 24 | [逐章记录](chapters/09-agent.md) |
| 10-system-design | 19 | [逐章记录](chapters/10-system-design.md) |

185 章判定分布：基础具备49、需改进78、不合格27、边界知识31。这是**章节分类而非得分**：同一个根因会映射多章，不能把27章不合格理解成27个独立缺陷，更不能据比例计算生产成熟度。

## 本次尚不能证明的事项

未测目标规模下的 p95/p99、最大租户数、GPU/模型供应商瓶颈和真实成本；未执行当前 pgvector 的完整真实模型问答评测；未做真实外部副作用重复/补偿演练、全量备份恢复、长时间 soak、跨浏览器部署旅程或专业渗透测试。F02 的真实网络报错、F13 的规模退化及 F15 的实际越权均未被本次证明，报告保留为明确边界的架构/防御风险。

本次最有价值的升级起点是：修复 F05/F06/F11，统一运行时与生命周期，修复 Turn/Outbox 的状态所有权，再在当前检索契约上生成可发布质量证据。详细依赖和用户旅程见[升级路线与验收](升级路线与验收.md)。
