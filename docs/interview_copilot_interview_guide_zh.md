# Interview Copilot 面试官讲解指南

本文用于面试答辩。它不是 README，也不是源码注释，而是帮助你把项目讲清楚、讲完整、能扛追问的一份讲解稿。

---

## 1. 一句话介绍

Interview Copilot 是一个面向技术面试准备的 AI 后端系统，覆盖面试录音上传、异步转写分析、知识库问答、长期记忆、多轮复盘、岗位检索与准备建议。它不是简单 ChatBot，而是一个 RAG（Retrieval-Augmented Generation，检索增强生成）+ Memory（记忆）+ ReAct Agent（推理-行动智能体）+ Async Worker（异步任务）的完整工程闭环。

可以这样开场：

> 我做的是一个面向技术面试准备的 AI 面试辅助系统。它把面试录音分析、多轮知识问答、长期记忆、错题沉淀、岗位准备和工具型 Agent 串成闭环。普通问答走确定性 RAG pipeline，复杂岗位任务走独立 ReAct Agent，录音转写和文档摄取走 Celery 后台任务，整体目标是让候选人的面试准备可复盘、可沉淀、可持续优化。

---

## 2. 推荐讲解顺序

### 2.1 先讲业务闭环

不要一开始就堆技术名词。先讲用户如何使用：

1. 用户上传面试录音。
2. 系统把音频放到 MinIO/S3。
3. Celery Worker 后台执行 WhisperX 转写和说话人分离。
4. LLM 抽取问答对、评分、反馈和改进答案。
5. 用户把错题或改进答案沉淀回知识库。
6. 后续多轮问答会结合知识库、长期记忆和当前状态继续复盘。

核心表达：

> 它不是单点功能，而是把面试练习到复盘再到下一轮准备连起来。

### 2.2 再讲双链路架构

系统有两条主要链路：

1. 普通多轮问答链路：deterministic workflow（确定性工作流）。
2. 复杂任务链路：ReAct Agent（推理-行动智能体）。

为什么拆开：

- 普通问答更看重稳定、低延迟、可控。
- 岗位检索、岗位详情、结合用户画像做准备建议等任务需要工具调用和多步执行。
- 所以简单问题不交给自由式 Agent，避免延迟和不确定性。

### 2.3 再讲上下文和记忆

重点强调：

> 我没有把历史消息直接拼进 prompt，而是做了上下文流水线。

系统会将上下文分成：

- Raw Transcript（原始对话记录）
- Working State（工作状态）
- Interview State（面试状态）
- Long-term Memory（长期记忆）
- Retrieved Knowledge（检索知识）
- Recent Turns（近期对话）

然后由 `ContextBundle` 结构化承载，再由 `PromptRenderer` 最后渲染成提示词。

### 2.4 再讲 RAG

RAG 链路可以概括为：

- 摄取阶段：解析文档、按类型切块、写入 Milvus 和 PostgreSQL Docstore。
- 检索阶段：Milvus 向量检索 + BM25 词法检索 + RRF 融合 + BGE Reranker 重排 + 分数阈值拦截。

核心表达：

> 我没有只做纯向量检索，因为面试题里很多内容强依赖关键词，比如框架名、协议名、函数名和概念名。Dense retrieval 负责语义相似，BM25 负责词面命中，Reranker 负责最终排序。

### 2.5 最后讲安全、稳定性和评测

可以从这些点收口：

- JWT 鉴权。
- RAG 和记忆都按 `user_id` 隔离。
- Agent 工具有 Pydantic 参数校验、工具调用次数限制、超时和预算熔断。
- Agent Trace 全量落库。
- 后端测试通过 `60 passed`。
- RAG 和 Agent 分别有评测脚本。

---

## 3. 项目整体实现

### 3.1 API 层

目录：`backend/app/api/`

包括：

- `auth.py`：注册、登录、JWT 鉴权。
- `chat.py`：会话管理、历史记录、WebSocket/SSE 流式聊天、长期记忆 API。
- `interview.py`：音频上传、面试分析任务、复盘结果保存。
- `rag_api.py`：文档上传、文档摄取、RAG 查询。
- `agent.py`：普通 chat 和 ReAct Agent API。
- `model_runtime.py`：运行时模型选择。

