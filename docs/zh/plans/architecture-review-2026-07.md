# 功能架构深度审查与分期改进方案（2026-07）

> 审查日期：2026-07-06
> 范围：七个功能域的**逻辑架构**（非代码风格——结构重构已于 2026-07-02 完成）：
> 模拟面试链路 / 模型供给链路 / SQL·Redis·Celery 基础设施 / 上传与存储 / Agent 链路 / 记忆系统 v3 / 分析管线
> 方法：七个并行深审代理逐文件精读实现（含 whisperx 等三方源码核对），每个发现给出「实际危害场景 + 方案 + 取舍 + 迁移成本 S/M/L」。
> 定位：与 RAG 优化计划（rag-production-optimization-plan.md）同级的执行依据。RAG 链路本身不在本轮范围（刚完成 Phase A-E 优化）。

---

## 一、全局诊断：五条横切主线

逐模块的问题各有清单（第三节），但它们背后是五个反复出现的模式：

### 主线 1：「写了注释没写代码」的机制缺陷

四个模块各有一个精心设计、有完整 docstring、但**实现为空**的机制：

| 机制 | 位置 | 现实 |
|---|---|---|
| `ToolEntry.max_result_chars` | agent 工具注册（10 处精心设定 2K~200K） | dispatch 无一行读取，唯一界限是全局 50K |
| `increment_analyzed_count` | 分析管线（docstring 称"每题递增供 SSE 细粒度进度"） | 全仓零调用，进度是纯时间估算 |
| `last_evidence_at` | 记忆能力状态（注释称"drives staleness"） | dispatch 从不传，字段永停创建时刻，全仓无消费者 |
| `refresh_catalog_for` / `invalidate_all` | 模型目录（docstring 称被 key 配置/刷新端点使用） | 零调用；纯 UI 配 key 的部署目录永远只有 seed |

这类问题的共性危害：文档误导后续所有改动（已实际误导多处注释），且缺陷不可能被测试发现（测试对照的就是这些谎言）。

### 主线 2：per-user 模型配置是「半成品双轨制」（可能是全项目最大的功能性缺陷）

用户在模型页配置的角色选择和 API key，**只对 L2 agent 生效**。L1 聊天、模拟面试、planner、记忆抽取、简历解析、dreaming、面试分析全部走 `RuntimeLLMProxy → get_llm_for_role(user_id=None)` → 恒用系统默认模型 + 部署方 env key。UI 的 `/models/runtime` 显示"已生效"（该端点带 user_id 解析），实际行为完全不同。叠加两个地雷：`get_llm_for_role` 缓存键不含 user_id（一旦有人传 user_id，A 的私钥会 serve 给全体用户）；fallback 链不检查用户 ready 集合（新用户只配 OpenAI key → 聊天 401，而模型页一排绿灯）。

### 主线 3：终态闭环缺失——多条路径通向「用户看不见的黑洞」

- mock finish 后 broker 挂 → record 卡 processing_review 且被 UI 隐藏 + 前端 retry 零调用 → **面试凭空消失**；
- 分析 SSE 8 分钟硬顶 vs 真实端到端 9-17 分钟 → **"明明成功却报 timeout"**；
- broker 消息彻底丢失 → 记录永卡 transcribing 中间态，无僵尸清扫；
- outbox claim 后硬崩 → job 永久卡死（无 stale-lock 回收），dead 无告警；
- SSE 断线 → agent turn 全部蒸发但 save_memory/task_create 副作用已落库；
- 业务删除不删 blob + pending 孤儿无 sweeper → 存储只增不减。

### 主线 4：控制权放错层

- mock 的 `ready_to_finish`：LLM 软信号（只看最近 4 轮）被前端当硬闸锁死输入；后端无任何硬护栏（无最大轮数/阶段题数）；
- chat/agent mode 由前端 localStorage 决定，换设备静默回落；
- 模型 fallback 静默换模型，用户不知情；
- 记忆开关四层 gate 漏一层（post-turn 抽取无视开关照写）。

