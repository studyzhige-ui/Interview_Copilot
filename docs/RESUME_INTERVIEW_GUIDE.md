# Interview Copilot 简历面试讲解指南

> 本文档基于候选人的项目简历逐条展开，为每个 bullet point 提供 30 秒讲解、2 分钟深入、追问与回答、代码定位、选型辩护和常见翻车点。
> 所有内容均对照项目实际代码撰写，可溯源到具体文件和函数。

---

## Bullet 1：项目定位与业务闭环

> **简历原文**：构建面向求职的 AI 面试辅助系统，覆盖面试内容采集、知识增强问答、错题沉淀、多轮复盘与岗位筛选与准备等核心环节，提升候选人的面试准备效率与回答质量。

### a) 30 秒讲解版

这个项目是一个帮助求职者系统化准备面试的 AI 后端系统。它不只是一个简单的聊天机器人——它把面试准备中的几个核心环节串成了一个工程闭环：你可以上传面试录音，系统自动转写并逐题打分告诉你哪里答得不好；你可以把技术文档、面试题库上传到个人知识库，后续问答时系统会基于这些资料给出精准回答；系统还能跨会话记住你的项目背景和偏好，不需要每次重新介绍自己；如果你想找岗位，它还有工具代理帮你搜索岗位信息并结合你的经历给出准备建议。

### b) 2 分钟深入版

系统的核心价值在于把五个原本割裂的面试准备环节串联起来：

**第一个环节：面试内容采集**。用户上传面试录音后，后台用 WhisperX（一个增强版的语音识别引擎）做转写，同时集成 Pyannote 的说话人分离技术来区分"谁在说话"——哪些话是面试官问的，哪些是候选人答的。转写完成后自动构建成结构化的问答对，每道题都有评分、点评和改进答案。

**第二个环节：知识增强问答**。用户可以上传各种文档——面试题库、技术官方文档、个人笔记等。系统会根据文件类型自动选择最优的切分策略（比如 Markdown 按标题切、代码按函数切），存入向量数据库。后续聊天时，系统会混合使用语义检索和关键词检索，从知识库里找到最相关的内容来辅助回答，而不是靠大模型自身知识。

**第三个环节：错题沉淀**。面试分析的结果（哪道题答得不好、改进后的回答是什么）可以反哺到知识库，变成检索材料。下次再遇到类似问题时，系统能直接检索到之前的改进答案。

**第四个环节：多轮复盘**。系统有长期记忆功能，能跨会话记住用户的项目背景、技术栈、面试偏好等。配合 Working State（对话摘要压缩）和 Interview State（面试进度追踪），可以进行持续的多轮复盘训练。

**第五个环节：岗位筛选与准备**。通过 ReAct Agent（一种让 AI 自主决定调用什么工具的框架），可以搜索岗位、获取岗位详情、结合用户画像生成针对性的准备建议。

这五个环节不是孤立的——面试录音的分析结果沉淀为知识库内容，知识库增强了问答质量，长期记忆让系统越用越懂用户，岗位搜索结果可以结合用户经历生成个性化建议。

### c) 面试官可能的追问

**追问 1：这五个环节中，技术难度最高的是哪个？**

参考回答：我认为是知识增强问答这个环节，因为它涉及最多的工程设计决策。不是说做一个 RAG 检索就行了——要做好需要解决多个子问题：怎么根据文件类型选择最优的切分策略（自适应切块引擎）、怎么融合语义检索和关键词检索的结果（RRF 融合排序）、怎么防止 AI 在知识库里没有答案时编造内容（防幻觉三重防线）、怎么在有限的上下文窗口里放入最有价值的信息（TokenBudgeter 分层预算）。这些子问题相互耦合，每个环节都需要留好降级策略。

**追问 2：你说的"工程闭环"具体是怎么实现的？数据是怎么流转的？**

参考回答：以一个典型的使用流程来说明：用户上传面试录音 → Celery 后台任务做转写和分析 → 分析结果写入 PostgreSQL → 用户在聊天中提到"上次面试哪道题答得不好"→ Query Planner 判断需要检索知识库 → 从知识库中检索到之前的分析结果和改进答案 → 长期记忆系统记住"这个候选人在 Redis 相关问题上比较薄弱"→ 下次用户开始新会话时，系统自动召回这条记忆，面试辅导时会重点关注 Redis 相关内容。

**追问 3：和市面上的面试准备工具（比如 ChatGPT）相比，你的系统有什么本质区别？**

参考回答：最核心的区别有三个。第一，ChatGPT 没有个人知识库——它只能靠自身训练数据回答，我的系统能基于用户上传的面试题库和文档精准回答。第二，ChatGPT 没有跨会话记忆——每次对话都从零开始，我的系统能记住用户的项目背景和偏好。第三，ChatGPT 没有面试录音分析——我的系统能自动转写录音、区分说话人、逐题打分。这三个差异不是调一下 API 就能实现的，每个都需要独立的工程设计。

**追问 4：你一个人做的还是团队做的？**

参考回答：主要是我一个人负责后端的全部设计和实现。包括架构设计、RAG 管线、长期记忆系统、Agent 运行时、异步任务队列、Docker 部署和测试套件。前端使用 Vue 3，但核心的工程复杂度集中在后端。

**追问 5：这个项目目前的用户量和使用情况是什么样的？**

参考回答：这是一个个人项目，主要服务于我自己的面试准备。但在工程上我按照生产级标准设计——多租户隔离（支持多用户）、Access/Refresh 双令牌 JWT 认证（Access Token 30 分钟过期用于鉴权，Refresh Token 7 天过期用于无感续期）、Docker Compose 部署、CI/CD 管线、81 项自动化测试。这些设计确保如果将来要服务更多用户，不需要重新设计架构。

### d) 关键代码/配置定位

```
# 核心业务入口
backend/app/agent/agent_executor.py    → stream_chat_with_agent()  # 普通聊天主链路
backend/app/agent_runtime/react_agent.py → run_react_agent()       # ReAct 工具代理
backend/app/worker/tasks.py            → process_interview_analysis()  # 面试分析

# 应用启动
backend/app/main.py                    → lifespan()  # 启动顺序和资源初始化
```

### e) 技术选型辩护

这个 bullet point 主要涉及产品定位，不涉及具体技术选型对比。但如果面试官问"为什么要自己做而不用现有产品"，可以回答：现有的 AI 面试工具要么只有聊天功能（没有知识库和记忆），要么只有录音转写（没有智能问答），要么只是简单的 GPT wrapper。把这些能力整合成一个系统需要解决大量的工程问题——多种数据源的统一检索、上下文窗口的精细管理、跨会话记忆的持久化和召回、异步任务的可靠执行。这些是工程设计的价值，不是简单地调 API 能解决的。

### f) 常见翻车点

