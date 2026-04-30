# Interview Copilot 超详细面试问答手册

本文覆盖 Interview Copilot 项目在面试中可能被问到的问题。回答尽量贴合当前代码实现，适合用于简历答辩、系统设计追问和项目深挖。

---

## 1. 业务与产品定位

### Q1：这个项目解决什么问题？

A：它解决技术面试准备中的三个核心问题：第一，面试录音难以复盘；第二，知识点和错题难以沉淀；第三，多轮练习缺少个性化上下文。Interview Copilot 把录音转写、面试分析、知识库问答、长期记忆和岗位准备串成闭环。

### Q2：它和普通聊天机器人有什么区别？

A：普通 ChatBot 主要是单轮或多轮生成。本项目有 RAG（Retrieval-Augmented Generation，检索增强生成）、Memory（长期记忆）、Interview State（面试状态）、ReAct Agent（工具智能体）、Celery Worker（异步任务）和 Evaluation（评测）体系，更像一个 AI 面试后端平台。

### Q3：核心业务链路有哪些？

A：三条。第一是 Chat QA（聊天问答）：用户提问，系统结合上下文、记忆和知识库回答。第二是 Interview Analysis（面试分析）：上传录音，异步转写和分析。第三是 Job Preparation（岗位准备）：ReAct Agent 调工具查岗位、拉详情、结合用户画像生成准备建议。

### Q4：项目的用户价值是什么？

A：它让面试准备从“零散练习”变成“持续改进”。用户可以得到即时问答、录音复盘、错题沉淀、长期偏好记忆和岗位准备建议，系统会把历史信息用于后续回答。

### Q5：项目最核心的工程难点是什么？

A：不是调用 LLM，而是如何把多轮上下文、知识库检索、长期记忆、异步转写、工具调用和数据隔离组织成稳定链路。难点在于边界设计、检索质量、状态管理和可观测性。

---

## 2. 整体架构

### Q6：整体架构怎么分层？

A：API 层、普通问答工作流层、ReAct Agent 层、RAG 层、服务层、数据与 Worker 层。API 用 FastAPI；普通问答在 `backend/app/agent/`；ReAct 在 `backend/app/agent_runtime/`；RAG 在 `backend/app/rag/`；服务在 `backend/app/services/`；数据层是 PostgreSQL、Milvus、Redis、MinIO/S3。

### Q7：为什么要做双链路？

A：普通问答和复杂任务的优化目标不同。普通问答需要稳定、低延迟、可控，所以走确定性 pipeline；复杂任务需要工具调用和多步推理，所以走 ReAct Agent。这样避免所有请求都被 Agent 的不确定性拖慢。

### Q8：普通问答为什么不用自由式 Agent？

A：因为普通面试问答通常不需要模型自己探索工具路径。自由式 Agent 会增加延迟、成本和不确定性，还不利于排查问题。显式 pipeline 每一步职责清楚，更容易优化和测试。

### Q9：ReAct Agent 为什么还要保留？

A：因为岗位检索、岗位详情、结合用户画像生成准备建议这类任务需要多步工具调用。ReAct Agent 适合让模型决定是否调用工具、调用哪个工具、如何基于 observation 继续推理。

### Q10：系统有哪些主要存储？

A：PostgreSQL 保存业务数据、聊天记录、面试分析、长期记忆和 Agent trace；Milvus 保存 RAG 知识向量和长期记忆向量；Redis 作为 Celery broker/result backend；MinIO/S3 保存音频和文档对象。

---

## 3. API 与鉴权

### Q11：认证怎么做？

A：使用 JWT（JSON Web Token，令牌鉴权）。登录成功后返回 Bearer token，普通 HTTP 接口通过 `get_current_user()` 依赖校验，WebSocket 通过 query token 解码校验用户。

### Q12：Chat API 支持哪些能力？

A：支持创建会话、列出会话、获取历史、改标题、查询完整 transcript、WebSocket 流式聊天、SSE 流式聊天、列出长期记忆、查看单条记忆和删除记忆。

### Q13：为什么同时支持 WebSocket 和 SSE？

A：WebSocket 适合双向实时通信，SSE 适合服务端单向流式返回，前端实现更简单。两者都能承载流式回答，方便不同客户端选择。

### Q14：RAG 和知识库 API 做什么？