正确的分配是：**LLM 提议、规则否决、用户终审**；会话属性归后端。

### 主线 5：验证与信任边界的兑现率低

- 上传 magic 校验只在两个不落库的 ephemeral 端点生效，持久化路径（知识/简历/音频）直接吃未验证字节，唯一兑现的是头像；
- 记忆的"保守写入"只存在于 prompt 文字，自报"精通K8s"一步写 strong；
- confirm 可被绕过（consume 接受 pending_upload），presigned TTL 1h 的 TOCTOU 全 purpose 通用。

### 立即修复项（安全/一行级，不等分期）

1. **Gemini url-key 进日志**：5xx 时 HTTPStatusError message 含 `?key=...` 完整 URL 被 logger.error 原样记录；
2. **`get_llm_for_role` 缓存键地雷**（主线 2）；
3. **WhisperX 共享实例线程不安全**：短语音端点在 API 进程无锁并发调 transcribe（whisperx 源码确认写 self.tokenizer）——并发即偶发崩溃/跨语言错解；
4. **记忆写 gate**：`allow_memory_write=ctx.global_memory_on`（一行）。

---

## 二、明确不做的事（决策记录，避免反复议论）

| 不做 | 理由 |
|---|---|
| async SQLAlchemy 迁移 | L+ 成本（91 处 SessionLocal + 全 service 签名 + Celery 双栈）；sync-core + to_thread 是正统模式，只需三条规范固化 |
| 合并 Celery / outbox 双机制 | 划分原则实际成立（Celery=用户在等的前台管线；outbox=与业务事务同生共死的副作用）；把原则写进文档即可 |
| 引入 LiteLLM | 协议已归一（OpenAI-compat 单通道）、弹性/人话层自建且贴产品；换包失去 curated/chat_filter/seed 定制点 |
| 分析进度改 pub/sub | 该修的是轮询读到的数据是假的，不是轮询本身；单机单观察者场景 DB 轮询是正确选型 |
| alembic squash | 收益只是新环境建库快几秒；下个大版本再议 |
| Milvus 记忆检索加投入 | <50 ability states 时全量注入更优；保留给 L2 工具，承认是规模预留 |
| 立即合并 L1/L2 为单循环 | 结构性方向正确（Claude Code 形态）但属 AGT-6 大工程的一部分，先做小项对齐 |

---

## 三、分模块问题总表

成本：S=半天内，M=1-3 天，L=一周以上。各条目 ID 在第四节分期中引用。

### 3.1 模拟面试（MOCK）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| MOCK-1 | finish 失败路径无终态闭环（面试蒸发） | processing_review 超时可见卡片 + 接通 retry-review + 入队失败回滚 mock_in_progress | S |
| MOCK-2 | resume 恢复后 answeredCount=0 锁死复盘按钮 | MockInProgressResp 加 answered_count 或按 conversation_id 重建 turns | S |
| MOCK-3 | current_question_message_id 只写不读；/finish 可重复派发；/start 可叠加 runtime | answer 带令牌比对 409 + finish 状态守卫 + 部分唯一索引 | S |
| MOCK-4 | submit_answer 事务横跨 LLM（连接/锁持有数十秒） | 拆两段短事务；orchestrator 容忍尾部悬空 user 消息 | M |
| MOCK-5 | ready_to_finish 软信号被前端当硬闸；无规则护栏 | LLM 信号降为建议横幅；stage max_questions/整场 max_turns 进规则层 | S |
| MOCK-6 | recent 8 条=只记最近 4 轮，20 轮面试重复提问 | prompt 动态区加全场「已问清单」（每条截 40 字）+ 阶段内计数 | S |
| MOCK-7 | 语音链路死通路（前端转写后丢 blob；voice_mode 存而不读） | **需决策**：接通（复盘可回放原声+表达评估）或删除 | M/S |
| MOCK-8 | _load_mock_qa 把 phase 全谎报 technical | assistant 消息 content_blocks_json 带 stage_key meta | S |
| MOCK-9 | runtime 双状态机冗余（两态可达四态文档） | record.status 唯一事实源；runtime 收敛为在场标记；状态常量统一 | S-M |