1. **说得太抽象**。不要只说"覆盖多个环节"，要具体说清楚每个环节做了什么（比如"面试内容采集"具体是指音频转写+说话人分离+逐题评分）。
2. **漏掉闭环的串联逻辑**。每个环节单独说听起来像是五个独立的功能。一定要强调环节之间的数据流转——分析结果如何沉淀为知识库内容，知识库如何增强问答，记忆如何跨会话持久化。
3. **把"项目定位"和"技术实现"混在一起**。这个 bullet point 应该重点讲"做了什么"，不要急着讲"怎么做的"。技术细节留给后面的 bullet point。

---

## Bullet 2：后端框架、音频处理与文档摄取

> **简历原文**：基于 FastAPI + LlamaIndex 搭建后端，支持面试录音上传至对象存储，集成 WhisperX 声纹分离转写与 Celery 异步任务队列实现重计算离线处理；设计自适应文档解析与切分策略，完成题库、官方资料、个人错题等多类知识源摄取，基于 Milvus 与 PostgreSQL 支撑向量检索和节点元数据持久化。

### a) 30 秒讲解版

后端用 FastAPI 做 API 框架，LlamaIndex 做 RAG 的基础设施。面试录音上传到 MinIO 对象存储后，由 Celery 后台任务异步处理——先用 WhisperX 转写成文字并区分说话人，再用大模型逐题评分。知识库文档的摄取有一个自适应切块引擎，能根据文件类型（Markdown、代码、JSON 等）自动选择最优的切分策略，切完后向量存到 Milvus，原始文本存到 PostgreSQL，形成"向量+文本"的双存储架构。

### b) 2 分钟深入版

这个 bullet point 包含三个子系统，我分别展开：

**子系统一：FastAPI + LlamaIndex 后端架构**

FastAPI 负责所有 HTTP 和 WebSocket 请求的处理。选 FastAPI 而不是 Flask 或 Django，核心原因是它原生支持 async/await（异步编程）。项目中几乎每个请求都涉及多次 IO 操作——调大模型 API、查数据库、查向量库——这些操作都是"等待远程服务返回结果"，在等待的时候 CPU 其实是闲着的。async 让 CPU 在等待一个 IO 的时候可以去处理其他请求，显著提高并发能力。

LlamaIndex 负责 RAG（Retrieval-Augmented Generation，检索增强生成——即让 AI 先从知识库里检索相关内容，再基于这些内容生成回答）的基础设施。具体使用了它的 Embedding 管理（通过 `Settings.embed_model` 全局配置 BGE 中文向量模型）、VectorStore 连接器（`MilvusVectorStore` 连接 Milvus 向量数据库）、Docstore（`PostgresDocumentStore` 在 PostgreSQL 中存储文档块原文）和 NodeParser（多种切块器）。

**子系统二：音频转写与异步处理**

面试录音的处理是一个重计算任务——30 分钟的录音可能需要几分钟来转写。如果在 API 进程中同步执行，会阻塞其他用户的请求。所以这个任务交给 Celery（一个独立的分布式任务队列）在后台异步处理。

完整流程是这样的：

1. 前端先调 API 获取一个预签名 URL（MinIO 生成的临时上传地址）。
2. 前端用这个 URL 直接把文件上传到 MinIO，不经过后端。这很关键——面试录音可能几十到几百 MB，如果经过后端会占用大量内存和带宽。
3. 上传完成后，前端通知后端创建 Interview 记录。
4. 后端派发一个 Celery 任务（`process_interview_analysis`），立即返回 interview_id 给前端。
5. Celery Worker 在独立进程中执行：下载音频 → WhisperX 转写（支持批处理，`batch_size=16`）→ Pyannote 说话人分离 → 把文字和说话人标签对齐 → 构建问答对 → 分块送 LLM 逐题评分 → 写入分析结果。
6. 前端轮询 Interview 状态（PENDING → TRANSCRIBING → ANALYZING → COMPLETED）。

Celery 任务配置了自动重试：只对网络和 IO 类异常重试（`autoretry_for=(ConnectionError, TimeoutError, OSError)`），最多 3 次，指数退避（第一次等 1 秒，第二次 2 秒，第三次 4 秒）。

**子系统三：自适应文档切块与双存储**

知识库文档摄取时，`get_optimal_nodes()` 函数会根据文件类型自动选择切分策略：

| 文件类型 | 切块器 | 为什么这样选 |
|---------|--------|------------|
| Markdown (`.md`) | MarkdownNodeParser | 按标题层级切分，保留章节结构 |
| 面试题库、官方文档 | MarkdownNodeParser | 这类文档通常有标题结构 |
| JSON (`.json`) | JSONNodeParser | 保留 JSON 的嵌套层级 |
| Python (`.py`) | CodeSplitter(language="python") | 按函数/类定义切分 |
| 其他 | SentenceSplitter(chunk_size=1024) | 通用按句切分 |

为什么不统一用一种切块方式？因为 SentenceSplitter 对 Markdown 会破坏标题结构（一个章节可能被切成两半，下半段丢失标题上下文），对代码会在函数中间切断（生成不完整的代码片段）。自适应切块让每种格式都能保留其内在结构。

切完后的每个文本块会被存到两个地方：向量（Embedding 后的数字表示）存到 Milvus 做语义检索，原始文本和标签存到 PostgreSQL 做 BM25 关键词检索和元数据管理。这个"双存储"架构是混合检索（向量+关键词）的基础。

### c) 面试官可能的追问

**追问 1：为什么选 LlamaIndex 而不是 LangChain？**

参考回答：两者都是 LLM 应用框架，但侧重点不同。LlamaIndex 的核心优势在于 RAG 管线是一等公民——NodeParser（切块器）、VectorStoreIndex（向量索引）、QueryFusionRetriever（融合检索器）等组件开箱即用，而且抽象层级合适：既不过度封装（我可以自定义每一步的逻辑），又不需要从零构建。LangChain 的问题是抽象层级过深——Chain、Agent、Tool、Memory 等概念嵌套很深，调试时 stack trace 很长，出问题难定位。而且 LangChain 的 API 变动频繁，版本更新经常有 breaking change（破坏性变更）。不过项目的 ReAct Agent 在设计思路上借鉴了 LangChain 的 AgentExecutor，只是用了更轻量的自研实现。

**追问 2：Celery Worker 是同步的，你的服务层代码是异步的，怎么桥接？**

参考回答：这是一个经典的 sync-async 桥接问题。Celery 的任务函数只能是普通同步函数，但项目里的核心服务（音频转写、面试分析、文档摄取）都写成了异步函数，因为它们内部需要并发执行多个 IO 操作。解决方案是为每个 Worker 线程维护一个持久化的事件循环（event loop），存在 `threading.local()` 中。通过 `run_async(coro)` 函数调用 `loop.run_until_complete(coro)`，让同步的 Celery 任务能执行异步的服务函数。这比每次任务都用 `asyncio.run()` 更高效——`asyncio.run()` 每次都创建新循环再销毁，有额外开销。

