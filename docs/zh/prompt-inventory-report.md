# Interview Copilot Prompt 全量盘点与统一管理建议

> 盘点日期：2026-06-10  
> 盘点范围：当前工作树中的 `backend/`、`frontend/`、`evaluation/`、`scripts/`、`alembic/`、`docs/`、`.claude/`、`.github/`  
> 当前分支：`feat/rag-optimization`  
> 说明：本报告基于当前工作树，包括尚未提交的 `query_planner.py` 改动。

## 1. 结论摘要

当前项目中，与模型行为直接相关的内容不是单一的“prompt 文件”，而是四类共同组成：

1. **15 类生产业务 prompt 家族**：聊天、Agent、规划、模拟面试、分析、记忆、简历解析等。
2. **16 个生产环境直接 LLM 调用点**：其中 15 个承载业务 prompt，另 1 个是模型连通性 `ping`。
3. **共享 prompt 组装层**：把 system prompt、面试记录、摘要、历史、记忆、RAG、当前问题拼成最终输入。
4. **Agent 工具提示面**：10 个工具描述和 24 个参数描述，同时进入 system prompt manifest 和 function-calling schema。

目前只有记忆模块将两个 prompt 集中在 `backend/app/services/memory/prompts.py`；其余 prompt 分散在业务模块内，且命名方式不统一，有模块常量、函数内联 f-string、动态前缀和 schema 描述等多种形态。

建议优先做“**统一治理与可观测**”，不要立刻做可在线编辑的重量级 Prompt Manager。项目现有设计文档也明确反对为了缓存而增加 prompt manager；统一管理的核心应是：

- 每个 prompt 有稳定 ID、版本、负责人、用途、模型角色、输入变量、输出协议和评测入口。
- 固定指令集中管理，动态上下文继续由业务代码负责。
- 所有 LLM 调用可追踪到 `prompt_id` / `prompt_version`。
- JSON 输出 prompt 统一使用结构化输出和 schema 校验。
- 对用户、简历、JD、转录、RAG、网页和工具结果建立清晰的不可信数据边界。

## 2. 数量与分布

| 类型 | 数量 | 说明 |
| --- | ---: | --- |
| 生产业务 prompt 家族 | 15 | 下文 P01-P15 |
| 生产直接 LLM 调用点 | 16 | 15 个业务调用 + 1 个模型 `ping` |
| 评测专用 prompt | 1 | `evaluation/runners.py` 的 RAG 回答评测 |
| Agent 工具 | 10 | 工具描述会影响模型决策 |
| Agent 参数描述 | 24 | Pydantic `Field(description=...)`，进入工具 schema |
| 共享上下文槽位 | 7 | system、record、summary、recent、memory、RAG、current query |
| 模拟面试 persona | 4 | friendly / professional / rigorous / pressure |

按文件分布：

| 领域 | 主要文件 |
| --- | --- |
| L1 Chat / RAG | `backend/app/conversation/chat_strategy.py` |
| Query Planner | `backend/app/conversation/query_planner.py` |
| L2 Agent | `backend/app/conversation/agent_strategy.py` |
| Prompt 组装 | `backend/app/services/chat/context_assembly_pipeline.py` |
| Agent 工具提示面 | `backend/app/agent_runtime/tool_registry.py`、`backend/app/agent_runtime/tools/*.py` |
| 模拟面试 | `backend/app/services/interview/mock_interview_service.py` |
| 面试分析 | `backend/app/services/voice/interview_analysis_service.py`、`backend/app/services/interview/analysis_orchestrator.py` |
| 长短期记忆 | `backend/app/services/memory/compaction_service.py`、`prompts.py` |
| 简历解析 | `backend/app/services/resume/resume_service.py` |
| 能力诊断 | `backend/app/services/analytics/diagnostics_report_service.py` |
| 评测 | `evaluation/runners.py` |

## 3. 生产 Prompt 清单

### 3.1 用户回答与 Agent