保留：plan_json 冻结、generate_plan 不走 LLM、abandon 物理删除、prefix 缓存设计、celery 幂等门。

### 3.2 模型供给（MDL）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| MDL-1 | 消费侧双轨制：per-user 配置只对 L2 生效 | L1/mock/后台全部改显式入口带 owner user_id；Settings.llm 只留系统路径 | M |
| MDL-2 | get_llm_for_role 缓存键地雷（跨用户密钥串用） | 键加 user+指纹，或删 user_id 参数 | S |
| MDL-3 | fast 角色腐化（最忙角色却 UI 不可选、注释矛盾）；fallback 不查 ready、降级无痕 | fast→utility 系统角色退出 selection；fallback 优先用户 ready 集合+留痕 | S-M |
| MDL-4 | refresh_catalog_for/invalidate_all 死代码；user_id 参数是全局缓存陷阱 | key upsert 接通（不回写全局缓存）或砍参数+文档声明 | S |
| MDL-5 | Gemini url-key 日志泄漏；_ping_one 原始异常直通前端 | fetch 失败路径 URL 打码；ping 输出 humanize | S |
| MDL-6 | POST /models/ping 对全目录 30 profile 发真实付费请求 | 限制为该用户 ready 的 profile | S |
| MDL-7 | core→services 反向依赖（catalog 引用 pipeline 私有符号；factory 懒 import auth） | catalog/selection/factory 整体搬 services/model_sources/（或 app/llm/），registry 门面当缓冲 | M |

保留：vendors 声明式适配（新厂商 3 处接入）、三层目录降级、Fernet 密钥设计、api_base 白名单。

### 3.3 基础设施（INF）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| INF-1 | resolve_user_pk 69 处冗余查询；username/pk 双身份贯穿 service 层 | API 层 21 处立即改 current_user.id；service 层分域收敛；memory 域 username 持久键最后迁 | M |
| INF-2 | analyze 派发中间态（broker 挂→僵尸 pending+upload 已 consumed） | catch 派发失败 → set_status(failed) | S |
| INF-3 | rag.py 7 个 async def 纯同步 DB 阻塞事件循环 | 无 await 的端点改 def；删除路径的同步 Milvus 链重点处理 | S |
| INF-4 | own_db 模板手工复制 ~15 处 | 统一 session_scope() 工具 | M |
| INF-5 | outbox claim 后硬崩永久卡死；dead 无出口 | claim 条件加 stale-lock 回收（10min）+ dead>0 告警日志 | S |
| INF-6 | slowapi 无 fallback：Redis 抖动→限流端点全 500 | in_memory_fallback_enabled=True | S |
| INF-7 | 列表查询整行加载 Text 大字段（analysis_json 数十 KB） | load_only / 列查询 | S |
| INF-8 | 状态字符串 72 处/31 文件散落，三套状态机无枚举 | 每域 StrEnum，先收 worker 裸集合 | S-M |
| INF-9 | dreaming 三级跳中间层退化 | scan 直接 enqueue outbox | S |
| INF-10 | _user_memory_lock_sync 绕过统一 sync 连接池 | 改用 sync_redis_client | S |
| INF-11 | revoke() fail-open 与 is_revoked fail-closed 组合缝隙 | 补注释或 revoke 失败抛 503 | S |
| INF-12 | config.py 388 行平铺 | 节标题分组注释（不拆嵌套 settings） | S |