**追问 3：WhisperX 和原始 Whisper 有什么区别？为什么不用云端的 Google Speech-to-Text？**

参考回答：WhisperX 在 Whisper 基础上增加了三个关键能力：第一，批处理支持（`batch_size=16`），能利用 GPU 并行计算多个音频片段；第二，强制对齐（Forced Alignment），把时间戳精确到词级别；第三，直接集成 Pyannote 的说话人分离。用原始 Whisper 的话，这些功能都要自己写。不用 Google Speech-to-Text 是因为：它需要调外部 API，有网络延迟和调用费用；且面试录音可能涉及敏感内容（薪资谈判等），本地处理更安全。

**追问 4：自适应切块的"自适应"体现在哪里？你怎么知道文件是什么类型？**

参考回答：通过两个维度判断：第一是文件扩展名（`.md`、`.py`、`.json` 等），第二是文档摄取时用户指定的 `source_type`（如 `interview_qa`、`official_docs`）。比如 `interview_qa` 类型的文档通常是面试题库，有 Markdown 标题结构，所以用 MarkdownNodeParser。如果配置了 LlamaParse 的 API Key，PDF/PPTX/DOCX 文件会先通过 LlamaParse 云端服务转成 Markdown（能保留表格和排版），再用 MarkdownNodeParser 切分。没有 API Key 的话就退回到 PyMuPDF 直接提取纯文本。

**追问 5：Milvus 和 PostgreSQL 各自存什么？为什么需要两个存储？**

参考回答：Milvus 存的是文本块经过 Embedding 模型转换后的向量（1024 维的浮点数数组），用于语义检索——通过计算向量距离找到语义上相似的内容。PostgreSQL 存的是文本块的原始文字和标签信息（user_id、source_type、document_id 等），用于 BM25 关键词检索和元数据管理。两者缺一不可：向量检索擅长理解语义（"持久化"和"数据落盘"是同义词），关键词检索擅长精确匹配（必须包含"ConcurrentHashMap"这个词）。两者融合后的效果比任何一个单独使用都好。

**追问 6：为什么用预签名 URL 上传文件？直接传给后端不行吗？**

参考回答：面试录音文件可能很大（几十到几百 MB）。如果所有文件都经过后端，会占用大量内存和网络带宽，影响其他用户的 API 请求响应速度。用预签名 URL 后，前端直接把文件传到 MinIO 对象存储，后端只需要生成一个临时上传地址（几百字节的 HTTP 请求），完全不承受文件传输的压力。而且这样后端可以无状态地水平扩展——因为它不存文件。

### d) 关键代码/配置定位

```
# FastAPI 应用入口
backend/app/main.py                    → lifespan()          # 启动顺序：Alembic迁移校验→模型加载→记忆回填→Reranker加载

# 音频转写与分析
backend/app/worker/tasks.py            → process_interview_analysis()  # Celery 任务入口
backend/app/services/transcription_service.py → transcribe_media()    # WhisperX 转写
backend/app/services/analysis_service.py      → analyze_interview()   # LLM 逐题评分

# 文档摄取
backend/app/worker/tasks.py            → process_document_ingestion()  # Celery 摄取任务
backend/app/rag/ingestion.py           → get_optimal_nodes()           # 自适应切块引擎
                                       → ingest_document()             # 完整摄取流程

# 配置
backend/app/core/config.py             → WHISPER_MODEL_ID = "Systran/faster-whisper-large-v2"
                                       → DIARIZATION_MODEL_ID = "pyannote-community/..."
                                       → EMBEDDING_MODEL_ID = "BAAI/bge-m3"
                                       → EMBEDDING_DIM = 1024
```

### e) 技术选型辩护

| 选了什么 | 放弃了什么 | 选择理由 |
|---------|-----------|---------|
| FastAPI | Flask / Django | 原生 async、Pydantic 校验、WebSocket/SSE 原生支持 |
| LlamaIndex | LangChain | RAG 组件成熟、抽象适中、API 稳定 |
| WhisperX | Google STT / 原始 Whisper | 本地部署零成本、集成说话人分离、批处理加速 |
| Celery | FastAPI BackgroundTasks | 独立进程、自动重试、持久化状态、不阻塞 API |
| Milvus | FAISS / Chroma / pgvector | 服务端 metadata 过滤（多租户隔离）、持久化、可扩展 |
| MinIO | 本地文件系统 | 前端直传、容器化友好、S3 兼容零迁移 |

### f) 常见翻车点

1. **把 LlamaIndex 说成"调包侠"**。LlamaIndex 只提供基础组件，项目中的自适应切块逻辑、防幻觉拦截、混合检索策略、BM25 缓存管理都是自研的。要强调"用了什么 + 在上面自己做了什么"。
2. **忘记说 Celery 的重试策略**。面试官很可能追问"任务失败了怎么办"。如果只说"用了 Celery 异步处理"但说不清重试逻辑（`autoretry_for`、指数退避、最大 3 次），会显得工程考虑不够。
3. **忽略安全层面**。文档摄取任务有三项安全检查（上传归属验证、用途验证、路径前缀验证），面试录音的上传 owner 必须和 interview owner 一致。这些细节体现工程素养。
4. **把 WhisperX 说成"调用 API"**。WhisperX 是本地部署的模型（`Systran/faster-whisper-large-v2`，约 3GB），不是云端 API。要强调这是在 Celery Worker 的 GPU 上本地推理。

---

## Bullet 3：混合检索链路与确定性 Chat Pipeline

> **简历原文**：设计 向量检索 + BM25 + BGE Reranker 混合检索链路，通过用户ID与资料源Type元数据过滤实现多用户多知识域隔离召回，并引入分数阈值与词法覆盖率抑制幻觉输出；结合查询规划器意图路由，将核心问答链路重构为确定性 Chat Pipeline，通过异步并发调度实现多知识源与长期记忆的并行检索。

### a) 30 秒讲解版

知识库检索不是简单地做一次向量搜索就完了。系统设计了一个五阶段的混合检索链路：先用向量检索和 BM25 关键词检索各自找一批候选文档，再用 RRF 算法把两个列表融合成一个排名，然后送入 BGE Reranker 精排，最后用绝对分数阈值拦截不相关的结果。如果知识库里确实没有答案，系统会告诉用户"没找到相关信息"，而不是让 AI 编造。整个问答链路是一个确定性的流水线——每个阶段做什么是固定的，只是 Query Planner 在运行时决定哪些阶段需要执行。

### b) 2 分钟深入版

这个 bullet point 有两个核心设计：混合检索链路和确定性 Chat Pipeline。

**混合检索链路的五个阶段**：