讲法：

> API 层只负责鉴权、参数校验、接口暴露和任务派发，真正的业务逻辑下沉到 agent、rag 和 services。

### 3.2 普通多轮问答链路

入口：`backend/app/agent/agent_executor.py`

当前执行顺序：

1. `ensure_session()`：确保会话存在。
2. `ensure_state()`：确保面试状态存在。
3. `assemble_rewrite_context()`：读取轻量上下文。
4. `plan_query()`：生成查询计划。
5. 并发召回长期记忆和知识库。
6. `assemble_answer_context()`：生成结构化上下文。
7. `PromptRenderer` 渲染最终 prompt。
8. 选择 fast LLM 或 primary LLM 生成答案。
9. `append_turn()` 写入原始对话。
10. 异步执行 `post_turn_maintenance_service.run()`。

可以强调：

> 这条链路不是黑盒 Agent，而是明确阶段化的 pipeline。每一步都能观察、测试和优化。

### 3.3 Query Planner

文件：`backend/app/agent/planner.py`

`QueryPlan` 一次性完成：

- 多轮指代消解。
- dense query（向量检索查询）生成。
- sparse query（关键词检索查询）生成。
- 判断是否需要长期记忆。
- 判断需要哪些记忆类型。
- 判断是否需要知识库。
- 判断需要哪些知识源。
- 判断回答模式。

这比旧式 `rewriter + router` 更集中，减少多个模型节点各自猜意图导致的不一致。

### 3.4 上下文 Pipeline

文件：`backend/app/services/context_service.py`

核心对象：

- `ContextBundle`：结构化上下文包。
- `TokenBudgeter`：上下文 token 预算器。
- `PromptRenderer`：提示词渲染器。
- `ContextAssemblyPipeline`：上下文收集、清洗、截断、修复、组装。

讲法：

> 先结构化，后渲染。这样比一开始就拼字符串更容易做预算、排序、去重、来源标注和测试。

### 3.5 长期记忆链路

文件：

- `backend/app/models/memory.py`
- `backend/app/services/memory_extraction_service.py`
- `backend/app/services/memory_vector_service.py`
- `backend/app/rag/hybrid.py`

长期记忆类型：

- `user_profile`：用户画像。
- `interaction_preference`：交互偏好。
- `feedback_rule`：反馈规则。
- `project_reference`：项目背景。

写入逻辑：

1. 每轮后读取 `memory_cursor` 之后的新消息。
2. LLM 抽取 durable memories（持久记忆）。
3. 过滤非法类型和低置信度条目。
4. 用 `user_id + type + normalized_key` 合并。
5. 写入 PostgreSQL。
6. 同步写入独立 Milvus 记忆 collection。

召回逻辑：

- 向量召回：从 `interview_copilot_memory` collection 检索。
- 词法召回：从 `MemoryItem` 表做候选和关键词覆盖。
- `HybridRetriever` 融合排序。

### 3.6 RAG 链路

文件：

- `backend/app/rag/ingestion.py`
- `backend/app/rag/retriever.py`
- `backend/app/rag/knowledge_retriever.py`
- `backend/app/rag/embeddings.py`

摄取：

- Markdown 使用 `MarkdownNodeParser`。
- JSON 使用 `JSONNodeParser`。
- Python/Java/C/C++ 使用 `CodeSplitter`。
- 普通文本使用 `SentenceSplitter`。
- PDF/PPTX/DOCX 可选 LlamaParse，否则 PDF 用 PyMuPDF。

检索：

1. Milvus dense retrieval（向量检索）。
2. PostgreSQL Docstore 构建 BM25。
3. QueryFusionRetriever 做 RRF 融合。
4. BGE Reranker 做重排。
5. 分数阈值过滤。
6. 返回 `context_text`、`chunks`、`sources`。

### 3.7 ReAct Agent 链路

入口：`backend/app/agent_runtime/react_agent.py`

工具定义：`backend/app/agent_runtime/tools.py`

默认工具：

- `search_jobs`
- `fetch_job_detail`
- `get_user_profile`
- `search_interview_qa`

执行过程：