### 3.4 上传与存储（UP）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| UP-1 | consume 接受 pending_upload，confirm 形同可选 | confirm-on-consume（合并逻辑，删独立端点） | S |
| UP-2 | 业务删除不删 blob；delete_object handler 零 enqueue | 删除路径接 outbox（纯接线） | S |
| UP-3 | pending_upload 孤儿无清理 | beat 日任务：>24h pending/failed → 清理 | S |
| UP-4 | 大小上限可绕过（声明自愿；rag.py 入口不查） | confirm 校验 actual_size；rag.py 平行入口收口 | S/M |
| UP-5 | 两套 purpose 词表数值漂移（resume 20MB vs 10MB） | PURPOSE_REGISTRY 单一事实源 | M |
| UP-6 | 持久化路径零 magic 校验（只有头像兑现） | 推广 avatar 模式：confirm 时 head(32) 按 purpose 验 | S-M |
| UP-7 | presigned TTL 1h TOCTOU 全 purpose 通用 | TTL 按 purpose（音频 1h 其余 10min）；进阶 ETag 入 checksum_sha256 | S/M |
| UP-8 | write_file 降级返回值丢弃（DB 记 s3:// 实际在本地） | 接返回值写回；降级产物统一 local:// | S |
| UP-9 | 本地降级半吊子、scheme 解析散落 7 处 | storage 收敛 read/download/delete(uri) 三入口；承认 S3 硬依赖 | M |
| UP-10 | 死代码（无用户前缀 key 的 legacy 函数）；read_file 不过滤 upload_status | 删除 + 过滤 | S |

### 3.5 Agent 链路（AGT）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| AGT-1 | 流中断=turn 蒸发且副作用已落库 | (a)最小：user 消息先落+blocks 增量持久化+finally/shield；(b)正解：turn 后台化+事件缓冲+重连续播 | M/L |
| AGT-2 | max_result_chars 死配置 | dispatch 返回前 enforce（超限走 persist） | S |
| AGT-3 | 记忆写 gate 四层漏一层（post-turn 无视开关） | 定语义（off=不读不写）+ allow_memory_write=ctx.global_memory_on | S |
| AGT-4 | mode 由前端 localStorage 决定 | 提为 conversations.mode 列 | S |
| AGT-5 | live≠replay（4 处缺口，error 事件被前端 throw） | 不变式「凡进 blocks 必先 yield」；error 降格为终态事件 | M |
| AGT-6 | L1 压缩阈值硬编码 1M；chat_strategy 自建 tokenizer | TokenBudget 取 ModelProfile；统一 core.tokens | S-M |
| AGT-7 | 压缩缝隙：assembly 不数 blocks；L2 summary 易失 | blocks 计入 turns_tokens；turn 结束 summary 并回 session | S+M |
| AGT-8 | L2 每 turn 白付一次 planner 调用 | agent mode 跳过 planner | S |
| AGT-9 | 工具小项：check_fn 无 ctx；recall_memory 与注入重叠；read_resume/read_file 分工 | check_fn 传 ctx；工具瘦身；描述分工 | S |
| AGT-10 | graceful fallback 文本进记忆抽取（假事实） | degraded 标记，engine 跳过抽取 | S |

保留/已对齐：blocks 形态、tool 配对协议、reconstruct、402 fatal、软 nudge、SLOT_ORDER、task_* 四件套、沙箱边界。