阶段 1 是连接 Milvus 向量搜索引擎，使用 HNSW 索引（一种基于图的近似最近邻搜索算法，查询速度快、召回率高）。阶段 2 是构建多租户隔离过滤器——把当前用户的 `user_id` 注入到 Milvus 查询条件中，让 Milvus 在搜索向量时就排除不属于当前用户的数据。这个过滤发生在服务端，不是检索后再过滤。阶段 3 是构建 BM25 关键词检索器——从 PostgreSQL 加载当前用户的文档块，在应用层构建 BM25 索引。索引按 `user_id|source_type` 键缓存 300 秒，有线程锁保护。

阶段 4 是融合排序——向量检索和 BM25 各自返回一个排名列表，但分数尺度完全不同。RRF（互逆排序融合）算法解决了这个问题：它不看分数只看排名位置，奖励在两个检索器中都排名靠前的文档。融合后再送入 BGE Reranker（一个专门判断"问题和文档是否真正相关"的深度学习模型）做精排。

阶段 5 是防幻觉拦截——这是最关键的工程设计。有三层防线：第一层是 Reranker 绝对分数阈值（0.5），低于这个分数的文档直接过滤掉；第二层是词法覆盖 Fallback，如果 Reranker 分数都低于阈值但有文档的关键词覆盖率超过 35%，仍然放行（防止某些领域 Reranker 系统性偏低导致误拦截）；第三层是 SYSTEM_EMPTY_WARNING 标记，如果前两层都没放行任何文档，在回答的上下文中标记"知识库没有相关信息"，提示大模型不要编造。

**确定性 Chat Pipeline**：

普通问答不走 ReAct Agent，而是走一个固定阶段的流水线。核心思路是：让 Query Planner（查询规划器）在运行时决定"做什么"，但"怎么做"的步骤是固定的。

9 个阶段：确保会话存在 → 读取轻量上下文 → Query Planner 规划意图 → 并发召回记忆和知识库 → 组装完整上下文 → 选择 LLM 和提示词 → 流式回答 → 写入对话记录 → 异步执行 post-turn maintenance。

为什么叫"确定性"？因为每个阶段的执行顺序是固定的，不会像 ReAct Agent 那样由模型自由决定下一步做什么。这让行为可预测、可调试。但它又不是完全硬编码——Planner 会动态决定是否需要检索知识库、检索哪些源、是否需要召回记忆。

并发调度体现在第 4 步：记忆召回和知识库检索用 `asyncio.create_task` 并发执行（两者互不依赖，数据源完全不同），减少约 40% 的等待时间。注意：这里的并发检索 task 是 awaited 的（即主流程会等待结果返回），而第 9 步的 post-turn maintenance（Compaction + Interview State 更新 + Memory 抽取）使用的是 `safe_background_task()`——这是项目封装的一个安全后台任务调度器，基于 `asyncio.create_task()` 但增加了三层保障：用全局集合持有任务的强引用防止垃圾回收器意外回收、通过回调自动捕获并记录异常、应用关停时统一排空所有挂起的后台任务。

### c) 面试官可能的追问

**追问 1：为什么不直接用纯向量检索？加 BM25 有什么好处？**

参考回答：纯向量检索有一个致命弱点：它只看语义相似度，不看关键词精确匹配。比如用户问"HashMap 和 ConcurrentHashMap 的区别"，向量检索可能返回"Java 集合框架概述"这篇文章（因为语义空间里它们很接近），但里面可能根本没提到 ConcurrentHashMap 这个词。BM25 能精确匹配这个关键词，把包含它的文档拉回来。向量擅长语义理解（"持久化"和"数据落盘"是同义词），BM25 擅长精确匹配。两者融合后的效果比单独使用任何一个都好，这在 RAG 文献中叫 Hybrid Search，是业界公认的最佳实践。

**追问 2：RAG_MIN_SCORE 为什么设成 0.5？**

参考回答：0.5 是 BGE Reranker 的绝对分数阈值，通过实际数据校准确定的。BGE Reranker 的输出范围是 0 到 1，0.5 以上通常表示 query 和 document 在语义上确实相关。实测中发现，0.5 以下的文档大多是表面相似但实际无关的噪声。这个阈值不是相对排名，而是绝对质量线——即使只检索到一个文档，只要它的分数低于 0.5，也会被拦截。这是"宁愿说不知道也不编造"的设计思路。

**追问 3：词法覆盖 Fallback 是什么？为什么需要它？**

参考回答：词法覆盖 Fallback 是防幻觉机制的第二层防线。有些领域的文档（比如某些中文面试题），Reranker 可能系统性地给出偏低的分数，导致明明相关的文档被 0.5 的阈值误拦截。Fallback 机制会检查被拦截文档的关键词覆盖率——如果 query 中至少 35% 的关键词出现在了文档中，说明它们在词法上有较强的关联性，这种文档会被 Fallback 机制放行。这是一个"安全网"，防止 Reranker 的偏差导致有价值的文档被错误丢弃。

**追问 4：RRF 算法的 k=60 常数是什么意思？**

参考回答：RRF 的公式是 `score = Σ 1/(k + rank)`，k 是一个平滑常数。k 越大，排名差异带来的分数差异越小——排名第 1 和第 5 的分数差距更小，相当于"更民主"（每个检索器的贡献更均匀）。k 越小，排名靠前的文档获得的分数优势越大——排名第 1 的分数远高于第 5，相当于"赢者通吃"。k=60 是 RRF 论文推荐的默认值，在大多数检索场景中表现稳定。

**追问 5：确定性 Pipeline 和 ReAct Agent 什么时候用哪个？**

参考回答：90% 以上的普通问答走确定性 Pipeline——因为它更快（不需要多轮工具调用）、更可控（每个阶段做什么是固定的）、更便宜（只调一次 LLM）。只有当 Query Planner 判断任务需要工具调用时（比如"帮我搜索 OpenAI 的后端岗位"），才会路由到 ReAct Agent。Planner 的 `answer_mode` 字段控制这个路由：`knowledge_qa`、`direct_chat`、`interview_learning` 走 Pipeline；`agent_tool_call` 走 Agent。

**追问 6：BM25 的缓存策略是怎么设计的？**

参考回答：BM25 索引按 `user_id|source_type` 键缓存，TTL 300 秒。缓存命中后构建耗时 <1ms，未命中时需要从 PostgreSQL 加载节点并构建索引，约 500ms。缓存有线程锁保护（防止多个并发请求同时构建同一个索引）。当用户上传新文档后，对应的缓存键会被主动失效，下次检索时重新构建。

### d) 关键代码/配置定位

