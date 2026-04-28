# Interview Copilot 面试问答手册

> 本文档基于当前项目代码重写，面向简历答辩、技术追问和系统设计问答。
> 校对范围覆盖 `backend/app/`、`backend/tests/` 与当前 API/服务实现。
> 当前自动化测试结果：`51 passed, 1 warning`。

---

## 1. 一句话介绍项目

### Q1：一句话介绍一下这个项目。

**A：** 这是一个面向求职场景的 AI 面试辅助系统，覆盖面试录音上传与转写分析、知识增强问答、错题沉淀、多轮复盘、岗位选择与准备等核心环节，目标是提升候选人的面试准备效率与回答质量。

### Q2：它和普通聊天机器人有什么本质区别？

**A：** 它不是单轮聊天，而是一个带有双链路 Agent、分层记忆、混合检索和异步音频分析的后端系统。

- 普通问答走确定性工作流主链路
- 复杂任务走独立 ReAct Agent 链路
- 会话历史不是简单拼接，而是经过 transcript、context pipeline、working state、long-term memory 四层管理
- 音频分析和文档摄取不阻塞主请求，而是通过 Celery Worker 离线执行

### Q3：这个项目最核心的业务价值是什么？

**A：** 它把原本零散的面试准备动作串成了闭环。

- 录音后可以自动转写、拆问答对、评分和生成反馈
- 错题和改进答案可以沉淀回知识库
- 后续问答能结合知识库、长期记忆和当前会话状态继续追问
- 岗位选择与准备可以通过工具调用拿到更具体的岗位信息和准备建议

---

## 2. 整体架构

### Q4：整体架构怎么拆？

**A：** 我把系统拆成六层。

1. API 层：FastAPI 路由，承接 Auth、Chat、Interview、RAG、Agent、Model Runtime。
2. 主问答链路：`app/agent/` 下的确定性工作流，负责多轮问答、记忆召回、RAG、流式回复。
3. 复杂任务链路：`app/agent_runtime/` 下的 ReAct Agent，负责 Function Calling 工具规划与执行。
4. 服务层：`app/services/`，包括 transcript、context、memory extraction、interview state、transcription、analysis、analytics、telemetry、storage。
5. RAG 引擎层：`app/rag/`，负责文档摄取、自适应切分、向量检索、BM25、rerank 和阈值拦截。
6. 数据层：PostgreSQL、Milvus、MinIO/S3、Redis。

### Q5：为什么要做双链路 Agent，而不是一个大 Agent 全包？

**A：** 因为两类任务的优化目标完全不同。

- 主问答链路重稳定性、低波动、低延迟，适合显式阶段化工作流
- 岗位准备、岗位检索这种复合任务需要工具调用和中间推理，更适合 ReAct Agent

如果把所有问题都交给自由式 Agent，会出现：

- 延迟波动大
- 工具调用成本高
- 排查困难
- 多步推理在简单问答场景里是浪费

---

## 3. 为什么选这些技术

### Q6：为什么选 FastAPI，而不是 Flask 或 Django？

**A：**

- 这个项目大量使用异步 I/O 和流式响应，FastAPI 原生适配 `async/await`
- 它对 HTTP 和 WebSocket 都很友好，当前 `chat` 同时支持 `/chat/ws/{session_id}` 和 `/chat/sse/{session_id}`
- 依赖注入机制适合统一处理 JWT 鉴权和数据库会话
- Pydantic 在 API 请求校验和 Agent 工具参数校验里都很好用

### Q7：为什么选 LlamaIndex，而不是 LangChain？

**A：** 因为当前项目的核心能力是文档摄取、节点切分、索引和检索，不是把所有能力堆成通用链式编排。

当前真正落地的能力主要是：

- `SimpleDirectoryReader`
- `MarkdownNodeParser / JSONNodeParser / CodeSplitter / SentenceSplitter`
- `VectorStoreIndex`
- `MilvusVectorStore`
- `PostgresDocumentStore`
- `QueryFusionRetriever`

也就是说，我更看重 LlamaIndex 在 RAG 底层抽象上的适配度，而不是它的 Agent 层。

### Q8：为什么选 Milvus，而不是 pgvector / FAISS / Chroma？

**A：**

- 这是一个服务化后端，不是单机脚本实验
- Milvus 更适合作为独立向量检索层
- 索引配置和检索参数比较清晰，当前用的是 `HNSW + IP`
- 业务数据和高维向量检索分层后，更容易分别调优和扩展

### Q9：为什么还保留 PostgreSQL，而不是让 Milvus 全包？

**A：** 因为 PostgreSQL 在这里承担的是关系型业务数据和节点元数据持久化，不只是聊天记录。

PostgreSQL 当前保存的核心数据包括：