A：`/knowledge/upload/url` 生成当前用户私有文档的预签名上传地址，`/knowledge/documents` 负责创建、查询、更新、删除用户自己的知识库文档，`/rag/query` 只在当前用户自己的知识库中执行检索查询。

### Q15：Model Runtime API 做什么？

A：它允许查看和更新不同角色的模型选择。项目把模型分成 `primary`、`fast`、`agent` 三个角色，分别服务普通 RAG 回答、轻量规划/抽取、ReAct function calling。

---

## 4. 普通多轮问答 Pipeline

### Q16：主问答链路怎么执行？

A：`stream_chat_with_agent()` 先确保 session 和 interview_state 存在；然后 assemble rewrite context；调用 `plan_query()` 生成 QueryPlan；按计划并发召回长期记忆和知识库；组装 answer context；根据是否需要知识检索选择 direct prompt 或 RAG prompt；流式生成；写入 transcript；异步触发 compaction、interview_state update、memory extraction 和 telemetry。

### Q17：为什么要先 assemble rewrite context？

A：用户当前问题可能有代词和省略，比如“那这个怎么答”。改写需要知道近期对话、working state 和 interview state，但不需要完整 RAG 结果。所以先加载轻量上下文用于规划。

### Q18：QueryPlan 包含什么？

A：包含 standalone_query（上下文消解后的独立问题）、dense_query（语义检索查询）、sparse_query（关键词检索查询）、needs_memory_retrieval（是否召回记忆）、memory_types（记忆类型）、needs_knowledge_retrieval（是否查知识库）、knowledge_sources（知识源）、answer_mode（回答模式）、reasoning（审计说明）。

### Q19：为什么区分 dense_query 和 sparse_query？

A：dense_query 面向向量检索，需要保留自然语言语义；sparse_query 面向 BM25/关键词检索，需要更短、更聚焦的术语。两者混用会损失召回质量。

### Q20：知识库和记忆为什么可以并发召回？

A：planner 已经先确定是否需要 memory 和 knowledge。之后两者互不依赖，可以用 `asyncio.create_task` 并发执行，减少整体等待时间。

### Q21：direct chat 和 RAG chat 怎么区分？

A：由 `QueryPlan.needs_knowledge_retrieval` 决定。不需要知识库时用 fast LLM 和直接回答提示词；需要知识库时用 primary LLM 和 RAG 提示词，强调基于检索知识回答。

### Q22：回答后为什么异步做维护？

A：维护包括 compaction、interview_state 更新、长期记忆抽取，耗时且不应该阻塞用户看到答案。因此主回答完成后异步执行。

---

## 5. 上下文 Pipeline 与状态管理

### Q23：Raw Transcript 是什么？

A：Raw Transcript（原始转录/原始对话记录）是事实源。每轮用户和 AI 消息按 `seq` 写入 `chat_messages`，后续 working state、memory、trace 和审计都可以从它重建。

### Q24：Context Pipeline 做什么？

A：它把数据库历史转成模型可消费上下文。流程是 sanitize（清洗非法角色和系统调试消息）、truncate（按 token budget 保留最近消息）、repair（修复开头 Agent 或结尾 User 造成的断裂对话）、assemble（组装 working_state、interview_state、memory、knowledge、recent_turns、current_query）。

### Q25：ContextBundle 是什么？

A：`ContextBundle` 是结构化上下文包，包含 working_state、interview_state、recent_turns、relevant_memories、knowledge_chunks 和 current_query。它让系统先结构化上下文，再由 PromptRenderer 渲染成字符串。

### Q26：为什么不直接拼字符串？

A：过早拼字符串会让预算控制、排序、来源标注、去重和测试都很困难。结构化后再渲染，可以明确每类上下文的位置和 token 预算。

### Q27：PromptRenderer 的区块顺序是什么？

A：顺序是 System rules、Working State、Interview State、Long-term Memories、Retrieved Knowledge、Recent Turns、Current Query。当前问题放最后，保证本轮意图最靠近模型回答位置。

### Q28：Working State 是什么？

A：Working State（工作状态）是结构化 JSON，字段包括 goal、current_phase、covered_topics、pending_topics、candidate_claims_to_verify、observed_gaps、next_best_question、constraints、summary。它用于压缩当前会话的协作状态。

### Q29：Compaction 什么时候触发？