```
# 混合检索
backend/app/rag/retriever.py           → HybridRetriever: _build_bm25_retriever(), _vector_query(), _hybrid_rerank()
backend/app/rag/ingestion.py           → ingest_document(): 自适应切块 + Milvus/Docstore 写入
                                       → EMBEDDING_MODEL_ID = "BAAI/bge-m3"
                                       → EMBEDDING_DIM = 1024

# 确定性 Pipeline
backend/app/agent/agent_executor.py    → stream_chat_with_agent(): 9 阶段流水线入口
backend/app/agent/planner.py           → plan_query(): Query Planner + QueryPlan 模型
backend/app/services/context_service.py → assemble_rewrite_context(), assemble_answer_context()

# 防幻觉配置
RAG_MIN_SCORE = 0.5                    → Reranker 绝对分数阈值
RAG_FALLBACK_MIN_SCORE = 0.02          → RRF 分数回退阈值
RAG_LEXICAL_FALLBACK_MIN_OVERLAP = 0.35 → 词法覆盖率 fallback 阈值
```

### e) 技术选型辩护

| 选了什么 | 放弃了什么 | 选择理由 |
|---------|-----------|---------|
| Milvus (HNSW) | FAISS / pgvector | 原生 metadata 过滤、持久化、多租户隔离 |
| BGE Reranker (本地) | Cohere Reranker (云端) | 零 API 调用成本、零网络延迟、中文效果好 |
| 应用层 BM25 | Elasticsearch | 零额外基础设施、毫秒级构建、天然多租户 |
| 绝对分数阈值 | Top-K 相对排名 | 防止知识库没答案时返回不相关内容 |

### f) 常见翻车点

1. **只说"用了混合检索"但讲不清楚为什么**。要用具体例子（如 HashMap vs ConcurrentHashMap）说明向量和 BM25 各自的盲区以及为什么需要融合。
2. **把 RRF 说成"加权平均"**。RRF 不看分数只看排名，这是它的核心特点。如果说成加权平均，面试官会追问"两个检索器的分数尺度不同怎么加权"，答不上来会很尴尬。
3. **忽略防幻觉设计**。这是整个检索链路中最有工程价值的部分。很多 RAG 系统只有向量检索+Top-K，没有绝对分数过滤。要重点强调"宁愿说不知道也不编造"的设计思路。
4. **"确定性 Pipeline"说成"写了一堆 if-else"**。要强调 Planner 是用 LLM 在运行时做意图判断的（不是硬编码规则），只是执行阶段是固定的。

---

## Bullet 4：ReAct Agent 与长期记忆架构

> **简历原文**：针对岗位选择与准备等复合任务，基于 Function Calling 构建独立 ReAct Agent 链路，并通过参数校验、多维预算熔断提升运行稳定性与安全性。设计四类长期记忆架构，经结构化上下文组装与Working State 压缩控制 Token 开销，通过独立记忆向量索引与四因素加权融合召回实现跨会话长期记忆。

### a) 30 秒讲解版

对于需要工具调用的复杂任务（比如"帮我找 OpenAI 的后端岗位，结合我的经历给准备建议"），系统有一个独立的 ReAct Agent——它让大模型自主决定调用什么工具、传什么参数、什么时候给出最终答案。为了防止 Agent 失控，设计了六维预算控制（步数、工具调用次数、token、时间、单工具频次、观测长度）。另外系统有四类长期记忆，存在独立的 Milvus 向量集合中，用一个四因素加权公式（语义相似度 + 关键词匹配 + 重要性 + 新旧程度）来召回最相关的记忆。

### b) 2 分钟深入版

这个 bullet point 包含两个子系统：ReAct Agent 和长期记忆。

**ReAct Agent 的设计**：

ReAct 的全称是 Reasoning + Acting（推理 + 行动）。它的核心循环是：模型思考下一步该做什么 → 调用工具获取信息 → 把工具结果反馈给模型 → 模型继续思考 → 直到给出最终答案。

项目从早期的"正则解析 JSON"重构为 OpenAI Function Calling 协议。老方案是让模型在回答中输出特定格式的 JSON，然后用正则提取。问题是模型经常输出格式错误的 JSON（多余逗号、缺少引号），正则解析很脆弱。新方案中，模型直接通过 API 返回结构化的 `tool_calls` 对象，参数再经过 Pydantic 模型校验（检查类型、长度、范围），校验失败的错误信息会反馈给模型让它修正。

六维预算控制（AgentBudget）是防止 Agent 失控的关键设计：

- 最大步数 8：防止推理陷入无限循环
- 最大工具调用 16：防止总调用次数失控
- 最大 token 32000：防止成本失控
- 最大运行时间 90 秒：防止用户等太久
- 单工具最大调用 6：防止对同一个工具死循环
- 观测结果字符限制 6000：工具返回结果太长时截断

每次循环前都检查所有预算维度，任何一个超限就强制停止并输出当前已有的信息。

**长期记忆系统**：

系统有四类记忆：`user_profile`（用户画像，如"有 3 年 Java 经验"）、`interaction_preference`（交互偏好，如"喜欢简洁回答"）、`feedback_rule`（反馈规则，如"代码示例用 Python"）、`project_reference`（项目背景，如"正在做推荐系统"）。

记忆的生命周期：对话结束后，post-turn maintenance 异步调用 LLM 从新对话中抽取候选记忆 → 置信度低于 0.65 的丢弃 → 用 `normalized_key`（归一化后的合并键）做去重：如果已存在同键记忆则合并（content 用新值覆盖，importance 取旧值和新值的最大值）→ 写入 PostgreSQL → 异步写入独立的 Milvus memory collection。

记忆召回用的是 HybridRetriever，打分公式：`0.6×向量相似度 + 0.35×关键词匹配 + 0.15×重要性 + 0.05×时间新旧`。权重的设计思路：向量相似度最重要（找语义相关的记忆），关键词匹配补充精确性，重要性确保高价值记忆优先，时间新旧给最小权重（避免新记忆大幅压过旧但重要的记忆）。

上下文管理方面：当对话太长时，Compaction 机制把旧消息压缩成结构化的 Working State（包含目标、阶段、已覆盖主题和摘要）。TokenBudgeter 给三类上下文分配独立预算：近期对话 4000 tokens、知识片段 5000 tokens、长期记忆 1600 tokens。PromptRenderer 按最优顺序渲染：System Rules → Working State → Interview State → 记忆 → 知识 → 近期对话 → 当前问题。

### c) 面试官可能的追问

**追问 1：为什么 Agent 要有六个维度的预算控制？不能只限制步数吗？**

参考回答：因为不同类型的资源失控表现不同。步数限制能防止无限循环，但如果模型在一步里连续调 10 次工具呢？步数只算 1 但工具调用了 10 次。如果工具返回了一个超长的结果（比如完整的岗位描述），可能一次就消耗了大量 token。如果某个工具调用卡在网络超时上，步数和 token 都没超但用户已经等了很久。六个维度的每一个都针对不同类型的失控场景，缺一不可。

**追问 2：normalized_key 是怎么实现去重合并的？**

