# 记忆生命周期审查与改进（2026-09-23）

## 结论与范围

本次针对 Interview Copilot 的长期经验记忆完成代码改进，不引入第二套事实库。用户事实归 CareerProfile、明确规则归 CopilotPreference、原始经历归 History、当前任务进度归执行状态。长期记忆仅保存低权威、带适用条件的经验。

长期记忆已使用 PostgreSQL 普通关系表，没有依赖 Milvus。知识库检索本次新增 PostgreSQL + pgvector 向量、SQL 中文 BM25 和既有 RRF/重排，并在后续清理后作为唯一后端；Milvus 运行时代码与回退配置已删除。具体实现及部署步骤见 [pgvector 迁移说明](pgvector-migration-20260923.md)。尚未操作线上业务数据。

## 参考来源及证据边界

- [Codex 流水线说明](https://github.com/openai/codex/blob/main/codex-rs/memories/README.md)：两阶段提取与整理、来源选择、租约、无输出状态、使用驱动保留、删除投影。读取时文件 blob 为 `9195e89ada8c450e9252f2fc63a95801b9254f3c`。
- [Codex 读取入口](https://github.com/openai/codex/blob/2c087a0cc2ef1d731086a1d0cb0081bdd792cc4d/codex-rs/ext/memories/src/prompts.rs)、[v1 读取策略](https://github.com/openai/codex/blob/2c087a0cc2ef1d731086a1d0cb0081bdd792cc4d/codex-rs/ext/memories/templates/memories/read_path.md)、[v2 读取策略](https://github.com/openai/codex/blob/2c087a0cc2ef1d731086a1d0cb0081bdd792cc4d/codex-rs/ext/memories/templates/memories/read_path_v2.md)。读取代码明确按 MemoryVersion 选择模板；不能把两版策略混称为所有客户端的单一默认行为。README 中部分路径已落后于此提交的 `ext/memories` 读取实现。
- 用户提供的 Claude Code 源码快照：commit `58231dcce408f805c645cfbc352d2876b517223b`。它是用户提供的私有仓库，以下结论限于该快照及其功能门禁，不据此宣称所有公开发行版已默认启用。
  - [提取入口](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/services/extractMemories/extractMemories.ts)
  - [目录及作用范围](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/memdir/paths.ts)
  - [索引选择器](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/memdir/findRelevantMemories.ts)
  - [召回触发、去重及预算](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/utils/attachments.ts)
  - [年龄及陈旧提示](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/memdir/memoryAge.ts)
  - [后台整理](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/services/autoDream/autoDream.ts)、[整理规则](https://github.com/studyzhige-ui/claude-code-source-private/blob/58231dcce408f805c645cfbc352d2876b517223b/services/autoDream/consolidationPrompt.ts)

## 全生命周期对照

| 环节 | Codex 参考 | Claude Code 快照 | 本项目适配 |
|---|---|---|---|
| 产生 | 后台扫描近期、足够空闲、允许来源的历史；有界领取、租约、失败退避；允许无输出 | 主代理完整 query loop 结束后尝试增量提取；游标只在成功后推进；主代理已写入则跳过；重叠请求合并为尾随运行；受功能开关和运行模式限制 | 保留 completed Turn、600 秒空闲、贡献控制、两阶段管线；即时延迟任务和每 5 分钟补扫 |
| 保存 | 阶段一数据库输出；阶段二生成摘要、登记及证据文件 | 主题 Markdown 和索引，部分功能分支支持日志；默认按项目 git root 定位目录 | 来源摘要、候选、证据、规范经验和用户工作区存 PostgreSQL；发布原子事务和版本检查 |
| 召回触发 | v1 自包含任务跳过；涉及历史决策、相关工作区或歧义时轻量检索。v2 先用摘要，额外证据可能改变答案才读取历史 | 每轮最近真实用户请求启动异步预取，需启用 auto memory 和功能门禁；有累计预算、已展示路径去重；无空格请求直接跳过 | 每轮上下文编译可选召回；空请求、禁用、明确忽略、无可用来源、请求过大时直接跳过；其余语义选取允许空集；不照搬英文空格门禁 |
| 召回范围 | Codex home 的版本化记忆目录，按摘要中的任务关系选择；不是天然的多租户数据库隔离 | 默认项目目录；提及配置了 memory 的 agent 时选择对应 agent 目录 | user_id 是硬边界，会话及 Turn 必须属于该用户；项目/岗位/面试条件由 applicability 和当前请求匹配，不宣称存在独立的项目级 ACL |
| 渐进读取 | 摘要→相关索引/证据；v2 避免为已知指针重复查历史 | 扫描最多 200 个头部，模型选至多 5 个，读取正文；每文件 200 行/4096 字节、会话累计预算约 60KB | 最多 100 条索引→至多 4 条完整经验与证据；新增 8000 token 输入预算和 2400 token 上下文块预算；删整条，不截断证据 |
| 更新 | 自动整理；前台明确记住/修改/忘记请求生成 ad hoc note，由整理应用，避免直接改生成文件 | 更新相同主题文件及描述；后台 dream 合并、修订、去重。默认时间/会话门槛 24 小时及 5 个历史会话，可配置且受门禁控制 | 保留语义 key、证据校验、manual 保护、冲突 mixed；新增只把相同版本收据反馈用于该版本评分 |
| 淘汰 | 按来源使用/生成时间选择；删除不再入选的来源投影，整理更新上层记忆 | dream 修正或移除错误、过时、被替代的条目及索引；此次读取未证明统一硬 TTL | 60 天未使用来源由后台清理及 tombstone 防复活；新增召回独立执行同一保留判定，不等待后台 |
| 防陈旧污染 | 当前依据优先；变化快或后果重的结论按需核实，不能把历史当当前事实 | 明确计算年龄，超过一天附带陈旧提醒；已展示记忆去重、按任务选择 | 索引和正文暴露 age_days，保留低权威标识；选择前后查来源及版本；当前请求优先 |

没有照搬文件目录、Rust/TypeScript 运行时或代理的任意文件写权限。数据库中的来源状态及用户边界比提示词优先。也没有照搬跨轮永久“已召回即不再召回”：本项目记忆块每次编译，旧收据不能证明正文仍在本次模型上下文中。

## 已确认问题与修复

1. **过期判定只存在于后台整理。** 原召回仅检查 active；生产开关关闭、worker 停止或任务积压时，过期内容仍可进入选择器。新增 `memory_retention.py`，后台擦除和读取过滤复用来源生成时间/实际使用时间判定。读取不执行删除；选择器调用前后均拦截过期、缺失或非 succeeded 来源。自动记忆缺少当前证据也拒绝。
2. **短索引遗漏结构化适用条件和年龄。** 原代码在有 index_text 时省略 applicability；选择器只能猜测完整边界。现在同时提供 retrieval hook、applicability、age_days；短追问额外携带同一会话、本轮之前至多 4 条消息。当前请求仍有最高优先级。语义判断仍依赖模型，并非确定性证明相关。
3. **固定条数不等于上下文预算。** 原选择器截断请求到前 8000 个字符，可能删除末尾纠正。现保留完整当前请求，超预算依次移除旧对话上下文和低优先级整条索引；请求自身过大时跳过可选召回。正文连同低权威前缀也受独立 token 预算约束，未放入返回块的内容不产生读取收据。
4. **反馈没有版本边界。** 整理原来按 memory_id 累加所有反馈，用户对旧正文的评价会影响新正文。现在通过 memory_version 与当前版本关联；旧收据继续保留供审计，但不评价新版本。

保留窗口依据来源生成时间，不依据经验最近一次整理时间；仅 recall_count/last_recalled_at 不延寿。`last_confirmed_at` 用于展示观测年龄，不代表在线核验。删除来源的历史边是追加记录，读取资格采用当前 `evidence_json`，避免已被替代的历史边永久屏蔽新证据。

## 验证与限制

- `python -m pytest backend/tests/test_services/test_memory_pipeline.py backend/tests/test_services/test_agent_memory_service.py -q -p no:cacheprovider`：39 通过。
- 改动 Python 文件 Ruff 检查通过。
- 默认测试数据库不可达后，启动了不挂载业务数据的 PostgreSQL 15.18 临时容器；两项真实 PostgreSQL 测试通过，覆盖过期过滤、后台清理、并发领取及非空迁移。
- 未运行真实模型语义评测或线上 A/B；无法仅凭契约测试量化误召回率、token 成本或任务成功率。
- 自动来源在读取时被排除并不等于数据库正文已物理清除；正文清除仍需要后台整理运行。legacy/manual 记忆仍由既有管理路径维护，不按自动来源规则误删。
- 全局最多 100 条索引仍有候选覆盖上限。当前 recall_count 是编译阶段记录，后续上下文组装仍可能裁剪；usage_count 是引用，不等同于实际效果。
- 记忆部分没有变更表结构或替用户打开贡献开关；检索部分新增扩展迁移 0047 和旧任务名称迁移 0048。没有执行线上数据迁移。

## Milvus → pgvector 设计依据

**技术上可行，但不是给长期记忆换数据库，也不是仅替换一个 Python 包。** 当前 PostgreSQL 存知识文档/分块事实，Milvus 是可重建索引；默认 embedding 维度为 1024。[pgvector 官方实现](https://github.com/pgvector/pgvector)支持向量距离、精确检索及 HNSW/IVFFlat，混合检索需要另配全文检索并进行融合；pgvector 自身不提供当前 Milvus 的中文分词 BM25 管线。

实现保留现有领域层的多路召回、RRF、重排及 PostgreSQL 最终可见性校验，在索引层增加 pgvector 实现。设计覆盖：

1. **完整索引身份。** 以 embedding 模型、维度、分块策略、词法分析器和检索后端生成 fingerprint；不能把同维度不同模型混在同一空间。PostgreSQL 标识符最长 63 字节，不能直接使用现有最长 220 字符 collection 名拼接表名。
2. **中文词法通道。** PostgreSQL 内置全文检索不等同于 Milvus 的 Chinese analyzer + BM25。本次采用 jieba 中文分词与 PostgreSQL SQL BM25，并保留 RRF；仍需重跑业务中文质量评测。只做向量检索会丢失专名、编号、精确短语等召回保障。
3. **事务及异步任务。** 原 `replace_document_rows` 是外部索引先删后插；本次 PostgreSQL 后端已原子替换对应租户/文档/代际的向量行。保留昂贵 embedding 的异步生成，以及已有 outbox 的任务身份和去重语义，遗留任务由 0048 一次性转换为 knowledge_index_*，运行时不再保留旧任务身份。
4. **租户和过滤后召回。** SQL 参数绑定、user_id 强制条件、document_id/source_kind 白名单；测试 chat_attachment 只能在显式文档范围出现。ANN 的过滤及召回数量需单独评测，不能以先全局 top-k 再客户端过滤代替范围查询。
5. **部署。** 当前镜像为 PostgreSQL 15 Alpine，需要安装相容 pgvector 扩展或选用同主版本镜像；不可借机直接升级 PostgreSQL 主版本。将 Milvus/etcd/专用 MinIO 的 Compose 依赖改为可选，业务文件用的 MinIO 仍需要保留。
6. **重建和切换。** 从 PostgreSQL 文档分块重建新索引；评估重新 embedding 成本，不能假设 SQL 表已存完整向量。对照同一中文评测集，验证租户隔离、删除立即不可见、重试幂等、模型切换、top-k 质量和延迟，再切换读路径并保留回退窗口。

用户明确选择 PostgreSQL + pgvector 混合检索后，以上评估已落实为后端、部署配置、重建工具和测试。中文词法选择固定 jieba 分词与 PostgreSQL 内 BM25 计算，无需额外 BM25 二进制扩展。功能链路完整不意味着与 Milvus 排序逐条相同，也不意味着大型语料性能必然更好；最终验证结果记录在迁移说明中。