| ID | 用途 | 定义 / 组装位置 | 调用位置 | 模型角色 | 输出 |
| --- | --- | --- | --- | --- | --- |
| P01 | L1 普通聊天 | `backend/app/conversation/chat_strategy.py:80` `DIRECT_SYSTEM_PROMPT` | 同文件 `:115-118` | `fast` | 流式自然语言 |
| P02 | L1 RAG 回答 | `backend/app/conversation/chat_strategy.py:83` `RAG_SYSTEM_RULES` | 同文件 `:109-113` | `primary` | 流式自然语言 |
| P03 | L2 执行 Agent | `backend/app/conversation/agent_strategy.py:66` `SYSTEM_PROMPT` + 动态工具 manifest | 同文件 `:300-318`、`:520-528` | `agent` | 流式文本 + tool calls |

#### P01 L1 普通聊天

- 固定规则很薄：简洁技术面试助手；相关时使用 session state / memories；上下文不足时说明缺失。
- 最终 prompt 由共享组装器拼接，不是独立 system/user messages。
- 动态输入：面试记录上下文、会话摘要、最近对话、长期记忆、当前问题。

#### P02 L1 RAG 回答

- 固定规则仅要求使用检索知识作为证据并避免编造来源。
- 动态输入在 P01 基础上增加 `[Retrieved Context]`，每个 chunk 标记为 `[K#]`。
- 当前规则没有明确要求输出 `[K#]` 引用、证据不足时的部分回答格式、禁止把 memory 当作可引用来源。
- `docs/zh/rag-generation-optimization-plan.md` 已记录此问题和目标 prompt，但当前源码尚未落实该完整版本。

#### P03 L2 执行 Agent

- system prompt 包含能力、工具使用原则、错误处理和输出规则。
- 动态追加 `Available tools` manifest。
- 工具同时以 OpenAI function-calling schema 传入。
- 动态输入：共享上下文中的 record / summary / memory / RAG，以及真实历史 messages、当前 user message、工具结果。
- Agent 是风险最高的 prompt 面，因为 prompt 注入可能进一步诱导工具调用。

### 3.2 规划、模拟面试与报告

| ID | 用途 | 定义 / 组装位置 | 调用位置 | 模型角色 | 输出 |
| --- | --- | --- | --- | --- | --- |
| P04 | Query Planner | `backend/app/conversation/query_planner.py:130-175` 函数内动态组装 | 同文件 `:178-181` | `fast` | JSON object |
| P05 | 模拟面试下一轮 | `backend/app/services/interview/mock_interview_service.py:85-105`、`:204-231` | 同文件 `:253-264` | `mock_interview` | JSON object |
| P06 | 综合能力诊断报告 | `backend/app/services/analytics/diagnostics_report_service.py:68-79` | 同文件 `:80-83` | `fast` | JSON object |
| P07 | 面试记录浓缩摘要 | `backend/app/services/interview/analysis_orchestrator.py:458-472` | 同文件 `:477-478` | `fast` | JSON object，未声明 `response_format` |

#### P04 Query Planner

- 决定是否检索知识库、生成 dense/sparse query、决定是否加载完整学习策略。
- prompt 根据 `global_memory_on` 动态改变输入槽位和输出 schema。
- 当前问题被保证只出现一次并位于末尾，已有专门测试。
- 失败时退化为使用原问题进行检索。
- 当前模板是函数内字符串拼接，不利于独立版本管理和评测映射。

#### P05 模拟面试下一轮

- 由稳定前缀、面试阶段、当前阶段、最近对话、候选人回答和输出规则组成。
- 稳定前缀包含完整简历、完整 JD、面试官 persona，设计上用于命中 prompt cache。
- 4 个 persona 文本位于 `INTERVIEWER_STYLES`，也属于 prompt 资产。
- JSON 解析失败时使用固定兜底问题。

#### P06 综合能力诊断报告

- 输入是能力状态记录，输出整体评价、优势、弱项和固定维度雷达图。
- 模板为函数内 f-string。
- 雷达维度硬编码在 prompt 中，属于业务口径，应纳入版本管理。

#### P07 面试记录浓缩摘要

- 输入标题、用户标签、分析概览、题目清单和转录片段。
- 输出标签和 200-400 字摘要，摘要之后会长期进入 debrief chat 的 `[Record Context]`。
- 这是“生成一次、长期影响后续 prompt”的高杠杆 prompt。
- 要求严格 JSON，但调用没有传 `response_format={"type": "json_object"}`。

### 3.3 简历与面试分析