A：当 working_state 加上 compaction_cursor 之后的 recent transcript 超过 5000 tokens 时触发。系统保留最近 6 条消息不压缩，把更早消息折叠进新的 working_state，并推进 compaction_cursor。

### Q30：Interview State 是什么？

A：Interview State（面试状态）是独立表 `interview_states` 中的结构化状态，字段包括 goal、phase、covered_topics、pending_topics、observed_gaps、evidence、candidate_claims、next_question、constraints。它更像面试进度状态机。

### Q31：为什么要同时有 Working State 和 Interview State？

A：Working State 面向 prompt 组织和协作状态，Interview State 面向面试过程管理。拆开后职责清楚，减少状态漂移，也方便后续 UI 展示和评测。

### Q32：post-turn maintenance 做什么？

A：它执行 compaction、interview state update 和 memory extraction。现在还有 session 级串行保护，避免连续消息导致 cursor 竞争或重复抽取。

---

## 6. 长期记忆系统

### Q33：长期记忆存什么？

A：只存跨会话稳定信息，包括 user_profile（用户画像）、interaction_preference（交互偏好）、feedback_rule（反馈规则）、project_reference（项目背景）。不存临时弱点、当前轮进度或通用技术知识。

### Q34：长期记忆怎么写入？

A：Post-turn maintenance 读取 `memory_cursor` 之后的增量消息，先更新 interview_state，再调用 LLM 抽取 durable memories（持久记忆）。系统过滤非法 type 和低于 0.65 confidence（置信度）的条目，用 `user_id + type + normalized_key` 合并，写入 confidence、importance、source_session_id、last_evidence_seq，并尝试写入 memory vector collection。

### Q35：为什么引入 normalized_key？

A：description 是自然语言字段，容易因为措辞变化导致重复记忆。normalized_key 是归一化合并键，可以把同类记忆合并到同一条记录。

### Q36：长期记忆为什么要向量化？

A：只按更新时间或召回次数筛选，相关但冷门的记忆可能永远进不了候选。向量化后可以按语义相似度找到相关记忆，再结合词法匹配、重要性和新近程度排序。

### Q37：为什么记忆使用独立 Milvus collection？

A：长期记忆和知识库 chunk 的语义、生命周期、metadata 和清理策略不同。独立 collection 可以避免污染知识库检索，也方便单独调参和回填。

### Q38：长期记忆怎么召回？

A：MemoryRetrievalService 同时走 memory_vector_service 的向量召回和 lexical_candidates 的词法召回，再用 HybridRetriever 融合。最终最多注入 3 条，注入前截断过长内容，并对太旧的记忆加 staleness_note（陈旧提示）。

### Q39：HybridRetriever 怎么打分？

A：分数由 `0.6 × vector_score + 0.35 × lexical_score + 0.15 × importance + 0.05 × recency_score` 组成。这样同时考虑语义相关、关键词覆盖、记忆重要性和新近程度。

### Q40：记忆召回后会产生什么副作用？

A：被选中的记忆会增加 recall_count，更新 last_accessed_at，然后以截断后的正文注入 prompt。

### Q41：记忆写入失败会不会影响回答？

A：不会。记忆向量 upsert 失败会把 embedding_status 标为 failed 并记录 warning；回答主链路已经完成，后续还能降级到词法召回。

---

## 7. RAG 摄取与检索

### Q42：RAG 摄取流程是什么？

A：文件上传到 MinIO/S3 后，API 投递 Celery 任务。Worker 下载文件，`ingest_document()` 用 LlamaIndex 解析文档，根据类型切块，给 node 写入 `user_id/source_type`，再写入 Milvus 向量库和 PostgreSQL docstore。

### Q43：为什么要自适应切块？

A：不同内容结构不同。Markdown 按标题结构切，JSON 按结构切，代码按语言语法切，普通文本按句子窗口切。统一固定长度切块会破坏语义边界，降低召回质量。

### Q44：支持哪些切块策略？

A：Markdown 或面试题/官方文档使用 MarkdownNodeParser；JSON 使用 JSONNodeParser；Python、Java、C、C++ 使用 CodeSplitter；其他文本使用 SentenceSplitter。

### Q45：检索链路是什么？

A：先用 Milvus 做 dense retrieval（稠密向量检索），再用 Postgres docstore 构建 BM25（词法检索），通过 QueryFusionRetriever 做 RRF（Reciprocal Rank Fusion，倒数排序融合），再用 BGE reranker（重排模型）重排，最后用 score gate（分数闸门）过滤低置信结果。

