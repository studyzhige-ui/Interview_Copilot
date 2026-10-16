# 工具、上下文、记忆全生命周期审计

日期：2026-10-15。范围：当前本地实现及隔离测试副本；不代表已发布版本，也不代表所有外部连接器已经真实执行验收。

## 结论与证据边界

这套实现已经具备可讲述的工程架构：工具有可信定义、策略准入、执行账本和恢复语义；上下文有预算、可回读投影、压缩和带版本的恢复；记忆有证据提取、整理、条件化更新、选择性召回及遗忘。不能再简单归为只把聊天记录塞进 prompt 的 demo。

但不能诚实地宣布“全面功能全部优秀”或“达到 Codex/Claude Code 同等成熟度”。本次实测证明了具体链路，尚未证明大规模真实用户收益、所有供应商行为、所有业务工具副作用和长时间故障恢复。尤其模型对自己是否使用了记忆的解释仍有错误。以下区分实现、已验证行为和剩余风险，避免用测试通过数代替产品成熟度。

## 参照范围

- Codex 源码快照：`2a6ecbb93c42c3eea835126c0c332517968ab2f4`。重点阅读 `codex-rs/memories/README.md`、`core/src/tools/parallel.rs`、`orchestrator.rs` 和 provider cache 相关代码。借鉴的是两阶段记忆、租约和输入校验、并发/独占工具、恢复边界。
- 用户提供的 Claude Code 本地快照：`58231dcce408f805c645cfbc352d2876b517223b`，`D:/Projects/TypeScript/Claude Code/src`。重点阅读 `StreamingToolExecutor.ts`、compact、SessionMemory、memoryAge。它只是本地参照快照，不能据此断言与官方线上版本一致。
- 项目已有压缩模板源于 Codex `83dc7d11e873f43533dc898d50fae71cf4d55dc5`，随源码保留 LICENSE/NOTICE；本轮没有直接复制 Claude Code 源码。
- [DeepSeek 缓存文档](https://api-docs.deepseek.com/guides/kv_cache/)说明缓存自动、尽力命中；[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)说明思考开关和预算行为；[OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)说明自动前缀缓存。供应商缓存不是应用账户隔离机制。

## 工具系统：定义到回收

| 环节 | 当前机制及代码入口 | 本轮证据/边界 |
|---|---|---|
| 定义 | `tool_registry.py`：类型参数、handler、effect、并发安全、preflight、资源身份、receipt resolver | 合成工具走真实注册、schema、解析、执行链；不是只 mock 最终返回 |
| 发现与暴露 | `builtin_tools.py`、`turn_tool_catalog.py`：实际连接决定注册；每轮快照、技能/MCP 动态发现 | MCP stdio/HTTP 协议及账户隔离回归；外部服务实际授权未逐一重验 |
| 模型使用 | provider adapter → 流式调用 assembler → typed dispatch plan | 参数碎片、无效 JSON、重复键、NaN、数组及参数不符被拒绝 |
| 准入 | `tool_policy.py` + preflight：可信 effect、账户、资源、连接范围、任务授权 | 模型不能自行声明 effect 或借工具描述获取权限；领域服务仍负责所有权 |
| 规划与并发 | `tool_batch.py`：只有明确安全的工具可并行，资源冲突隔离 | 保留模型结果顺序；取消时取消并回收待完成任务。未进行高并发压力证明 |
| 执行与身份 | `tool_call_executor.py`：call id、参数指纹、turn/generation、handler started、持久化结果 | 同身份重放不再次执行；同 id 参数冲突被拒绝 |
| 超时/取消 | 按是否可能产生副作用区分可知失败和 unknown | READ 超时为 timeout；已启动 external write 超时/取消为 unknown，不能假定失败后自动重做 |
| 结果与上下文 | 原始结果留在账本，模型可见预览/引用，可按 call id 回读 | 大结果投影和回读、call/result 配对测试 |
| 响应结束 | 本轮补齐无工具最终回答的 stop reason 校验 | length/max_tokens/content_filter/缺失结束信号不能作为完成答案；Chat 保留部分输出并标记未完成 |
| 恢复/终止 | turn store + 执行账本 + 代次 fence；终止关闭未结算模型调度 | 真实 PG 并发测试及后端回归；unknown 不等于 exactly-once 外部执行保证 |

设计核心：权限属于可信策略和领域 owner，模型只提出调用；执行结果、展示事件和模型上下文是不同投影。外部写操作即使断网也不能虚构成功或盲目重试。取消本地协程不代表远端操作已撤销。

## 上下文：装配到恢复与删除

| 环节 | 当前机制/本轮修复 | 验证与边界 |
|---|---|---|
| 数据边界 | 原始对话、当前请求、记忆、业务对象、检索证据、运行控制分别装配 | owner 仍为事实源；摘要不是事实数据库，也不产生授权 |
| 请求预算 | `context_budget.py` 统计消息与工具 envelope，预留输出及安全空间；Agent 使用供应商 usage 校准 | token 数是估计，不承诺精确复刻所有模型 tokenizer |
| 减压 | 单工具输出限额 → 可回读引用 → 摘要 + 最近完整交互 → 实际 envelope 再检查 | 大输出和配对测试；不可容纳必要信息时明确报容量错误 |
| 压缩输入 | 本轮 `persistent_history()` 排除可撤回记忆、偏好、业务快照和运行指令 | 这些内容不再被直接压入持久摘要；历史助手已说出的内容仍是历史，不等于彻底擦除 |
| 当前状态 | 每次请求重新装配动态 owner 数据；catalog guidance 移出共享系统前缀 | 保留当前请求与运行状态；MCP schema 本身仍可能是账户特有数据 |
| 检查点 | format v2 + CAS version + transcript cursor + turn generation | 旧格式摘要可能夹带过期记忆，拒绝复用并回放原始历史；保留 CAS fence，不重置写版本 |
| 迟到结果 | 保存时锁 conversation/turn，校验 owner、running、cancel_requested 和代次 | 取消、请求取消、换代次、owner 不符四种回归 |
| 终止回收 | 本轮 `_terminalize` 同事务删除该 turn 的临时检查点 | completed/failed/cancelled 均验证；不删除正式窗口和原始记录。历史遗留临时行未批量清理 |
| 删除 | conversation FK cascade；记忆来源撤回走自己的 invalidation | 删除记忆不自动改写已显示的历史助手回答；需要删除历史时走会话删除链 |
| Prompt cache | 稳定 tools/system 前缀；Anthropic 显式 marker；OpenAI/DeepSeek 自动缓存 | DeepSeek hit 字段已归一化。命中 token 仍占逻辑窗口，不能从容量预算中扣除 |
| 缓存统计 | 修复 DeepSeek `prompt_cache_hit_tokens`，区分 enabled 与 hit | 实测 453/468 输入各命中 128，477 输入命中 256；不是命中率承诺或用户数据隔离证明 |

长历史实测加入 40 对冗余交互，两次压缩并序列化/恢复后，上海、最新 35k 底线、只核实 B、薪资未知、未授权投递、resume.pdf 六项全部保留。首轮压缩后 envelope 估计 7,962 tokens，保留最近 28 条消息。没有记录相同口径的原始 envelope 数，不能把供应商摘要输入 tokens 当成原始总量计算压缩率。此样本不代表无限轮次语义无损。

## 记忆：形成、固化、更新、使用、遗忘

| 环节 | 当前机制 | 实测或测试证据 |
|---|---|---|
| 来源与开关 | deployment、account、conversation 控制；只接收合格完成轮次，排除活跃/失败/敏感输入 | 不合格来源不会调用模型；代码默认 producer 关闭，检查时运行中的 QA 部署为开启。未读取用户私人开关 |
| 提取 | `consolidation.extract_turn`：原文 quote/seq 支持、租约、fingerprint、失败重试 | 六个真实模型样本：条件反馈、重复方法提取；职业事实、显式规则、一次性要求、注入不作为此类经验记忆 |
| 整理与持久化 | 第二阶段按 user 整理，版本化条目、来源、条件、效果、索引；数据库保存 | 临时业务库端到端 extraction → publication → 新会话 recall；不是进程内变量 |
| 条件与冲突更新 | 更新保留证据来源和适用条件；人工版本修改受保护 | 真实新反馈使旧表格记忆升到 v2，标为 mixed/宽屏适用，新增窄屏负面及短段落有效经验 |
| 召回 | 先校验开关，有限索引选择，再重验当前版本/来源；有时限及 token 限额 | 相关比较召回，不相关翻译及明确拒绝记忆不召回；账户隔离测试 |
| 帮助回答 | compiler → 原生 provider wire → 模型答案；当前要求优先 | 新会话中记忆编辑后出现“先排除/再比较/待核实”；本轮要求表格可覆盖；四个指定事实保留 |
| 记录使用 | recall receipt、版本、引用匹配；曝光/使用/反馈分开 | 不能把“召回过”当成“帮助了用户”，也不能相信模型自报是因果证据 |
| 反馈与管理 | 反馈、版本编辑、停用、提升到显式偏好、删除有独立 owner 路径 | 编辑或提升期间后台整理不能覆盖人工修改 |
| 失效/遗忘 | source invalidation 清空派生投影，lease/input fence 阻止迟到复活；闲置保留期限 | 删除后 recall 为空；重新处理旧来源不重建；提取/整理/选择过程中撤回的竞态测试 |
| 后台恢复 | worker 扫描未完成来源及工作区，租约、失败退避、空结果终态 | 合约测试；本轮没有杀死整个生产 worker 做长时间恢复演练 |

这里的自动记忆是“有证据、带适用条件的交互经验”，不是所有个人事实都写入一个向量库。个人事实、明确偏好、业务对象有各自 owner。记忆可以持久化并更新，且实测能影响答案；这仍不足以证明真实任务成功率提高。

重要人工发现：最终样本虽满足格式与事实检查，模型却声称“未采用历史记忆”，并对已给定单程的通勤重复提出口径疑问。相关报告保留完整输出。不能把六个布尔断言通过包装成语义质量满分，也不能用模型解释作为严格的记忆归因。

## 本轮修复及行为变化

1. 可撤回动态数据不再直接进入持久检查点或摘要；旧格式从原始历史重建，代价是首次恢复可能多花 token。
2. 检查点写入补齐取消/owner/代次校验；终止时清理当轮临时投影。
3. catalog guidance 从稳定系统前缀移到每轮运行上下文，降低无关前缀变化。
4. DeepSeek 缓存命中统计和自动缓存能力声明修正；不把 miss 当 cache creation。
5. `DEEPSEEK_REASONING_EFFORT` 显式配置，默认 `none`。两次真实请求分别用 1,500 和 4,096 输出预算仍被隐式高强度思考耗尽，因此没有继续盲目加预算。需要思考时可设 low/high/max，并同步评估输出预算与延迟。
6. Agent/Chat 对不完整最终答案不再报告完成；保留部分文本和失败原因。
7. Direct prompt 明确记忆不证明当前事实/授权，计算要区分事实与假设。它改善边界表达，不构成模型绝不幻觉的保证。

## 验证账本与复现

原始输出在本地 `data/lifecycle-audit-20261015/`，其中 usage.sqlite 是合成测试的真实调用计费账本，业务数据使用独立临时 SQLite，不读取生产用户会话。

| 验证 | 当前结果 |
|---|---|
| Linux 容器隔离代码副本后端套件，排除 release/browser/model_acceptance | 227 passed，13 skipped，`backend-linux-final.xml` |
| PostgreSQL 临时库（真实独立连接、迁移和并发） | 12 passed，`postgres-final.xml` |
| 本轮相关 Python 文件 Ruff | check 通过，format 完成 |
| 真实记忆提取/整理/选择 | `memory-selection.json`：10 项通过 |
| 真实记忆条件冲突更新 | `memory-automatic-update.json`：通过，保留两次来源 |
| compiler/native-wire 回答对照 | `memory-production-revised.json`：六个行为检查通过；人工语义缺陷见上文 |
| 两次压缩/恢复及长历史 | `context-continuation.json`、`context-pressure.json`：各六项通过 |

失败记录也属于证据：Windows 广泛套件曾有 HTTP MCP 线程收尾失败及 Anthropic SDK 版本不符，207 passed/23 skipped/2 failed，保留 `backend.xml`。Linux 部署依赖环境通过，不据此宣称 Windows 环境全绿。新增终止测试初版触发 SQLite fixture commit 泄漏，导致后续唯一键冲突；按已有测试约定把该测试的服务 commit 留在 fixture rollback 边界后重跑通过，未改变产品逻辑来迎合测试。早期模型截断留下 usage ledger；`memory-production-prompt.json` 的事实保持检查失败仍保留，后续明确要求保留四个原始值后才通过。

复现（使用项目依赖齐全的环境；live 会实际调用模型）：

```text
python -m pytest backend/tests --ignore=backend/tests/release --ignore=backend/tests/browser --ignore=backend/tests/model_acceptance -q
python evaluation/memory_lifecycle_eval.py --live --output data/logs/memory-selection.json
python evaluation/memory_lifecycle_eval.py --live --integration-only --update-checks --output data/logs/memory-update.json
python evaluation/memory_lifecycle_eval.py --live --integration-only --answer-checks --output data/logs/memory-answer.json
python evaluation/memory_lifecycle_eval.py --live --context-only --context-history-pairs 40 --output data/logs/context-pressure.json
```

PG 测试需要显式配置 `TEST_PG_ADMIN_URL` 和 `REQUIRE_TEST_POSTGRES=1`，自动创建/删除临时数据库。不要将 SQLite 成功等同于锁语义验证。

## 面试可讲的内容与上线前边界

可以讲：“我们把事实源、模型投影和执行账本拆开。工具先做可信授权和类型校验，外部写入不确定时停止自动重试。上下文压缩保留完整工具交互与最近历史，可撤回记忆不进入长期摘要。记忆有原文证据、条件、版本和删除失效链。用真实模型测了新会话使用与条件更新，用 PostgreSQL 测并发写入 fence。”

不能讲：“记忆必然提高所有回答质量”“外部操作 exactly-once”“任何历史压缩都无损”“所有工具均做了真实账户端到端验收”“跟 Codex 一样成熟”。需要继续积累的是：多轮真实任务评测集、引用/归因正确率、长期并发与故障注入、各连接器沙箱验收、缓存成本/延迟的长期分布，以及运行环境发布验收。

本轮修改保留在工作区，隔离副本已验证；没有覆盖运行中的 `/app` 或重启部署，也没有发布。已有其他工作区改动未作为本次成果提交。变更前检查点为 `refs/checkpoints/lifecycle-audit-20261015`（`e3fd0f2dfc032dc7f1cd79b68597d627de1fa0b5`）。
