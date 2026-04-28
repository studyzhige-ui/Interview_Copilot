# Interview Copilot 面试讲解指南

本文不是源码注释，也不是 README，而是一份专门给面试答辩准备的项目讲解稿。
它的目标不是让你背概念，而是帮你把当前这版代码真正落地的设计讲顺、讲稳、讲得能扛追问。

当前这份指南基于项目最新代码整理，已经和这轮实现保持一致，尤其对齐了这些关键变化：

- `working_state` 已经从自由文本变成结构化 JSON
- 会话新增 `memory_cursor`，长期记忆维护改为增量处理
- 新增 `InterviewState` 作为独立状态层
- 长期记忆新增 `normalized_key / confidence / last_evidence_seq`
- ReAct Agent 已接入预算熔断、工具参数校验和运行轨迹
- 当前自动化测试结果为 `51 passed, 1 warning`

---

## 1. 一句话怎么介绍这个项目

如果面试官让你先快速介绍项目，可以这样说：

> 我做的是一个面向求职场景的 AI 面试辅助系统，不只是做单轮问答，而是把面试录音上传、离线转写分析、知识增强问答、错题沉淀、多轮复盘和岗位选择准备串成了一个闭环，目标是提升候选人的准备效率和回答质量。

如果面试官让你再展开一点，可以继续补：

> 这个系统有两条核心能力链路。一条是音频分析链路，用户上传录音后，系统会走对象存储、Celery Worker、WhisperX 和说话人分离去完成转写、问答对抽取和面试分析。另一条是在线复盘问答链路，系统会结合知识库、多轮上下文、working state 和长期记忆进行问答。对于岗位准备这种更复杂的任务，再单独切到 ReAct Agent 链路。

---

## 2. 怎么讲整体架构

面试里最容易讲乱的地方，是一上来就堆技术名词。
更好的方式是按“业务闭环 -> 双链路 -> 核心机制 -> 指标验证”来讲。

### 2.1 业务闭环

先说清楚，这不是一个普通聊天机器人，而是一个面试准备平台：

- 录音采集
- 转写与分析
- 错题回流
- 知识增强问答
- 多轮复盘
- 岗位检索与准备

### 2.2 双链路设计

然后说清楚，系统内部不是一条大链路，而是两条不同优化目标的链路：

1. 主问答链路：确定性工作流
2. 复杂任务链路：ReAct Agent

主问答链路重：

- 稳定性
- 延迟
- 可控性

ReAct Agent 链路重：

- 多步工具调用
- 任务分解
- 工具执行与中间状态推进

### 2.3 核心技术机制

这部分可以归纳成四件事：

1. 文档摄取与混合检索
2. 分层记忆与状态管理
3. 异步音频分析
4. 工具型 Agent 的安全控制

### 2.4 指标验证

最后再用结果收口：

- 检索指标
- RAGAS 指标
- 检索延迟
- 端到端响应时间
- 当前测试通过情况

---

## 3. 当前系统架构，按层怎么拆

你可以把当前实现拆成六层。

### 3.1 API 层

目录：`backend/app/api/`

主要路由：

- `auth.py`
- `chat.py`
- `interview.py`
- `rag_api.py`
- `agent.py`
- `model_runtime.py`

职责：

- 对外暴露 HTTP / WebSocket / SSE 接口
- 鉴权
- 参数校验
- 组织主链路和异步任务入口

### 3.2 主问答工作流层

目录：`backend/app/agent/`

核心文件：

- `agent_executor.py`
- `rewriter.py`
- `router.py`
- `tools.py`

职责：

- 多轮上下文装配
- query rewrite
- intent router
- 多源并发检索
- 最终问答生成

### 3.3 ReAct Agent 层

目录：`backend/app/agent_runtime/`

核心文件：

- `react_agent.py`
- `tools.py`

职责：

- Function Calling
- 工具注册与 schema
- 预算熔断
- 工具执行
- Trace 持久化

### 3.4 服务层

目录：`backend/app/services/`

当前比较关键的服务有：

- `transcript_service.py`
- `context_service.py`
- `memory_extraction_service.py`
- `interview_state_service.py`
- `storage_service.py`
- `transcription_service.py`
- `analysis_service.py`
- `analytics_service.py`
- `telemetry_service.py`

### 3.5 RAG 层

目录：`backend/app/rag/`

核心文件：

- `ingestion.py`
- `retriever.py`
- `embeddings.py`

职责：