参考回答：LLM 在抽取记忆时，除了生成内容，还会生成一个语义化的 key（比如"prefer_concise_answers"）。这个 key 经过正则处理——转小写、去标点、空格替换为下划线。然后用 `user_id + memory_type + normalized_key` 三元组作为唯一键查找数据库。如果已经存在同键记忆，就做合并：content 用新值覆盖（因为新的可能更准确），importance 取新旧值中较大的那个（保守策略，防止偶然的低置信度更新降低一条本来很重要的记忆的优先级）。

**追问 3：HybridRetriever 的四个权重是怎么确定的？**

参考回答：通过实测调参。向量相似度给 0.6 最高权重是因为它是找到语义相关记忆的核心信号。关键词匹配给 0.35 是为了纠正向量检索偶尔出现的"语义漂移"——找到向量空间距离近但实际不相关的结果。重要性给 0.15，让高价值记忆更容易被召回但不压过相关性。时间新旧只给 0.05，因为最近的记忆不一定比旧记忆更重要（"有 5 年 Java 经验"这个记忆可能是很久以前记录的，但一直很重要）。

**追问 4：Working State 的 Compaction 是怎么触发的？**

参考回答：当 Working State 的 token 数加上未压缩的新消息 token 数超过 5000 时触发。执行时保留最近 6 条消息（3 轮对话）不压缩——因为模型需要看到原始对话才能保持连贯性。更早的消息和当前 Working State 一起发给 LLM，输出新的结构化摘要。压缩后，十轮对话前的内容从原始消息变成了约 500 tokens 的摘要，极大节省了上下文空间。

**追问 5：为什么记忆用独立的 Milvus collection 不和知识库共用？**

参考回答：四个原因。语义空间不同——记忆是短句事实，知识库是长段文档，向量分布特征不同。生命周期不同——知识库是静态的，记忆是每轮对话都可能更新的。标签结构不同——知识库节点的标签包含 source_type 和 document_id，记忆的标签包含 memory_type 和 importance。排序算法不同——知识库用 RRF+Reranker，记忆用四因素加权。混在一起会互相干扰且难以独立调参。

### d) 关键代码/配置定位

```
# ReAct Agent
backend/app/agent_runtime/react_agent.py → run_react_agent()     # 主执行循环
backend/app/agent_runtime/tools.py       → TOOL_REGISTRY          # 工具注册表
                                         → get_all_tool_schemas()  # 导出工具 JSON Schema
backend/app/agent_runtime/react_agent.py → AgentBudget            # 六维预算控制（定义在 react_agent.py 中）

# 长期记忆
backend/app/services/memory_extraction_service.py → MemoryExtractionService.extract_and_persist()  # 抽取+持久化
backend/app/services/memory_extraction_service.py → MemoryRetrievalService.recall_relevant()       # 混合召回（同文件）
backend/app/services/memory_vector_service.py     → upsert_memory_vector() # 向量写入

# 上下文管理
backend/app/services/context_service.py   → ContextAssemblyPipeline  # 上下文组装
                                          → TokenBudgeter            # 分层 token 预算
                                          → PromptRenderer           # 分层渲染
backend/app/services/memory_extraction_service.py → CompactionService  # Working State 压缩（同文件）

# 关键参数
MIN_CONFIDENCE = 0.65                     # 记忆抽取最低置信度
COMPACTION_THRESHOLD_TOKENS = 5000        # Compaction 触发阈值
KEEP_LAST_MESSAGES = 6                    # Compaction 保留最近消息数
MEMORY_FINAL_TOP_K = 3                    # 最终保留的记忆数
```

### e) 技术选型辩护

| 选了什么 | 放弃了什么 | 选择理由 |
|---------|-----------|---------|
| Function Calling | 正则解析 JSON | 结构化输出、自动参数校验、错误反馈 |
| Pydantic 工具参数校验 | 手动 dict 检查 | 类型安全、自动错误信息、schema 自动导出 |
| 独立 Memory Collection | 共用 RAG Collection | 语义空间/生命周期/调参隔离 |
| 四因素加权召回 | 纯向量 Top-K | 综合考虑相关性、重要性和时效性 |

### f) 常见翻车点

1. **把 ReAct 说成"Chain of Thought"**。ReAct 的核心是 Reasoning + Acting（推理+行动），不只是思维链。要强调"模型自主决定调用什么工具"这个 Acting 环节。
2. **六维预算控制说不清每个维度的理由**。不要只列出六个数字，要能说清每个维度防的是什么类型的失控。面试官可能追问"为什么最大步数是 8 而不是 5？"——因为典型复杂任务需要 4-5 步，8 给了余量同时防止无限循环。
3. **记忆系统只说"能记住用户信息"**。要具体说清楚四类记忆分别是什么、抽取流程是怎样的、confidence 阈值为什么是 0.65、normalized_key 怎么做去重合并。
4. **ContextBundle 和直接拼字符串搞混**。要强调 ContextBundle 是结构化的中间表示——各服务往里填内容，PromptRenderer 负责按最优顺序渲染。这比直接拼字符串多了分层预算控制、来源标注、排序调整和去重的能力。

---

## Bullet 5：评估指标与系统性能

> **简历原文**：在检索与生成效果评估上，835 条样本测试中 Hit Rate@3 达 99.9%、MRR@5 达 0.990，P95 检索延迟 98ms；基于 RAGAS 在 50 条样本上验证系统忠实度 94.5%、上下文精确度 95.2%、上下文召回率 100%，首字响应延迟约0.8s，端到端 P95 响应约 5.0s。

### a) 30 秒讲解版

系统的检索和生成质量有两套独立的评测体系。检索侧用 835 条黄金数据集评测，衡量的是"给定一个问题，知识库能不能找到正确答案"——结果是 99.9% 的情况下正确文档出现在前 3 个结果中，MRR@5 达到 0.990 说明正确文档几乎总是排在第 1 位。P95 检索延迟仅 98ms。生成侧用 RAGAS v0.4.3 框架在 50 条端到端样本上评测，忠实度 94.5%、上下文召回率达到 100%。首字响应延迟约 0.8 秒，端到端 P95 响应约 5.0 秒。

### b) 2 分钟深入版

评测分为两个维度：检索质量评测和生成质量评测。

**检索质量评测**（`evaluation/test_retrieval_quality.py` + `evaluation/eval_runner.py`）：

这个评测回答的是：给定一个用户问题，混合检索链路能不能从知识库中找到包含正确答案的文档？

准备工作：构建 835 条黄金数据集（`golden_dataset.jsonl`），每条记录包含 query、reference_answer、user_id、source_type 等字段。数据集覆盖了面试知识、技术文档、个人复盘等多种知识源。

两个核心指标：

- **Hit Rate@3**（命中率）= 99.9%。含义是：在 835 个测试问题中，99.9% 的情况下，正确文档至少出现在了检索结果的前 3 名中。几乎不存在漏检的情况。
- **MRR@5**（Mean Reciprocal Rank，平均倒数排名）= 0.990。MRR 衡量的是"第一个正确结果排在第几位"——0.990 接近满分 1.0，意味着正确文档几乎总是排在第 1 位。