| ID | 用途 | 定义位置 | 调用位置 | 模型角色 | 输出 |
| --- | --- | --- | --- | --- | --- |
| P08 | 简历结构化解析 | `backend/app/services/resume/resume_service.py:30-50` `PARSE_PROMPT` | 同文件 `:117-122` | `fast` | JSON array / object |
| P09 | 从 ASR 转录提取 QA | `backend/app/services/voice/interview_analysis_service.py:62-99` `_LLM_EXTRACTION_PROMPT` | 同文件 `:136-147` | `fast` | JSON object |
| P10 | 单题深度分析 | 同文件 `:296-318` `_PER_QUESTION_PROMPT` | 同文件 `:379-391` | `primary` | JSON，未声明 `response_format` |
| P11 | Mock 面试批量评分 | 同文件 `:657-707` `_BATCH_PROMPT_PREFIX` / `_BATCH_PROMPT` | 同文件 `:746-772` | `primary` | JSON，未声明 `response_format` |
| P12 | 全局复盘综合报告 | 同文件 `:421-478` `_SYNTHESIS_PROMPT` | 同文件 `:513-521` | `primary` | JSON，未声明 `response_format` |

#### P08 简历结构化解析

- 输入完整简历文本。
- 输出 section type、标题、原文和 metadata。
- prompt 要求“只输出合法 JSON 数组”，但调用使用 `json_object` response format；代码同时兼容对象和数组。输出协议存在轻微不一致。

#### P09 ASR QA 提取

- 输入转录全文，可附加简历提示。
- 负责角色识别、QA 提取、追问关联、阶段分类。
- 对长转录会分块调用，prompt 质量会直接影响后续全部评分。

#### P10 单题深度分析

- 输入单题、前序窗口、简历片段和 JD 片段。
- 输出 score、critique、improved_answer、tags。
- 仅靠文本要求 JSON，没有使用结构化输出参数。

#### P11 Mock 面试批量评分

- 使用完整简历 + JD 作为 cache-stable prefix。
- 输入前置窗口、本批题目、后置窗口。
- 评分维度按 phase 写死在 prompt 中，属于核心产品评分标准。
- 仅靠文本要求 JSON，没有使用结构化输出参数。

#### P12 全局复盘综合报告

- 输入完整简历、JD 和逐题分析摘要。
- 输出整体分、成长领域、阶段摘要和技能雷达。
- “成长陪练而非把关人”是关键产品定位。
- 仅靠文本要求 JSON，没有使用结构化输出参数。

### 3.4 记忆与上下文压缩

| ID | 用途 | 定义位置 | 调用位置 | 模型角色 | 输出 |
| --- | --- | --- | --- | --- | --- |
| P13 | 会话摘要压缩 | `backend/app/services/memory/compaction_service.py:42-91` `COMPACTION_PROMPT` | 同文件 `:162-169` | `fast` | JSON object |
| P14 | 实时记忆抽取 | `backend/app/services/memory/prompts.py:40-125` `REALTIME_EXTRACTION_PROMPT` | `realtime_extraction.py:96-105` | `fast` | JSON array |
| P15 | 夜间记忆整理 | `backend/app/services/memory/prompts.py:136-208` `DREAMING_PROMPT` | `dreaming_worker.py:358-374` | `fast` | JSON array |

#### P13 会话摘要压缩

- 同一个 prompt 被两个流程复用：
  - 外层会话压缩，将摘要写入 session `summary`。
  - L2 Agent 内层 autocompact，将旧消息压成 reference-only system message。
- 输出固定六章节，之后会再次注入模型上下文。
- 属于“模型生成内容再进入高权限上下文”的高风险 prompt。

#### P14 实时记忆抽取

- 每轮对话后运行，只提取强信号。
- 输入用户画像、学习策略、能力索引和最新对话。
- 输出会写入长期记忆，并影响未来大量会话。
- prompt 详细、保守，已有清晰的正反例和路由协议。

#### P15 夜间记忆整理

- 按 interview record 周期综合复盘对话和当前记忆。
- 允许跨 session 推断稳定认知、方法和习惯。
- 输出会写入长期记忆。
- `dreaming_worker.py` 会将记录消息压平为单行，但这不能完全消除语义层 prompt injection。