### 3.6 记忆系统（MEM）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| MEM-1 | last_evidence_at 腐烂（衰减地基坏死） | dispatch 传 now + 注入标注时距 + dreaming stale-review | S+M |
| MEM-2 | 用户删除会被自动重建（最伤信任） | 抽取快照注入「勿再写」或 dispatch 层 30 天 tombstone | M |
| MEM-3 | 编辑 API 无版本检查全文覆盖 | PUT 带 base_updated_at → 409 | S |
| MEM-4 | 幻觉防护只有 prompt（自报一步写 strong） | dispatch 机制化：realtime +1 级上限；strong 归 dreaming/需 evidence | S |
| MEM-5 | doc 无限增长无天花板；compaction_service 同名陷阱 | 阈值触发 dreaming 全文重写压缩（audit 可回滚）；改名 | M+S |
| MEM-6 | 锁 15s 降级裸奔（v2 时代设计，job 本可重试） | 锁加 raise 模式，job 用 raise | S |
| MEM-7 | 抽取质量不可观测（drop/parse-fail 无指标） | metrics 加 patch_dropped/extraction_parse_failed | S |
| MEM-8 | 注入截断按 updated_at 挤掉陈年弱项 | 分层排序（weak/improving 全保） | S |
| MEM-9 | dreaming 阈值 50 条对轻量用户过高；无 archive 表达力 | 事件驱动兜底（completed+静默6h）；协议加降级/archive op | S+M |
| MEM-10 | 杂项：audit 缺 mastery before；evidence_refs 无消费者；recall 默认 false 无引导 | 补 audit 字段；evidence 用起来或删；首次 debrief 后引导 | S |

### 3.7 分析管线（ANA）

| ID | 问题 | 方案 | 成本 |
|---|---|---|---|
| ANA-1 | QA 抽取跑两遍（双倍钱+可能错位回填） | analyze_interview 加 qa_pairs 入参 | S |
| ANA-2 | 抽取要求逐字还原全文→长录音输出截断→空报告 | 索引式输出（LLM 只出边界行号），代码切原文回填 | M |
| ANA-3 | 无断点续跑（任何失败从 ASR 重头） | 阶段门三个 if（有 transcript 跳 ASR 等） | S |
| ANA-4 | 假进度+8 分钟假超时+SSE 终态不认 review_ready | 终态补全+状态驱动 percent+真增量+上限对齐 time_limit | S+1天 |
| ANA-5 | WhisperX 线程不安全+API 进程重复吃 1.5GB | 止血锁；正解短语音走 registry（云优先） | S/M |
| ANA-6 | 批改失败静默塞 0 分照常 completed；30 题无上限并发 | JSON mode+重试+Semaphore+失败题 NULL+synthesis 排除 | S-M |
| ANA-7 | 无 reanalyze 入口（failed 死记录；prompt 迭代无法回放） | POST /interview-records/{id}/reanalyze | S |
| ANA-8 | 云 ASR 撑不起长录音（25MB/120s 限制） | 按时长切片并发转写，或长音频强制本地 | M |
| ANA-9 | 杂项：僵尸中间态清扫缺失；说话人数硬编码 2；grounding_refs 死字段；useAnalysisStream 死代码 | beat 清扫任务；配置化；决策用或删 | S |

---

## 四、分期执行方案

每期独立可交付、测试保驾、完成后可暂停。顺序按「安全 → 可靠性 → 数据卫生 → 功能正确性 → 产品能力 → 架构对齐 → 结构收口」，第 4-6 期可按兴趣重排。

### Phase 0：安全与一行级止血（~1 天）
MDL-5（key 日志打码）、MDL-2（缓存键地雷）、ANA-5 止血锁、AGT-3（记忆写 gate）、AGT-2（max_result_chars）、AGT-8（跳过 planner）、AGT-10（degraded 不进抽取）、INF-6（slowapi fallback）、MEM-1 的 bug 修复部分（dispatch 传 last_evidence_at）、INF-10。
**验收**：全量测试绿；日志中无 key；两用户并发短语音转写不崩。

### Phase 1：可靠性终态闭环（~2-3 天）
INF-2（派发失败落 failed）、INF-5（outbox stale-lock+dead 告警）、MOCK-1（复盘黑洞三件套）、MOCK-2（恢复 answered_count）、ANA-4（进度说真话）、ANA-9 僵尸清扫、INF-11。
**验收**：kill broker/worker 的每种时点，记录都到达用户可见的终态；60 分钟录音分析全程进度真实且不假超时。