### Q46：为什么不是纯向量检索？

A：面试题里有很多关键词强依赖内容，比如框架名、函数名、算法名、协议名。向量检索擅长语义相似，BM25 擅长精确词面命中，二者融合更稳。

### Q47：BM25 为什么在应用层构建？

A：当前规模下，从 PostgresDocumentStore 取出经过 user_id/source_type 过滤的 nodes 后构建 BM25，工程复杂度低且边界清楚。未来数据量变大可以升级到独立 sparse index。

### Q48：为什么要加 Reranker？

A：向量检索和 BM25 都是粗召回，目标是尽量别漏。Reranker 是二阶段排序，用交叉编码模型判断 query 和候选片段的相关性，提升最终上下文质量。

### Q49：RAG 怎么降低幻觉？

A：如果重排后没有节点超过 `RAG_MIN_SCORE`，返回 `[SYSTEM_EMPTY_WARNING]`，告诉模型知识库没有足够可靠依据。另有 lexical fallback（词面覆盖兜底）避免 reranker 分数尺度导致误杀。

### Q50：多租户隔离怎么做？

A：上传、文档记录、摄取 metadata、面试记录、长期记忆和检索请求都绑定 `current_user.username`。检索时 Milvus 用 `user_id == 当前用户` 的 MetadataFilters，BM25 在 Python 层也只使用当前用户的 node 池；项目不再设计公共库或共享题库。

---

## 8. ReAct Agent 链路

### Q51：ReAct Agent 用在哪里？

A：用于岗位检索、岗位详情、结合用户画像做准备建议、搜索面试题库等多步任务。普通问答不默认走 ReAct。

### Q52：当前有哪些工具？

A：`search_jobs` 搜索 Lever 岗位；`fetch_job_detail` 获取岗位详情；`get_user_profile` 读取用户画像、最近会话、面试统计；`search_interview_qa` 搜索面试题库。

### Q53：工具安全怎么做？

A：每个工具都有 Pydantic 参数模型；工具参数 JSON 长度受 `AGENT_MAX_TOOL_ARG_CHARS` 限制；站点有 allowlist（白名单）；上下文中的 user_id/session_id 由系统注入；工具执行有 timeout；未知工具、参数错误、超时都会写成 observation 返回。

### Q54：预算熔断有哪些？

A：最大步数 `AGENT_MAX_STEPS`，最大工具调用数 `AGENT_MAX_TOOL_CALLS`，单工具最大调用数 `AGENT_MAX_CALLS_PER_TOOL`，总 token 上限 `AGENT_MAX_TOTAL_TOKENS`，总运行时间 `AGENT_MAX_RUNTIME_SECONDS`。超限后写 budget_stop trace 并返回停止原因。

### Q55：为什么记录 Agent Trace？

A：Agent 最怕黑盒。系统把 AgentRun 和 AgentStep 落库，记录工具名、参数、observation、错误、延迟、token 和 final answer。这样能做回放、debug、成本分析、trajectory evaluation（轨迹评测）。

### Q56：ReAct 会不会污染长期记忆？

A：默认不会。ReAct 会读取相关记忆辅助执行，但只有 planner 判断任务属于 interview_learning、review、preference_update 时，才允许写长期记忆。

---

## 9. 音频分析与异步任务

### Q57：为什么音频分析必须异步？

A：音频转写、说话人分离、LLM 分析耗时长且可能占 GPU/CPU。如果放在 HTTP 请求里，会导致超时和服务阻塞。因此 `/analyze` 只创建 Interview 并投递 Celery 任务。

### Q58：音频链路怎么跑？

A：前端拿 presigned URL 上传到 MinIO/S3；调用 `/analyze`；Celery task 把状态从 PENDING 改为 TRANSCRIBING，下载文件，调用 `transcribe_media()`，再改为 ANALYZING，调用 `analyze_interview()`，写 Transcript 和 AnalysisResult，最后 COMPLETED。失败则 FAILED。

### Q59：WhisperX 输出为什么转 Markdown？

A：因为后续分析和切分更容易处理结构化文本。转写结果以 speaker 段落形式输出，便于区分面试官问题和候选人回答。

### Q60：面试分析怎么抽取问答对？