- 用户、会话、消息 transcript
- working state / memory cursor / compaction cursor
- memory items
- interview / transcript / analysis result
- interview state
- agent run / agent step trace
- PostgresDocumentStore 节点持久化

Milvus 负责的是高维向量相似检索，两者职责不同。

### Q10：为什么音频分析要用 WhisperX + Pyannote？

**A：**

- WhisperX 相比基础 Whisper，更适合做带时间戳对齐的转写
- Pyannote 负责 speaker diarization，区分候选人与面试官
- 面试分析场景必须先把说话人区分清楚，否则后续问答对抽取和评分会很不稳定

### Q11：为什么音频分析和文档摄取都要走 Celery？

**A：**

- 两者都属于重计算任务
- 音频分析会占用较多 CPU/GPU 和较长时间
- 文档摄取涉及对象存储拉取、解析、切分、嵌入、入库
- 如果放在主请求里，会直接拖垮 API 响应时间

所以当前实现是：

- 文件先上传到 MinIO/S3
- API 只负责接收路径并投递任务
- Worker 独立下载、处理、更新状态

---

## 4. 文档摄取与索引构建

### Q12：你简历里写“完成多类知识源摄取”，具体指什么？

**A：** 指的是把题库、官方资料、个人错题等不同来源的内容统一走一条导入链路：

1. 解析文档
2. 根据内容类型做自适应切分
3. 生成 nodes
4. 写入 Milvus 向量库
5. 同步写入 PostgreSQL 版 Docstore

### Q13：自适应解析与切分怎么做？

**A：** 入口在 `backend/app/rag/ingestion.py` 的 `get_optimal_nodes()`。

- Markdown 或 `interview_qa / official_docs`：`MarkdownNodeParser`
- JSON：`JSONNodeParser`
- Python：`CodeSplitter(language="python")`
- Java：`CodeSplitter(language="java")`
- C / C++：`CodeSplitter(language="cpp")`
- 其他文本：`SentenceSplitter(chunk_size=1024, chunk_overlap=100)`

另外，如果配置了 `LLAMA_CLOUD_API_KEY`：

- PDF / PPTX / DOCX 会优先走 `LlamaParse`
- 结果按 Markdown 继续进入 Markdown 切分链路

否则 PDF 走 `PyMuPDFReader` 兜底。

### Q14：为什么不能所有文档统一固定长度切块？

**A：** 因为不同文档结构差异太大。

- Markdown 更适合按标题边界切
- JSON 更适合按结构切
- 代码更适合按函数 / 类边界切
- 普通长文本再退回句子滑窗

统一固定长度切块虽然简单，但会更容易破坏语义边界，影响检索质量。

### Q15：多用户隔离在摄取阶段怎么保证？

**A：** 切分完成后会强制把 `user_id` 和 `source_type` 回填到每个 node 的 metadata 上。

这是一个很重要的安全动作，因为 parser 过程中可能丢原始 metadata，不重新写回的话，后面的隔离过滤会失效。

---

## 5. 混合检索链路

### Q16：你为什么不是纯向量检索？

**A：** 因为面试场景里有很多关键词强依赖问题。

- 向量检索擅长语义相似
- BM25 擅长关键词精确命中
- 两者互补后再做 rerank，会比单一路径稳定

### Q17：当前检索链路具体怎么跑？

**A：**

1. 先在 Milvus 上做向量检索
2. 再从 PostgresDocumentStore 里读取节点，按 `user_id/source_type` 过滤后构建 BM25
3. 用 `QueryFusionRetriever(mode="reciprocal_rerank")` 做 RRF 融合
4. 用 `BGE Reranker` 做交叉重排
5. 用 `RAG_MIN_SCORE` 做绝对阈值拦截

### Q18：为什么 BM25 不是直接在数据库里做？

**A：** 当前实现里 BM25 不是依赖外部搜索引擎，而是直接基于 docstore 中过滤后的节点构建 `BM25Retriever`。
这样做的好处是：

- 检索逻辑都在 Python 和 LlamaIndex 这一层可控
- 可以精确配合 `user_id/source_type` 过滤
- 工程复杂度更低

代价是：如果数据规模继续扩大，BM25 这层未来可能要独立演化。

### Q19：为什么要加 reranker？

**A：** 因为前面的 dense retrieval 和 BM25 都是粗召回，目标是“别漏”。
最终真正决定喂给模型的上下文质量的，是候选结果谁更相关，所以用交叉编码器做二阶段重排。

### Q20：绝对阈值拦截解决什么问题？

**A：** 它是用来抑制幻觉的。

如果所有候选节点重排后得分都低于阈值，系统就返回 `[SYSTEM_EMPTY_WARNING]`，提示当前知识库没有足够可靠的依据，而不是硬让模型编答案。