- 文档解析
- 自适应切分
- 向量化
- Milvus 检索
- BM25 检索
- rerank
- score gate

### 3.6 数据与异步层

当前存储和异步组件包括：

- PostgreSQL
- Milvus
- Redis
- MinIO / S3
- Celery

其中：

- PostgreSQL：业务数据、状态、memory items、agent trace、docstore
- Milvus：向量检索
- Redis：Broker / 缓存
- MinIO / S3：音频和文件
- Celery：离线任务执行

---

## 4. 主问答链路怎么讲

这条链路是当前系统的核心。

入口在 [agent_executor.py](D:/Projects/Python/Interview_Copilot/backend/app/agent/agent_executor.py) 的 `stream_chat_with_agent()`。

### 4.1 当前执行顺序

可以按下面这 10 步讲：

1. 确保会话存在
2. 召回长期记忆
3. 组装会话上下文
4. 对当前 query 做 rewrite
5. 做 intent router
6. 如果需要检索，就并发查多个知识源
7. 汇总各知识源结果
8. 构造最终 prompt 并生成答案
9. 同步写 raw transcript
10. 异步做 post-turn maintenance

### 4.2 为什么这条链路不是 Agent

你可以这样答：

> 因为普通问答更需要稳定、低延迟和可控性，而不是让模型自由试错。我把它做成固定阶段的确定性工作流，每一步职责都很明确，这样链路更容易调优，也更容易排查问题。只有真正需要多步工具调用的复杂任务，我才交给 ReAct Agent。

### 4.3 query rewrite 在这里解决什么问题

它解决的是多轮对话里的代词、省略和不完整 query 问题。
比如“那这个底层原理呢”这种句子，对人来说有上下文，但对检索器来说不够明确。

rewrite 的作用就是把当前轮问题改写成更适合检索的 standalone query。

### 4.4 intent router 在这里的价值是什么

router 不是为了显得高级，而是为了减少不必要的检索和错误的知识源选择。

它决定的是：

- 这次问题需不需要检索
- 要检索哪些 source
- 搜索关键词应该是什么

### 4.5 多源检索为什么要并发

因为一个问题经常要同时参考多个知识域，比如：

- 题库
- 官方资料
- 个人错题

如果串行查，延迟会线性叠加。并发检索的核心价值不是语法，而是减少主链路总时延。

---

## 5. 分层记忆怎么讲

这是当前系统最值得讲清楚的设计之一。

你可以把它拆成四层。

### 5.1 Layer 1：Raw Transcript

入口：`TranscriptService`

它的职责非常克制：

- 只做 append-only 写入
- 只做读取
- 不做总结
- 不做压缩

它是整个系统的唯一事实源。

当前一轮对话会写两条消息：

- `User`
- `Agent`

并通过 `seq` 保证顺序。

这层的意义是：

- 历史可回放
- 问题可审计
- 后续任何 summary / memory / state 都可以从原始层重建

### 5.2 Layer 2：Context Assembly Pipeline

入口：`ContextAssemblyPipeline`

它不是简单 `history + query` 拼接，而是四步：

1. `sanitize`
2. `truncate`
3. `repair`
4. `assemble`

它的目标是把 transcript 变成“模型可消费上下文”，而不是原样复读数据库内容。

#### sanitize

做的事情：

- 去空消息
- 只保留 `User / Agent`
- 去掉 `[SYSTEM_]`、`[DEBUG_]` 之类内部标记

#### truncate

做的事情：

- 按 token budget 从后往前累计
- 优先保留最新消息

默认 recent turns 预算是 `4000 token`。

#### repair

做的事情：

- 如果截断后第一条是 `Agent`，删掉
- 如果最后一条是 `User`，删掉

这是为了避免把结构断裂的对话喂给模型。

#### assemble

最终拼装顺序是：

1. `working_state`
2. `relevant_memories`
3. `recent_turns`

这意味着 prompt 里先放相对稳定的状态，再放动态记忆和近期细节。

### 5.3 Layer 3：Working State / Compaction

当前这层已经不是旧版那种自然语言 summary，而是结构化 JSON。

字段包括：

- `goal`
- `current_phase`
- `covered_topics`
- `pending_topics`
- `candidate_claims_to_verify`
- `observed_gaps`
- `next_best_question`
- `constraints`
- `summary`

#### 它什么时候更新

不是每轮都更新，而是在：

- `working_state`
- 加上 `compaction_cursor` 之后的 recent transcript

总 token 超过 `5000` 时触发 compaction。