## 4. 其他必须纳入管理的 Prompt 面

### 4.1 共享上下文组装器

文件：`backend/app/services/chat/context_assembly_pipeline.py`

最终顺序由唯一的 `SLOT_ORDER` 定义：

1. system prompt
2. `[Record Context]`
3. `[Context Summary]`
4. `[Recent Turns]`
5. `[Memory]`
6. `[Retrieved Context]`
7. `[Current Query]`

这不是业务 prompt 文案，但它决定：

- 哪些数据进入模型。
- 数据以什么权限和顺序出现。
- prompt cache 是否命中。
- prompt injection 的影响范围。
- token budget 和裁剪后模型实际看到什么。

统一管理时必须保留此层为代码控制，不应让运营配置随意调整槽位顺序。

### 4.2 Agent 工具描述与参数描述

文件：

- `backend/app/agent_runtime/tool_registry.py`
- `backend/app/agent_runtime/tools/*.py`

当前有 10 个工具：

- `read_file`
- `write_file`
- `read_interview_history`
- `search_jobs`
- `search_knowledge`
- `recall_memory`
- `save_memory`
- `read_resume`
- `web_search`
- `read_url`

工具描述会同时进入：

1. Agent system prompt 中的 `Available tools` manifest。
2. OpenAI function-calling `tools` schema。

另外有 24 个 `Field(description=...)` 参数描述进入 schema。它们直接影响模型何时调用工具、如何填参数、是否误用工具，因此必须作为 prompt 资产管理，而不是普通代码注释。

### 4.3 Prompt 片段与稳定前缀

| 片段 | 位置 | 作用 |
| --- | --- | --- |
| 4 个模拟面试 persona | `mock_interview_service.py:35-52` | 改变面试官风格 |
| 模拟面试稳定前缀 | `mock_interview_service.py:85-105` | 注入简历、JD、persona，影响缓存 |
| Agent autocompact wrapper | `context_compactor.py:221-225` | 将摘要标记为只读参考 |
| RAG chunk 标签 | `context_assembly_pipeline.py:348-354` | 生成 `[K#]` 引用标识 |
| debrief reference | `services/chat/interview_reference.py` | 长期注入面试摘要、QA 索引、简历 |
| memory render | `services/memory/v3_context_loader.py` | 将长期记忆注入聊天 |

### 4.4 非业务与评测 Prompt

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| 模型连通性 ping | `backend/app/api/model_runtime.py:165-170` | user message 固定为 `ping`，不是业务 prompt |
| RAG 评测回答 prompt | `evaluation/runners.py:198-203` | 严格基于参考资料回答，用于生成质量评测 |
| 开发工具配置 | `.claude/settings.local.json` | 未发现业务 prompt |
| 前端 | `frontend/` | 未发现生成型 prompt；仅有 prompt token 展示和 memory 注入开关文案 |

## 5. 动态输入来源清单

统一管理不能只管理固定文本，还必须登记每个 prompt 可以接收哪些动态数据：

| 动态来源 | 进入的主要 prompt | 信任级别 |
| --- | --- | --- |
| 用户当前消息 | P01-P05、P13-P15 | 不可信 |
| 最近对话 / 历史消息 | P01-P05、P13-P15 | 不可信，可能包含旧工具结果 |
| 用户画像 / 学习策略 / 能力状态 | P01-P04、P06、P14-P15 | 半可信，部分由 LLM 生成 |
| RAG 知识 chunk | P02-P03 | 不可信，来源可能是上传文档或外部内容 |
| 简历全文 | P03、P05、P08-P12 | 不可信 |
| JD 全文 | P03、P05、P10-P12 | 不可信 |
| ASR 转录 | P07、P09 | 不可信 |
| 面试分析结果 | P07、P11-P12、P15 | 半可信，由 LLM 生成 |
| 网页与工具结果 | P03 | 不可信 |
| 工具 schema / manifest | P03 | 可信代码配置 |

## 6. 主要问题与风险

### P0：不可信内容进入高权限上下文