A：系统解析 speaker turn，默认第一个 speaker 是面试官，然后按“面试官连续提问 + 候选人连续回答”构造 QA pairs。如果格式不可用，就按段落 fallback。

### Q61：长转录怎么处理？

A：根据 `ANALYSIS_CHUNK_TOKEN_LIMIT` 分块，并尽量保持完整 QA pair。每个 chunk 单独分析，多 chunk 时再汇总 overall score 和 overall feedback。

---

## 10. 模型与配置

### Q62：模型路由怎么做？

A：`model_registry.py` 定义 ModelProfile 和 role defaults。primary 和 fast 默认 DeepSeek V4 Flash，agent 默认 DeepSeek V4 Pro。RuntimeLLMProxy 每次按 role 取当前选择，方便前端或运行时切换。

### Q63：为什么分 primary、fast、agent？

A：不同任务对模型要求不同。primary 负责质量更高的主回答；fast 负责规划、记忆抽取、状态更新等轻量任务；agent 需要支持 function calling。

### Q64：启动时初始化什么？

A：FastAPI lifespan 会创建表、执行 schema compatibility、初始化 LlamaIndex LLM 和 embedding、回填 memory embedding、初始化 reranker。Whisper 和 diarization 模型由 Celery worker 加载。

### Q65：为什么不用 Alembic？

A：当前项目仍是本地开发阶段，使用 `create_all + schema_compat` 保持已有本地数据库可用。生产化后应迁移到 Alembic 管理数据库版本。

---

## 11. 安全与隔离

### Q66：数据隔离有哪些层？

A：业务表按 user_id 查；RAG 摄取和检索按 user_id/source_type 限制；memory vector collection 也按 user_id 过滤；Agent trace 查询必须匹配当前 user_id。

### Q67：有哪些安全风险和改进方向？

A：本地 docker compose 的 MinIO bucket 示例适合开发不适合生产；CORS 当前允许所有来源，生产要收紧；默认 SECRET_KEY 只能本地使用；LLM prompt injection 仍需加强，例如对检索内容做更严格的来源标注和工具调用策略约束。

### Q68：工具调用如何防止越权？

A：工具上下文由系统注入 user_id 和 session_id，模型不能自己伪造；外部站点有 allowlist；参数经过 Pydantic 校验；trace 查询按当前用户过滤。

---

## 12. 评测与测试

### Q69：当前测试情况怎么样？

A：后端测试覆盖 API、核心配置、安全、模型注册、ORM、RAG scope、context pipeline、memory pipeline、agent runtime、agent tools、agent trace、storage 和 telemetry。最近一次执行 `pytest backend/tests -q` 通过 `60 passed`。

### Q70：RAG 评测有哪些指标？

A：`run_rag_eval.py` 统计 Hit Rate@3（前三命中率）、MRR@3（平均倒数排名）、Precision@3（前三精确率）、Recall@3（前三召回率）、nDCG@3（排序质量）、RAGAS faithfulness（忠实度）、context precision（上下文精确度）、context recall（上下文召回率）、延迟、token、失败率和超时率。

### Q71：Agent 怎么评测？

A：`run_agent_trajectory_eval.py` 基于 AgentRun/AgentStep 统计 run_count、completion_rate、avg_steps、avg_tool_calls、invalid_tool_call_rate、avg_latency_ms。如果提供标注数据，还能算 tool_selection_accuracy（工具选择准确率）。

### Q72：为什么评测要分 RAG 和 Agent？

A：RAG 评测关注“检索到的上下文是否相关、答案是否忠实”；Agent 评测关注“有没有完成任务、工具是否选对、工具调用是否有效、轨迹是否稳定”。二者评价对象不同。

---

## 13. 部署与运维

### Q73：部署依赖有哪些？

A：FastAPI 应用和 Celery worker 跑在主机；docker compose 提供 PostgreSQL、Redis、MinIO、Milvus、Nginx。启动时 FastAPI lifespan 创建表、检查 schema、初始化 LlamaIndex、回填 memory embedding、加载 reranker。

### Q74：为什么 API 和 Worker 不全放 compose？

A：当前 compose 定位为本地基础设施，API 和 worker 由开发者在主机启动，便于热重载、调试 GPU/模型缓存和本地 Python 环境。

### Q75：生产化还需要补什么？