这一步是在检索侧做的，而不是把责任推给生成模型自己判断。

### Q21：多用户多知识域隔离在检索侧怎么做？

**A：**

- 向量检索侧：`MetadataFilters`
- BM25 侧：先在 Python 层过滤 node，再建 retriever

也就是说，隔离不是只做一层，而是 dense 和 sparse 两层都做。

---

## 6. 主问答链路

### Q22：主问答链路为什么叫“确定性工作流”？

**A：** 因为它不是自由循环的 Agent，而是一条固定阶段的显式流水线。

当前 `stream_chat_with_agent()` 大致分成：

1. ensure session
2. 长期记忆召回
3. 上下文拼装
4. query rewrite
5. intent router
6. 多源并发检索
7. 汇总上下文
8. 最终生成
9. 同步写 raw transcript
10. 异步做 post-turn maintenance

### Q23：为什么要做 query rewrite？

**A：** 因为多轮对话里大量存在代词、省略和不完整问题。
如果不重写，检索器拿到的 query 往往不够明确，召回会漂。

### Q24：为什么要做 intent router？

**A：** 因为不是所有问题都值得走同一套检索链路。

路由的职责是：

- 判断需不需要检索
- 判断查哪些知识源
- 抽取更适合检索的关键词

### Q25：多源检索为什么要并发？

**A：** 因为一个问题可能同时依赖题库、官方资料、个人错题等多个来源。
并发检索能减少总等待时间，当前实现里确实是用异步并发调度完成的。

---

## 7. 分层记忆系统

### Q26：你们的记忆为什么是分层的？

**A：** 因为“原始事实”“当前会话状态”“跨会话稳定信息”不是一回事，不能混在一起管。

当前可以拆成四层：

1. Raw Transcript
2. Context Assembly Pipeline
3. Working State / Compaction
4. Long-term Memory

### Q27：Layer 1 Raw Transcript 是做什么的？

**A：** 它是 append-only 的原始事实源。

- 用户和 Agent 每轮消息都会顺序写入 `chat_messages`
- 记录 `seq`
- 用户消息可额外保存 `rewritten_query`

所有后续的 compaction、memory extraction、审计和回放，都是从这层出发。

### Q28：Layer 2 Context Pipeline 不是简单拼接吗？

**A：** 不是，它是四步流水线：

1. `sanitize`
2. `truncate`
3. `repair`
4. `assemble`

它的目标是把近期上下文整理成适合模型消费的格式，而不是盲目把历史消息全拼进去。

### Q29：Working State 现在是什么结构？

**A：** 它不再是自由文本摘要，而是结构化 JSON，字段包括：

- `goal`
- `current_phase`
- `covered_topics`
- `pending_topics`
- `candidate_claims_to_verify`
- `observed_gaps`
- `next_best_question`
- `constraints`
- `summary`

这意味着 working state 已经从“随意摘要”进化成“可约束的会话状态对象”。

### Q30：Compaction 什么时候触发？

**A：** 当前阈值是：

- `working_state` token
- 加上 `compaction_cursor` 之后的 recent transcript token
- 总和超过 `5000`

才会触发压缩。

### Q31：压缩时保留什么？

**A：** 当前实现会保留最近 6 条消息不压，把更老的消息压进新的 `working_state`。
这是一种“保留近端细节，折叠远端状态”的设计。

### Q32：除了 working state，为什么还单独有 interview state？

**A：** 因为这两个状态关注点不一样。

- `working_state`：会话协作状态，更偏 prompt 组织和近期任务推进
- `interview_state`：面试评估状态，更偏 topic coverage、evidence、candidate claims、next question

`interview_state` 也是结构化 JSON，并在 post-turn maintenance 时增量更新。

### Q33：长期记忆存什么？

**A：** 当前允许四类长期记忆：

- `user_profile`
- `interaction_preference`
- `feedback_rule`
- `project_reference`

它明确不存：

- 当前会话临时状态
- 短期弱项打分
- 已经属于知识库的技术知识

### Q34：长期记忆怎么写入？

**A：**

1. 每轮对话结束后，后台维护服务会取 `memory_cursor` 之后的增量消息
2. 先更新 `interview_state`
3. 再调用 LLM 做 memory extraction
4. 只保留置信度不低于 `0.65` 的条目
5. 用 `user_id + type + normalized_key` 合并，而不是旧版的 description 精确匹配
6. 写入 `confidence / last_evidence_seq / source_session_id`
7. 成功后推进 `memory_cursor`

### Q35：为什么引入 `normalized_key`？

**A：** 因为单纯按 `description` 精确匹配太脆弱。
现在改成用 `normalized_key` 做同类记忆归并，更适合长期维护和更新。