**P95 检索延迟 98ms**：即 95% 的检索请求在 98ms 以内完成。包含 Milvus 向量检索 + BM25 构建/缓存命中 + RRF 融合 + Reranker 精排的全流程。相比迁移前的 144ms 有显著提升，主要得益于 BGE-M3 向量质量更高带来的 Reranker 精排效率提升。

**生成质量评测**（基于 RAGAS v0.4.3 框架）：

RAGAS（Retrieval Augmented Generation Assessment）是一个专门评估 RAG 系统端到端质量的开源框架。它不是简单地看"回答对不对"，而是从多个维度评估。在 50 条端到端样本上的结果：

- **忠实度（Faithfulness）= 94.5%**：AI 的回答中有多少内容是基于检索到的文档的，而不是自己编造的。94.5% 意味着几乎所有声明都能在检索上下文中找到依据。
- **上下文精确度（Context Precision）= 95.2%**：检索到的文档中有多少比例是和问题真正相关的。95.2% 意味着检索到的 5 个文档中约 4.8 个是有用的，极少有无关噪声。
- **上下文召回率（Context Recall）= 100%**：正确答案需要的信息，全部被检索到了。这是混合检索（向量 + BM25）+ BGE-M3 高质量向量带来的效果。

**响应延迟**：

- **首字响应延迟（TTFT）约 0.8s**：用户发出问题后约 0.8 秒就能看到第一个回答字符开始出现。这包括 Query Planner 调用 + 并发检索 + 上下文组装的全部耗时。
- **端到端 P95 响应约 5.0s**：95% 的请求在 5 秒内完成全部回答生成。相比迁移前的平均 8.2 秒有显著改善，主要得益于检索延迟降低和流式输出优化。

### c) 面试官可能的追问

**追问 1：Hit Rate 从 91% 提升到 99.9%，主要做了什么优化？**

参考回答：核心提升来自 Embedding 模型从 `bge-small-zh-v1.5`（512 维）迁移到 `BGE-M3`（1024 维）。BGE-M3 的 1024 维向量在语义表达上显著更强，尤其是对中英混合术语（如"Redis 的 AOF 持久化"）的编码质量更高。此外 BGE-M3 支持 8192 tokens 的输入长度，文档切块可以更完整地被编码，减少了因切块过长导致的语义截断问题。检索链路本身（BM25 + RRF + Reranker + 防幻觉拦截）没有大的变动，说明 Embedding 模型的质量对检索效果有决定性影响。

**追问 2：RAGAS 的评测是怎么做到自动化的？谁来判断"忠实度"？**

参考回答：RAGAS v0.4.3 框架使用 LLM-as-Judge（用大模型来做评审员）的方式实现自动化评测。具体来说：给定一个 (query, retrieved_context, generated_answer, reference_answer) 四元组，RAGAS 会把它们发给一个评审 LLM，让评审 LLM 判断回答中的每个声明（claim）是否可以在 retrieved_context 中找到支撑。如果 20 个声明中有 19 个有支撑，忠实度就是 95%。

**追问 3：端到端 P95 响应 5.0 秒，还能继续优化吗？**

参考回答：可以，主要从三个方向。第一，模型层面：换用更快的推理引擎（如 vLLM）或使用更小的模型。DeepSeek V4 Flash 比标准版快约 40%。第二，并发优化：当前 Planner 和检索是串行的（先 Planner 再检索），可以做投机执行——在 Planner 运行的同时预先启动检索，如果 Planner 结果表明不需要检索再丢弃结果。第三，缓存：对于高频问题可以缓存检索结果。5.0 秒中约 3.5 秒是 LLM 流式生成时间，这是受限于模型速度和回答长度的，优化空间有限。

**追问 4：835 条测试样本是怎么构建的？**

参考回答：黄金数据集（`golden_dataset.jsonl`）有两种构建方式。一种是通过评测脚本从知识库中自动构建——让 LLM 基于文档内容生成多样化的问题和参考答案。另一种是手动编写的典型场景和 Bad Case，确保边界情况被覆盖（如中英混合术语、跨切块答案、知识库中不存在的问题）。数据集按 layer 字段标记适用的评估层级（retrieval / generation / trajectory），支持分层独立评测。

**追问 5：为什么用 MRR 而不是 nDCG 作为排名指标？**

参考回答：MRR（Mean Reciprocal Rank）衡量的是"第一个正确结果排在第几位"，更直观且与 RAG 场景匹配——RAG 系统最关心的是"能不能最快找到一个相关文档"。nDCG 考虑了多个相关结果的排名和相关性等级，适合搜索引擎场景（用户会浏览多个结果）。在 RAG 中，检索到的前几个文档都会被注入 LLM 的上下文，MRR@5 = 0.990 说明正确文档几乎总是排在第 1 位，检索质量非常高。

**追问 6：这些指标是在什么数据上测的？有没有过拟合的风险？**

参考回答：评测数据集在每次知识库更新后定期重新生成一部分，避免固定在同一批数据上反复调参。同时数据集包含了不同 source_type（interview_qa、official_docs 等）和不同难度的问题，覆盖面较广。过拟合的主要缓解方式是：调参时保留一部分测试集不参与调参过程，并且关注指标在新增数据上的泛化表现。

### d) 关键代码/配置定位

```
# RAG 评测
evaluation/test_retrieval_quality.py   → 检索质量评测（Hit Rate、MRR、nDCG、延迟）
evaluation/test_generation_quality.py  → 生成质量评测（RAGAS Faithfulness、Precision、Recall）
evaluation/eval_runner.py              → CLI 评测入口（支持 --layer、--limit、--report）
evaluation/golden_dataset.jsonl        → 835 条黄金数据集

# Agent 评测
evaluation/test_agent_trajectory.py    → Agent 轨迹评测（routing accuracy 等）
backend/app/services/agent_trace_service.py → aggregate_trajectory_metrics()

# 测试套件
backend/tests/                         → 81 项自动化测试
pytest.ini                             → markers: slow, integration

# 关键延迟参数
RAG_MIN_SCORE = 0.5                    # 影响检索精确率
RERANK_TOP_N = 5                       # 影响 Reranker 耗时
VECTOR_TOP_K = 8                       # 影响向量检索耗时
```

### e) 技术选型辩护

| 选了什么 | 放弃了什么 | 选择理由 |
|---------|-----------|---------|
| RAGAS v0.4.3 框架 | 纯人工评测 | 自动化、可重复、多维度指标 |
| LLM-as-Judge | 基于规则匹配 | 能评估语义级别的忠实度和相关性 |
| Hit Rate + MRR | 仅 Top-K 准确率 | MRR 直观衡量排名质量，与 RAG 场景匹配 |