### Phase 2：上传生命周期闭环（~2-3 天）
UP-1（confirm-on-consume）、UP-2（删除接 outbox）、UP-3（孤儿 sweeper）、UP-4（大小校验+rag 入口收口）、UP-5（PURPOSE_REGISTRY）、UP-6（magic 推广）、UP-7（TTL 按 purpose）、UP-8、UP-10。UP-9（storage 三入口）可顺带或延后。
**验收**：七条流入路径对照表全绿（验证/生命周期/清理三列无空格）；删除记录后 MinIO 对象随之消失。

### Phase 3：模型供给统一（~2-3 天）
MDL-1（消费侧统一，核心）、MDL-3（utility 角色+fallback ready）、MDL-4（死代码接通/砍）、MDL-6（ping 收窄）。MDL-7（搬 app/llm）可延到 Phase 7。
**验收**：用户配置的角色/key 在 L1 聊天、mock、后台任务全部真实生效；只配 OpenAI key 的新用户开箱即用。

### Phase 4：分析管线增效（~3-4 天）
ANA-1（双抽取）、ANA-2（索引式输出）、ANA-3（阶段门）、ANA-7（reanalyze）、ANA-6（批改失败策略）、ANA-5 正解（registry 化）、ANA-9 杂项。ANA-8（云切片）视 TRANSCRIPTION_PROVIDER 使用情况可选。
**验收**：60 分钟录音端到端时间下降 ≥30%；批改失败题显示为「未评分」而非 0 分；failed 记录一键重跑。

### Phase 5：模拟面试补全（~2-3 天）
MOCK-5（控制权三层）、MOCK-6（已问清单）、MOCK-3（并发令牌）、MOCK-8（stage_key 落 meta）、MOCK-9（runtime 收敛）、MOCK-4（两段事务）、MOCK-7（**语音：需决策**）。
**验收**：20 轮面试无重复提问；LLM 说结束不再锁死输入；复盘报告分阶段归因正确。

### Phase 6：记忆生命周期闭环（~3-4 天）
MEM-8（排序）、MEM-4（升级纪律）、MEM-3（乐观锁）、MEM-7（可观测）、MEM-6（锁 raise）、MEM-2（tombstone）、MEM-9（dreaming 事件化）、MEM-1 的 stale-review、MEM-5（doc 压缩）、MEM-10。
**验收**：删除的记忆不复活；自报无法一步 strong；轻量用户每周至少一次 dreaming；drop 率可查。

### Phase 7：Agent 链路对齐（6a ~2-3 天；6b 单独设计）
6a：AGT-4（mode 入库）、AGT-6（窗口取 profile）、AGT-7（压缩缝隙）、AGT-5（live=replay 协议）、AGT-9（工具小项）。
6b：AGT-1 正解（turn 与连接解耦、事件缓冲、断线续播）——**单独立设计文档**，与 agent-context-management 计划合流；顺带评估 L1/L2 合并为「planner 路由的单循环」。
**验收**（6a）：刷新页面后 replay 与 live 逐字节一致；128K 模型下 L1 压缩正常触发。

### Phase 8：结构收口（~2 天）
INF-1（身份收敛，API 层先行）、INF-8（StrEnum）、INF-4（session_scope）、INF-3+INF-7（def 化+load_only）、INF-9、INF-12、MDL-7（若未做）。
**验收**：resolve_user_pk 调用归零（API 层）；worker 无裸状态字符串。

**总量级**：约 18-25 个工作日的实现量（不含 6b）。每期完成即提交+两审，与 RAG 计划同款纪律。

---

## 五、待用户决策的三个问题

1. **分期顺序**：按上表推进，还是调整（例如你更关心的模块先做）？
2. **MOCK-7 语音链路**：接通（复盘回放原声+表达评估，M）还是删除死通路（S）？
3. **AGT-1 turn 解耦（6b）**：现在就立设计文档，还是等 Phase 0-7 落完再议？