#### 它怎么压缩

当前实现会：

- 保留最近 `6` 条消息不压
- 把更早的部分合并进新的 `working_state`
- 更新 `compaction_cursor`

所以当前 `working_state` 的角色更接近：

> 已经被折叠过的历史工作状态摘要

而不是“当前轮全部状态的唯一载体”。
当前真实会话状态实际上由两部分共同构成：

- `working_state`
- `recent_turns`

这是你在面试里可以讲得比较细的一点。

### 5.4 Layer 4：Long-term Memory

这层关注的是跨会话仍然有价值的信息，不是当前会话推进。

当前长期记忆允许的类型是：

- `user_profile`
- `interaction_preference`
- `feedback_rule`
- `project_reference`

也就是说，它存的是：

- 用户画像
- 交互偏好
- 稳定反馈规则
- 项目背景参考

而不是：

- 当前会话进度
- 临时分数
- 可从知识库直接检索到的技术知识

---

## 6. Interview State 是什么

这是这轮代码里一个很重要的新点。

以前比较容易把“会话状态”和“面试进度状态”混在一起，现在系统把它拆开了。

当前 `InterviewState` 维护的内容包括：

- `goal`
- `phase`
- `covered_topics`
- `pending_topics`
- `observed_gaps`
- `evidence`
- `candidate_claims`
- `next_question`
- `constraints`

这层和 `working_state` 的区别是：

- `working_state` 更偏 prompt 组织和协作状态
- `interview_state` 更偏面试过程跟踪和问题推进

面试时如果被追问“为什么要两个状态”，你可以这么答：

> 因为这两个状态的用途不同。working state 是给主问答链路组织上下文用的，更偏会话协作视角；interview state 更像面试过程状态机，关注已经覆盖了哪些 topic、发现了哪些 gap、下一步该问什么。拆开之后职责更清楚，也更方便后续各自演进。

---

## 7. 长期记忆写入与召回怎么讲

### 7.1 写入逻辑

当前长期记忆的写入已经从旧版“按 description 更新”进化成了“按 `normalized_key` 合并”。

流程是：

1. `post_turn_maintenance_service.run()` 读取 `memory_cursor` 之后的增量消息
2. 用这些消息更新 `interview_state`
3. 调 LLM 提取 durable memories
4. 只保留：
   - 合法 type
   - `confidence >= 0.65`
5. 对每条记忆生成或接收 `normalized_key`
6. 用：
   - `user_id`
   - `type`
   - `normalized_key`
   去查是否已有同类记忆
7. 如果有就更新，没有就新建
8. 成功后推进 `memory_cursor`

这比旧版的 `user_id + type + description` 精确匹配更稳。

### 7.2 为什么要有 `normalized_key`

因为 `description` 是语言层字段，很容易因为措辞变化而产生重复条目。
`normalized_key` 的作用就是让同类记忆有更稳定的归并依据。

### 7.3 新增的记忆字段有什么意义

当前 `MemoryItem` 新增这些字段后，长期记忆已经更像“受管控的数据对象”：

- `normalized_key`：归一化合并键
- `confidence`：抽取置信度
- `last_evidence_seq`：最后一次证据出现在哪条消息
- `recall_count`：被证明有用的次数

### 7.4 召回逻辑

当前召回是典型的 Active Recall 风格：

1. 先按 `recall_count desc, updated_at desc` 做预筛
2. 最多取 `12` 条候选
3. 把候选目录给快模型做选择
4. 最多选出 `3` 条
5. 注入时如果太长会截断到较短内容
6. 如果记忆太老，会附加 stale note

这说明当前设计不是“把所有长期记忆全贴进 prompt”，而是按需挑选。

---

## 8. RAG 链路怎么讲

### 8.1 文档摄取

入口在 `backend/app/rag/ingestion.py`。

当前摄取流程是：

1. 根据文件类型选择解析器
2. 生成 `Document`
3. 根据内容类型路由到不同切分器
4. 生成 nodes
5. 回填 `user_id/source_type`
6. 写入 Milvus 和 PostgresDocumentStore

支持的切分策略：

- Markdown：`MarkdownNodeParser`
- JSON：`JSONNodeParser`
- Python / Java / C++：`CodeSplitter`
- 其他：`SentenceSplitter(chunk_size=1024, chunk_overlap=100)`

如果配置了 `LLAMA_CLOUD_API_KEY`：

- PDF / PPTX / DOCX 会优先走 `LlamaParse`