### Q36：长期记忆怎么召回？

**A：** 不是全量注入，而是：

1. 先按 `recall_count desc, updated_at desc` 取候选
2. 先做 prefilter，默认最多看 12 条
3. 再让快模型从 catalog 里选出最相关的最多 3 条
4. 注入时会截断过长内容，并对老记忆附加过期提示

这就是典型的 Active Recall 思路，而不是“记忆全贴进 prompt”。

---

## 8. ReAct Agent 链路

### Q37：ReAct Agent 主要做什么？

**A：** 当前主要承接岗位选择与准备类复合任务，特点是：

- 要查岗位
- 要拉岗位详情
- 要结合用户画像和面试历史
- 要多步执行

所以不适合走主问答链路的一次性 RAG。

### Q38：当前注册了哪些工具？

**A：**

- `search_jobs`
- `fetch_job_detail`
- `get_user_profile`
- `search_interview_qa`

### Q39：工具调用怎么保证安全和稳定？

**A：**

- 每个工具有独立的 Pydantic 参数模型
- 工具参数长度受 `AGENT_MAX_TOOL_ARG_CHARS` 限制
- 工具调用上下文不是模型自己传的，而是系统注入 `user_id/session_id`
- 可以限制单工具调用次数和总工具调用次数
- 每个工具调用有超时

### Q40：预算熔断具体有哪些维度？

**A：**

- 最大步数 `AGENT_MAX_STEPS`
- 最大工具调用数 `AGENT_MAX_TOOL_CALLS`
- 单工具最大调用次数 `AGENT_MAX_CALLS_PER_TOOL`
- 总 token 上限 `AGENT_MAX_TOTAL_TOKENS`
- 总运行时长 `AGENT_MAX_RUNTIME_SECONDS`

任一条件触发，就停止 Agent 执行。

### Q41：为什么要记录 Agent Trace？

**A：** 因为工具链路比普通问答更难 debug。
当前系统会持久化：

- run
- step
- tool args
- observation
- error
- latency

这样能做：

- 运行轨迹回放
- 成本分析
- 失败定位
- 工具路径优化

---

## 9. 音频分析与岗位报告

### Q42：面试录音分析链路怎么走？

**A：**

1. 前端拿 presigned URL
2. 音频传 MinIO/S3
3. `/analyze` 创建 `Interview(status=PENDING)`
4. Celery Worker 拉取文件
5. `transcribe_media()` 转写
6. `analyze_interview()` 做问答拆解与评分
7. 保存 `Transcript` 与 `AnalysisResult`
8. Interview 状态推进到 `COMPLETED`

### Q43：个人错题是怎么回流到知识库的？

**A：** `/memory/save` 接口会把：

- 问题
- 改进答案
- 原始分数
- 标签

拼成文本，再通过 `ingest_text()` 写回 `personal_memory` 知识源。

这相当于把复盘结果再次纳入 RAG。

### Q44：analytics/report 是做什么的？

**A：** 它是一个全局诊断通道，会综合用户的历史面试与记忆数据，生成更宏观的能力分析报告，不属于主问答链路。

---

## 10. 测试、稳定性与当前边界

### Q45：当前测试情况怎么样？

**A：** 当前本地在项目专用环境下跑 `pytest -q`，结果是：

- `51 passed`
- `1 warning`

说明这轮重构后的 API、核心服务和模型层已经有比较完整的回归覆盖。

### Q46：你觉得这个项目最有工程含量的点是什么？

**A：** 我会优先讲四个：

1. 主问答链路做成了确定性并发工作流，而不是黑盒式自由 Agent
2. 分层记忆从 transcript、context、working state 到 long-term memory 有明确边界
3. RAG 链路不是纯向量，而是 dense + BM25 + rerank + score gate 的组合
4. 复杂任务单独走 ReAct Agent，并加了预算熔断、工具参数校验和 trace

### Q47：当前实现还有哪些边界或下一步优化点？

**A：**

- BM25 目前仍在应用层构建，规模继续变大后可能需要独立稀疏检索层
- working state 和 interview state 已经结构化，但还可以进一步减少 LLM 漂移
- long-term memory 现在已经有 `normalized_key` 和 `confidence`，下一步可以继续做 promotion / decay
- 主问答链路和 Agent 链路都在增长，未来可以补更细的 benchmark 和回归集

---

## 11. 最后收口

### Q48：如果最后让你总结这个项目最能体现你什么能力，你怎么答？

**A：** 我不会把它描述成“我接了几个模型接口”，而会说这是一个围绕真实求职场景搭起来的 AI 后端系统。我做的重点是把 RAG、记忆、异步音频分析、工具型 Agent、多用户隔离和效果评测串成一套稳定、可解释、可持续优化的工程链路。