1. planner 生成任务计划。
2. 读取相关上下文和长期记忆。
3. 渲染工具清单和 agent prompt。
4. LLM 返回 tool_calls。
5. 系统校验参数并执行工具。
6. observation 回传模型。
7. 循环直到最终答案或预算熔断。
8. 写入 Agent Trace。

重要边界：

> ReAct 默认读取相关记忆，但默认不自动写长期记忆。只有 planner 判定为 `interview_learning`、`review`、`preference_update` 时才允许写入。

### 3.8 音频分析链路

文件：

- `backend/app/api/interview.py`
- `backend/app/worker/tasks.py`
- `backend/app/services/transcription_service.py`
- `backend/app/services/analysis_service.py`

流程：

1. 前端上传音频到 MinIO/S3。
2. `/analyze` 创建 `Interview(status=PENDING)`。
3. Celery 执行 `process_interview_analysis()`。
4. 状态变为 `TRANSCRIBING`。
5. WhisperX 转写，说话人分离。
6. 状态变为 `ANALYZING`。
7. LLM 抽取问答、评分、反馈、改进答案。
8. 写入 `Transcript` 和 `AnalysisResult`。
9. 状态变为 `COMPLETED` 或 `FAILED`。

---

## 4. 技术选型横向对比

### 4.1 FastAPI vs Flask vs Django

选择 FastAPI 的原因：

- 原生支持 async/await，适合流式聊天和异步 I/O。
- WebSocket 和 SSE 支持自然。
- Pydantic 参数校验和 OpenAPI 文档自动生成，适合复杂 API。
- 依赖注入适合 JWT 鉴权和 DB session 管理。

Flask 更轻，但异步和类型校验不如 FastAPI 顺手。Django 全家桶强，但本项目不需要重型后台管理和 ORM 生态。

### 4.2 LlamaIndex vs LangChain

选择 LlamaIndex 的原因：

- 项目核心是文档摄取、节点切分、向量索引、Docstore 和检索融合。
- LlamaIndex 在 RAG 数据层抽象更贴合。
- 主问答链路不希望过度 Agent 化，所以没有把 LangChain 当主编排框架。

LangChain 更适合复杂链式编排和 Agent 生态，但本项目的稳定问答链路更适合显式 pipeline。

### 4.3 Milvus vs FAISS vs Chroma vs pgvector

选择 Milvus 的原因：

- 它是服务化向量数据库，适合独立部署和扩展。
- HNSW 索引参数清晰。
- 能把高维向量检索和业务关系数据解耦。

FAISS 更适合本地实验。Chroma 开发体验轻但生产隔离和扩展能力较弱。pgvector 部署简单，但向量检索和业务库耦合更高。

### 4.4 Celery vs FastAPI BackgroundTasks

选择 Celery 的原因：

- 音频转写、说话人分离、文档解析、embedding、LLM 分析都是长任务。
- Celery 有独立 worker、broker、result backend、失败状态和进程隔离。
- BackgroundTasks 更适合短小后台动作，不适合长时间重计算。

### 4.5 WhisperX vs Whisper

选择 WhisperX 的原因：

- 支持更好的时间戳对齐。
- 更适合长音频和后续分段处理。
- 可以结合 pyannote 做 diarization（说话人分离）。

基础 Whisper 可以转文字，但对面试场景中的“谁问、谁答、何时切换”支持不够。

### 4.6 混合检索 vs 纯向量检索

选择混合检索的原因：

- 面试题里大量术语强依赖关键词，如 Redis、MVCC、CAP、B+ Tree。
- 向量检索擅长语义相似，但可能漏掉精确术语。
- BM25 擅长词面匹配，但不理解语义相近表达。
- Reranker 能对粗召回结果重新排序。

组合后比单一路径稳定。

### 4.7 云端 LLM vs 本地 LLM

当前使用 DeepSeek/OpenAI-compatible LLM 的原因：

- 推理质量更稳定。
- function calling 能力更成熟。
- 适合快速验证复杂 agent 和 RAG 链路。

项目通过 model registry 把模型按角色分成：

- `primary`
- `fast`
- `agent`

这让后续切换本地模型或其他供应商更容易。