- L1 Chat / RAG 使用单字符串 `acomplete` / `astream_complete`，system 规则和不可信内容只是按文本顺序拼接，没有 API role 隔离。
- L2 Agent 将 record、summary、memory、RAG 等共享上下文整体放进 `system` message；其中很多内容来自用户、上传文件、RAG 或其他 LLM。
- 简历、JD、转录、RAG chunk、网页和工具结果多数直接插值，没有统一的不可信内容包裹协议。
- `dreaming_worker.py` 的换行压平只能阻止部分格式伪装，不能阻止自然语言层面的指令注入。

建议：

- 为所有动态数据使用统一的 `UNTRUSTED_DATA` 边界说明。
- 在 Agent system prompt 中明确：record / memory / RAG / tool result 是数据，不得作为指令执行。
- 工具调用前继续依赖代码层权限、SSRF、参数校验和 allowlist，不能只靠 prompt。

### P0：高影响 JSON Prompt 未统一使用结构化输出

以下 prompt 要求严格 JSON，但调用没有显式 `response_format={"type": "json_object"}`：

- P07 面试记录浓缩摘要
- P10 单题深度分析
- P11 Mock 批量评分
- P12 全局复盘综合报告

这些结果会进入数据库、后续分析或长期上下文。建议统一结构化输出，并使用 Pydantic schema 做严格校验和可观测的 fallback。

### P1：固定 prompt 分散，缺少稳定 ID 和版本

- prompt 位于多个业务文件，命名不统一。
- 部分是模块常量，部分是函数内 f-string。
- LangSmith 能看到完整 prompt，但无法稳定按业务 prompt 版本聚合质量。
- 无法快速回答“某次结果使用了哪个 prompt 版本”。

### P1：Prompt 与输出 schema 重复维护

- JSON schema 多数直接写在 prompt 文本里，同时解析逻辑在代码中另写一份。
- 字段变化容易造成 prompt、解析器、前端契约不同步。
- P08 明确要求 JSON 数组，但调用要求 `json_object`，已经出现协议偏差。

### P1：RAG 回答约束不足

当前 P02 规则过薄，源码未落实设计文档中的 `[K#]` 引用、证据不足处理和来源边界规则。统一管理后应把 RAG prompt 作为首个重点评测对象。

### P1：核心评分口径写死且缺少版本追踪

P10-P12 中的评分维度、成长口径、雷达维度会直接影响产品结果，但目前没有版本、变更记录或历史结果关联。

### P2：语言与风格不统一

- L1 Chat / RAG prompt 使用英文。
- Agent、分析、记忆 prompt 主要使用中文。
- 多个分析 prompt 重复“全部输出简体中文”的硬性约束。

语言本身不是错误，但应明确每个 prompt 的语言策略并减少重复规则漂移。

### P2：测试覆盖不均衡

已有较好覆盖：

- Query Planner 的组装顺序、隐私开关和 fallback。
- 共享上下文槽位顺序。
- Agent manifest 与 system block 顺序。
- 模拟面试稳定前缀。
- 记忆 pipeline、压缩和能力诊断的部分流程。

明显薄弱：

- `interview_analysis_service.py` 的 P09-P12 未发现对应 prompt 契约测试。
- 缺少固定 prompt 快照 / 变量完整性测试。
- 缺少 prompt injection 回归集。
- 缺少 prompt 版本与离线评测结果的关联。

## 7. 统一管理目标架构

不建议第一步就把所有 prompt 存进数据库并提供在线编辑。更适合当前项目的是“代码托管、统一登记、类型安全渲染、可追踪版本”。

建议目录：

```text
backend/app/prompts/
  __init__.py
  registry.py
  chat.py
  agent.py
  planner.py
  interview.py
  analysis.py
  memory.py
  resume.py
```

建议每个 prompt 定义包含：

```python
PromptSpec(
    id="interview.analysis.batch_score",
    version="1.0.0",
    owner="interview-analysis",
    model_role="primary",
    template=...,
    input_model=BatchScoreInput,
    output_model=BatchScoreOutput,
    output_mode="json_object",
    risk="high",
    eval_suite="interview_analysis",
)
```

边界原则：

- `PromptSpec` 管理固定指令、变量契约、输出契约和元数据。
- 业务 service 继续负责取数、权限、裁剪和 fallback。
- `context_assembly_pipeline.py` 继续负责槽位顺序和 token budget。
- Agent 工具描述继续跟工具代码放在一起，但必须登记版本并纳入审计。
- 不把 prompt cache 做成额外缓存层；稳定前缀仍由现有代码设计保证。