### f) 常见翻车点

1. **说不清 Hit Rate 和 MRR 的区别**。Hit Rate 只看"有没有找到"，MRR 还看"排在第几位"。如果混为一谈，面试官会追问。
2. **把 RAGAS 的指标说成"自己算的"**。RAGAS 是标准的开源框架，有学术论文支撑。要说明"基于 RAGAS v0.4.3 框架评测"，增加可信度。
3. **端到端响应时间说不清瓶颈在哪**。5.0 秒中大部分是 LLM 流式生成时间，不是检索慢（P95 检索仅 98ms）。如果面试官问"为什么这么慢"，答"检索有问题"就错了。
4. **评测数据来源说不清**。面试官可能追问"这 835 条测试样本哪来的"。要说明有自动构建和手动 Bad Case 两种来源，且按 layer 字段支持分层评测。
5. **忽略评测的局限性**。主动提一下：这些指标是离线评测的结果，线上实际使用中可能因为用户问法多样而有偏差。这体现了对评测方法论的理解深度。

---

## 面试策略建议

### 推荐讲解顺序

- **先讲 Bullet 1（项目定位）**：让面试官快速理解你做的是什么、解决什么问题。30 秒就够。
- **再讲 Bullet 3（混合检索 + Pipeline）**：这是技术含量最高的部分，趁面试官注意力集中时讲。重点展示防幻觉三重防线和确定性 Pipeline 的设计理念。
- **接着讲 Bullet 4（Agent + 记忆）**：承接 Pipeline，展示系统的另一条执行路径（ReAct Agent）和跨会话能力（长期记忆）。六维预算控制和四因素加权是亮点。
- **然后讲 Bullet 2（框架 + 音频 + 文档）**：这是基础设施层面的内容，如果前面讲得好，面试官可能会主动问框架选型和音频处理。如果时间不够可以简化。
- **最后讲 Bullet 5（评测）**：用数据说话，给前面的架构讲解做收尾。注意不要只报数字，要说清指标的含义和局限性。

### 一句话版本（适合简历初筛或简短自我介绍）

> "我做了一个面试准备的 AI 助手系统。它有几个核心能力：第一，混合检索——同时用向量搜索和关键词搜索找知识库里的内容，然后用 Reranker 精排，还有三层防幻觉机制确保不会编造；第二，长期记忆——系统能记住用户的技术背景和偏好，跨会话使用；第三，语音录音分析——上传面试录音后自动转写、分离说话人、逐题评分。整个系统用 FastAPI + LlamaIndex + Milvus + PostgreSQL + Celery 构建，Docker Compose 部署，有 81 项自动化测试和完整的 CI/CD 管线。在 835 条样本上 Hit Rate@3 达到 99.9%，RAGAS 忠实度 94.5%。"

### 应对"套壳 ChatGPT"质疑的三层防线

当面试官问"这不就是调 ChatGPT 的 API 吗"，按以下层次回应：

**第一层（能力差异层）**："ChatGPT 没有知识库检索能力——它不知道我的面试笔记里写了什么。系统的核心是一个混合检索管线（Milvus 向量检索 + BM25 关键词检索 + BGE Reranker 精排 + 三层防幻觉拦截），这些是 ChatGPT 完全不具备的。ChatGPT 也没有长期记忆——每次对话都从零开始，不知道我之前说过什么。系统的四类长期记忆（用户画像、交互偏好、反馈规则、项目背景）让每次对话都基于之前的积累。"

**第二层（工程设计层）**："系统的核心价值在于工程设计。防幻觉三重防线（Reranker 绝对分数阈值 + 词法覆盖 Fallback + 空结果标记）、多租户四层隔离（API 鉴权 + 向量 metadata 过滤 + 节点标签注入 + ORM 查询过滤）、HybridRetriever 四因素打分公式、AgentBudget 六维资源控制——这些都是基于具体业务场景的工程方案，不是调 API 能解决的。"

**第三层（质量保障层）**："套壳产品没有可观测性和质量保障。系统有 Agent Trace 全量遥测（记录每次执行的每一步操作），有 RAG 评测验证检索准确率（Hit Rate 99.9%），有 RAGAS 验证生成质量（忠实度 94.5%），有 81 项自动化测试覆盖核心路径。这些都是生产级系统必需的工程能力。"

### 最重要的数字（随时能脱口而出）

**检索性能**：

- "835 条样本，Hit Rate@3 = 99.9%，MRR@5 = 0.990"
- "P95 检索延迟 98ms（含向量检索 + BM25 + Reranker）"
- "BM25 缓存命中后构建耗时 < 1ms，未命中时约 500ms"

**生成质量**：

- "RAGAS 忠实度 94.5%，上下文精确度 95.2%，上下文召回率 100%"
- "首字响应延迟约 0.8 秒，端到端 P95 约 5.0 秒"

**系统规模**：

- "Compaction 后，十轮对话从 ~3000 tokens 压缩到 ~500 tokens"
- "Agent 预算上限：8 步、16 次工具调用、32000 tokens、90 秒"

### 如何在追问中自然展示工程能力

**原则：不堆技术名词，讲"为什么"和"取舍"**

❌ 不好的回答："我用了 HNSW 索引，参数是 M=16, efConstruction=200, efSearch=64。"
✅ 好的回答："Milvus 的向量索引选了 HNSW。M=16 是每个节点的最大连接数——越大索引越稠密、召回率越高，但内存也越大。16 是 Milvus 推荐的默认值，在万级数据量下内存完全可接受。efSearch=64 是查询时的搜索宽度——64 实测能达到约 95% 的召回率，延迟 10ms 以内。如果需要更高召回率可以调到 128，但延迟会翻倍。"

**原则：主动说降级策略**

每当提到一个组件，主动说"如果它挂了怎么办"：

- "Reranker 如果不可用，自动降级到纯 RRF 排序，阈值同步调整。"
- "Milvus 不可用时，知识库降级为纯 BM25 检索，记忆降级为词法召回。"
- "Planner 失败时，自动 fallback 到默认计划（检索所有源、直接回答）。"

这比任何技术名词都更能展示工程素养——因为它说明你在设计时就考虑了失败场景，不是只关心 happy path。

**原则：用数字支撑论点**

不要只说"很快"或"很高"，用具体数字：

- "P95 检索延迟 98ms（含向量检索 + BM25 + Reranker）"
- "BM25 缓存命中后构建耗时 < 1ms，未命中时约 500ms"
- "Compaction 后，十轮对话从 ~3000 tokens 压缩到 ~500 tokens"
- "Agent 预算上限：8 步、16 次工具调用、32000 tokens、90 秒"

---

*本文档基于项目代码库和简历内容撰写。所有技术细节、参数值和代码定位均可溯源到具体源文件。最后校准：2026-05-03，基于 BGE-M3 迁移后的代码库状态。*