---

## 5. 常见追问答法

### 5.1 为什么普通问答不用 ReAct Agent？

普通面试问答更看重稳定、低延迟和可控性，所以做成显式阶段的 deterministic workflow。只有岗位检索、职位详情、结合用户画像做准备建议这类复合任务，才走 ReAct Agent。

### 5.2 为什么要同时有 Working State 和 Interview State？

Working State 面向 prompt 组织和当前协作状态，Interview State 面向面试过程管理，比如 covered topics、observed gaps、candidate claims、next question。两者职责不同，拆开后更容易控制漂移，也方便后续评测和 UI 展示。

### 5.3 长期记忆为什么不用全量注入？

全量注入浪费 token，也容易把无关偏好带入回答。当前做法是 vector + lexical hybrid recall（向量和词法混合召回），最多注入少量相关 memory，并维护 recall_count、confidence、importance 和 last_evidence_seq。

### 5.4 RAG 怎么降低幻觉？

第一，多租户和 source_type 过滤保证检索边界。第二，dense + BM25 提高召回。第三，reranker 提升排序质量。第四，`RAG_MIN_SCORE` 分数闸门低于阈值就返回空知识提示，不让模型硬编。

### 5.5 Agent 工具调用怎么防失控？

工具参数用 Pydantic schema 校验；限制 `AGENT_MAX_STEPS`、`AGENT_MAX_TOOL_CALLS`、`AGENT_MAX_CALLS_PER_TOOL`、`AGENT_MAX_TOTAL_TOKENS`、`AGENT_MAX_RUNTIME_SECONDS`；每次执行都有 timeout；所有 step 写入 Agent Trace。

### 5.6 项目最体现工程能力的地方是什么？

可以这样答：

> 我不是只接了几个模型 API，而是把 RAG、长期记忆、多轮上下文、异步转写、工具型 Agent、安全边界、评测和部署组织成了一套可运行、可追踪、可优化的后端系统。项目的难点在于边界设计，而不是单点模型调用。

---

## 6. 面试时可以主动强调的亮点

1. **双链路设计**：普通问答和 ReAct Agent 分离，兼顾稳定性和复杂任务能力。
2. **结构化上下文**：通过 `ContextBundle` 和 `PromptRenderer` 管理 prompt，而不是简单拼接历史。
3. **长期记忆向量化**：记忆单独使用 Milvus collection，并结合词法召回和重要性排序。
4. **混合 RAG 检索**：Milvus + BM25 + RRF + Reranker + score gate。
5. **异步音频分析**：Celery Worker 承担重任务，API 不阻塞。
6. **多租户隔离**：RAG、记忆、Agent trace 都按 `user_id` 过滤。
7. **工具治理**：ReAct 工具有 schema 校验、超时、预算熔断和 trace。
8. **测试覆盖**：后端测试已覆盖 API、RAG scope、context pipeline、memory pipeline、agent runtime、trace、storage、telemetry。

---

## 7. 如果被要求现场画架构

建议画成五块：

```text
用户 / 前端
  |
FastAPI API 层
  |
  |-- 普通 Chat Pipeline
  |     |-- Query Planner
  |     |-- ContextBundle / PromptRenderer
  |     |-- Memory Retriever
  |     |-- Knowledge Retriever
  |
  |-- ReAct Agent Pipeline
  |     |-- Tool Schema
  |     |-- Tool Loop
  |     |-- Agent Trace
  |
  |-- Interview Analysis Pipeline
        |-- Celery Worker
        |-- WhisperX / Diarization
        |-- LLM Analysis

PostgreSQL / Milvus / Redis / MinIO
```

讲解时按“输入进入哪条链路、链路怎么组织上下文、数据存在哪里、如何保证稳定”展开即可。

---

## 8. 收尾表达

最后可以这样总结：

> 这个项目最核心的是把 LLM 能力工程化。我没有把模型当成黑盒聊天接口，而是围绕面试准备这个场景，把 RAG、长期记忆、多轮上下文、工具调用、异步任务、安全隔离和评测组合起来。它既能回答面试问题，也能沉淀用户长期画像，并且对复杂岗位准备任务提供可追踪的工具执行过程。