A：收紧 CORS、替换 SECRET_KEY、私有化 MinIO bucket、引入 Alembic、API/Worker 容器化、加 Prometheus/Grafana 监控、为模型和向量库加健康检查、完善日志脱敏和数据删除策略。

---

## 14. 技术选型追问

### Q76：为什么选 FastAPI？

A：FastAPI 支持 async/await、WebSocket、SSE、Pydantic 校验和 OpenAPI 文档，适合流式聊天和异步 I/O。Flask 更轻但异步和类型校验弱；Django 更重，当前项目不需要完整全家桶。

### Q77：为什么选 LlamaIndex？

A：项目核心是文档摄取、节点切分、docstore、向量索引和检索融合，LlamaIndex 更贴近 RAG 数据层。LangChain 更偏通用链式编排和 Agent 生态，但普通问答链路不希望过度 Agent 化。

### Q78：为什么选 Milvus？

A：Milvus 是服务化向量数据库，适合独立部署和扩展；HNSW 参数清晰；能把向量检索和业务数据库解耦。FAISS 更适合本地实验，Chroma 更轻，pgvector 部署简单但和业务库耦合更高。

### Q79：为什么选 Celery？

A：音频转写、文档摄取、embedding、LLM 分析都是重任务。Celery 有独立 worker、broker、result backend 和失败状态，比 FastAPI BackgroundTasks 更适合长任务。

### Q80：为什么选 WhisperX？

A：WhisperX 比基础 Whisper 更适合带时间戳对齐和说话人分离的面试录音，后续可以更稳定地区分面试官问题和候选人回答。

---

## 15. 优化方向

### Q81：RAG 还能怎么优化？

A：BM25 可以从应用层构建演进为独立 sparse index；加入 query expansion；对 source_type 做更细粒度 routing；引入 learning-to-rank；做 chunk-level citation。

### Q82：记忆还能怎么优化？

A：可以加入 memory decay（记忆衰减）、promotion（晋升规则）、conflict resolution（冲突解决）、用户可编辑记忆、敏感记忆删除策略，以及基于评测的 memory usefulness（记忆有效性）指标。

### Q83：Agent 还能怎么优化？

A：可以加入 tool policy（工具策略）、planner/executor 分离、并行工具调用、失败重试、工具结果缓存、trajectory replay UI、自动生成工具选择评测集。

### Q84：音频分析还能怎么优化？

A：可以加入更精细的说话人角色识别、题目边界检测、面试官追问识别、答案结构评分维度、语速和停顿分析，以及对每道题生成可练习的 follow-up question。

### Q85：上下文 pipeline 还能怎么优化？

A：可以加入冲突检测、来源优先级仲裁、prompt cache 稳定性优化、上下文命中率指标、不同 answer_mode 的模板评测，以及长期记忆和 knowledge chunk 的引用标注。

---

## 16. 总结类问题

### Q86：这个项目最亮的点是什么？

A：它不是只接入大模型，而是把 RAG、长期记忆、多轮上下文压缩、异步音频分析、工具型 Agent、安全隔离和评测闭环组合成一套工程化系统。

### Q87：如果让你讲最大收获，你怎么说？

A：最大收获是理解了大模型应用真正难的不是调用接口，而是上下文工程、检索工程、状态管理、异步任务和可观测性。模型只是核心能力之一，系统边界才决定项目能不能稳定运行。

### Q88：如果面试官质疑这是套壳项目，怎么回答？

A：可以说：如果只是套壳，核心就是一次 prompt 调用。但这个项目有文档摄取、混合检索、长期记忆向量化、query planner、ContextBundle、ReAct 工具治理、音频转写后台任务、Agent trace、模型运行时选择和评测脚本。工程复杂度主要在模型调用之外。

### Q89：如果让你重做一版，会先改哪里？

A：我会优先把数据库迁移改成 Alembic，把 RAG BM25 演进到独立 sparse index，把 memory usefulness 做成可评测指标，并补充生产级监控和 prompt injection 防护。

### Q90：最后怎么概括项目？

A：Interview Copilot 是一个围绕技术面试准备构建的 AI 后端系统。它用确定性多轮 RAG pipeline 保证普通问答稳定，用长期记忆实现个性化，用 Celery 承载音频和摄取重任务，用 ReAct Agent 处理工具型复合任务，并通过 trace、测试和评测保证系统可解释、可追踪、可持续优化。