否则 PDF 回退到 `PyMuPDFReader`。

### 8.2 混合检索

当前检索链路是：

1. Milvus 向量检索
2. BM25
3. Query Fusion Retriever 做 RRF 融合
4. BGE Reranker
5. `RAG_MIN_SCORE` 阈值拦截

### 8.3 为什么不是纯向量检索

你可以这么答：

> 面试场景里关键词强依赖问题很多，比如术语、框架名、概念名、函数名。如果只做 dense retrieval，对关键词敏感性不足；如果只做 BM25，又丢语义相似性。所以我做的是 dense + sparse + rerank 的组合链路，最后再加阈值拦截抑制低质量召回带来的幻觉。

### 8.4 多租户隔离

当前多租户隔离体现在两端：

- 摄取时 node metadata 强制写回 `user_id/source_type`
- 检索时 dense 和 BM25 两层都做过滤

这不是 UI 层面的逻辑，而是检索层面的真实约束。

---

## 9. ReAct Agent 怎么讲

当前复杂任务链路入口在 `backend/app/agent_runtime/react_agent.py`。

### 9.1 它适合什么任务

它不是普通问答的默认链路，而是用于：

- 岗位检索
- 岗位详情获取
- 结合用户画像做准备建议
- 多步工具调用任务

### 9.2 当前有哪些工具

默认工具包括：

- `search_jobs`
- `fetch_job_detail`
- `get_user_profile`
- `search_interview_qa`

### 9.3 工具安全控制怎么讲

当前工具不是让模型随便乱调，而是：

- 每个工具都有 Pydantic 参数模型
- 参数长度受 `AGENT_MAX_TOOL_ARG_CHARS` 限制
- schema 可以走 strict 模式
- 工具上下文由系统注入 `user_id/session_id`
- 工具有超时
- 单工具调用次数有限制

这就是你简历里“参数校验、工具权限控制、预算熔断”的真实落点。

### 9.4 预算熔断怎么讲

当前 `AgentBudget` 会检查：

- 最大步数
- 最大工具调用数
- token 总预算
- 总运行时长

一旦超限，就会：

- 写入 budget stop trace
- 停止 Agent
- 返回带 stop reason 的结果

### 9.5 为什么要记录 Agent Trace

因为工具型 Agent 最怕黑盒化。
当前系统会记录：

- run
- step
- tool args
- observation
- error
- latency

这样后续可以做：

- debug
- 回放
- 指标聚合
- 失败定位

---

## 10. 音频分析链路怎么讲

### 10.1 上传阶段

音频不是直接压给应用服务器，而是：

1. 先拿 presigned URL
2. 上传到 MinIO / S3
3. API 保存 `file_path`

这样可以避免主服务长时间承载大文件流。

### 10.2 分析阶段

`/analyze` 会：

1. 创建 `Interview(status=PENDING)`
2. 投递 `process_interview_analysis`

Worker 再执行：

1. 下载文件到临时路径
2. 转写
3. 进入分析阶段
4. 写入 `Transcript`
5. 写入 `AnalysisResult`
6. 更新 Interview 状态

### 10.3 为什么必须异步

因为音频分析链路包含：

- 大文件
- 转写
- 说话人分离
- LLM 分析

这类任务不适合留在主请求里做。

---

## 11. 这轮代码更新后，最值得你在面试里强调什么

如果你只讲最核心的变化，我建议你强调下面 6 点：

1. 主问答链路已经稳定成确定性工作流，而不是随意式 Agent。
2. `working_state` 已从文本摘要进化为结构化 JSON。
3. 新增 `InterviewState`，把会话工作状态和面试推进状态拆开管理。
4. 长期记忆现在通过 `memory_cursor` 做增量维护，并用 `normalized_key` 合并。
5. ReAct Agent 已具备参数校验、预算熔断和 trace。
6. 自动化测试当前是 `51 passed`，说明系统已经不是只靠手工跑通的 Demo。

---

## 12. 最后怎么收口

如果面试官问你“这个项目最能体现你什么能力”，你可以这样收：

> 我觉得这个项目最能体现的是，我不是把大模型当成一个黑盒接口去堆功能，而是围绕真实求职场景，把主问答、复杂任务、分层记忆、异步音频分析、混合检索和多租户隔离组织成了一套可运行、可调优、可审计的后端系统。尤其这轮更新之后，状态管理、长期记忆和工具型 Agent 的边界都更清楚了，系统化程度比之前更高。