## 8. 推荐迁移顺序

### 第一阶段：建立清单与调用可观测性

1. 给 P01-P15 分配稳定 `prompt_id` 和初始版本。
2. 在所有 LLM trace 中附加 `prompt_id`、`prompt_version`、`model_role`、`output_mode`。
3. 增加静态检查：新增 `.acomplete()`、`.astream_complete()`、`chat.completions.create()` 时必须声明 prompt ID 或标记为非业务调用。

### 第二阶段：先治理高风险结构化 Prompt

优先迁移：

1. P07 面试记录浓缩摘要
2. P10 单题分析
3. P11 批量评分
4. P12 综合报告
5. P14-P15 长期记忆写入

原因：这些输出会写数据库、形成评分或再次进入未来 prompt。

工作内容：

- 使用 Pydantic 输出模型生成 schema。
- 统一结构化输出参数。
- 记录解析失败、fallback、空输出和字段修复率。
- 建立小规模 golden cases。

### 第三阶段：治理用户回答与 Agent 安全边界

1. 完成 P02 RAG 规则升级和引用评测。
2. 给共享上下文槽位增加统一的不可信数据边界。
3. 给 P03 Agent 增加数据与指令隔离规则。
4. 将工具描述和参数描述纳入版本 diff 与 review。

### 第四阶段：集中固定模板

- 按领域迁入 `backend/app/prompts/`。
- 保留 prompt 与业务 owner 的对应关系，避免形成一个无人维护的巨型 `prompts.py`。
- 为每个模板增加变量完整性测试和渲染快照测试。

### 第五阶段：再决定是否需要在线管理

只有出现以下明确需求时才考虑数据库 / UI Prompt Manager：

- 非开发人员需要调整 prompt。
- 需要灰度、A/B、快速回滚。
- 需要按租户或环境覆盖。

如果启用在线管理，必须具备版本不可变、审批、回滚、权限、审计日志、变量校验和离线评测门禁；Agent system prompt、工具 schema 和安全边界不应允许普通运营角色直接编辑。

## 9. 建议的 Prompt ID

| 当前 ID | 建议稳定 ID |
| --- | --- |
| P01 | `chat.direct.answer` |
| P02 | `chat.rag.answer` |
| P03 | `agent.execute.system` |
| P04 | `planner.query.route_and_rewrite` |
| P05 | `interview.mock.next_turn` |
| P06 | `analytics.ability_diagnosis` |
| P07 | `interview.debrief.summary` |
| P08 | `resume.parse.sections` |
| P09 | `interview.transcript.extract_qa` |
| P10 | `interview.analysis.single_question` |
| P11 | `interview.analysis.batch_score` |
| P12 | `interview.analysis.synthesis` |
| P13 | `memory.conversation.compact` |
| P14 | `memory.realtime.extract` |
| P15 | `memory.dreaming.consolidate` |

建议对附属资产另外登记：

- `agent.tools.manifest`
- `interview.mock.persona.{style}`
- `context.chat.slot_order`
- `agent.context.autocompact_wrapper`
- `evaluation.rag.answer`

## 10. 验收标准

完成统一管理后，应能快速回答：

1. 当前生产环境有哪些 prompt，分别由谁负责？
2. 某一次模型调用使用了哪个 prompt ID、版本和模型角色？
3. 某个 prompt 接收哪些动态数据，哪些数据不可信？
4. 输出 schema 是什么，解析失败率是多少？
5. 修改 prompt 后，哪些测试和评测必须通过？
6. 某次评分或长期记忆是由哪个 prompt 版本生成的？
7. Agent 新增或修改工具描述时，是否经过 prompt 行为评审？

## 11. 最优先行动项

1. 为 P01-P15 建立 `PromptSpec` 元数据和 trace 标签，不改变现有文案。
2. 修复 P07、P10、P11、P12 的结构化输出契约。
3. 落实 P02 的 RAG 引用与证据不足规则，并接入现有 evaluation。
4. 为共享上下文和 Agent 增加统一的不可信数据边界。
5. 给 P09-P12 增加 prompt 契约测试与 golden cases。

