# Interview Copilot 项目详尽技术文档

> 本文档面向基础较薄弱的开发者。读完它，你应该能完整理解 Interview Copilot 的全部模块、流程、参数选择和工程取舍。所有专业术语在第一次出现时都会从零解释，所有流程都用"当用户做了 X，系统首先…然后…接着…"的叙事方式走一遍。

---

## 目录

1. [项目总览](#一项目总览)
2. [链路一：RAG 知识问答链路](#二链路一rag-知识问答链路)
3. [链路二：Agent Harness 智能体](#三链路二agent-harness-智能体)
4. [记忆系统](#四记忆系统)
5. [模拟面试系统](#五模拟面试系统)
6. [录音分析系统](#六录音分析系统)
7. [文档摄入与知识库](#七文档摄入与知识库)
8. [模型路由与注册](#八模型路由与注册)
9. [评测体系](#九评测体系)
10. [工程基础设施](#十工程基础设施)

---

## 一、项目总览

### 1.1 这个模块解决什么问题

求职者准备技术面试时面临一个尴尬的现实：知识复习、模拟练习、复盘反思这三件事被切分到三种工具里。背面试题 (八股) 用题库 App，模拟练习要找朋友陪练，复盘只能靠手写笔记。三个环节彼此不联通，候选人没办法在一个统一的工作台上，让"复习—练习—复盘"形成闭环。

Interview Copilot 解决的就是这件事。它把"知识库问答""录音分析""AI 模拟面试""复杂任务的 Agent 智能助理"四种能力都收拢到同一套后端、同一个前端工作台里。所有用户上传的资料（简历、面经 PDF、面试录音）和系统沉淀的记忆（用户的技术栈、面试习惯、薄弱点）都被串成一条主线，让每一次提问都能带上历史背景，每一次模拟面试结束都能进入对应的复盘会话，每一次复盘的关键结论都能被记忆系统记住、在下一次模拟中被自动调用。

**目标用户**：正在准备技术面试的开发者。其中尤其适合两类人：一类是基础八股需要反复练习与查漏补缺的应届/转行候选人，一类是希望系统化复盘真实面试录音的在职跳槽者。

### 1.2 系统支持的四大核心能力

**① 知识问答**：用户在对话框里问"Redis 的持久化机制有哪些？"，系统从用户事先上传的面经/官方文档/技术笔记里检索相关片段，让大语言模型基于这些片段回答。这一条路径走的是"RAG 链路"。

**② 录音分析**：用户上传一段真实面试录音（mp3/wav/m4a），系统在后台用语音识别模型把声音转成文字，自动区分面试官与候选人，把整段录音切成 QA 对，逐题打分，并形成一份完整的复盘报告。

**③ 模拟面试**：AI 扮演面试官，根据用户简历生成五阶段的结构化面试计划（自我介绍 → 简历深挖 → 技术八股 → 行为面试 → 反问），逐题提问、根据答案动态决定追问或推进、面试结束后批量打分，并自动创建一个复盘会话让用户继续与 AI 讨论薄弱点。

**④ Agent 智能任务**：用户提出复杂指令，比如"帮我看一下这个 JD 和我简历的差距，再给我列一份两周备战计划并保存为 Markdown 文件"。系统会启动一个能够自主推理、调用多种工具的 Agent（智能体），它会自己决定先读简历、再搜 JD、再搜索面经、最后写文件，整个推理过程实时推送给前端。

### 1.3 整体架构总览：双链路设计

系统在 API 层面就把上述四件事拆成了两条并行的处理管线，称为"双链路"。

> **链路一：RAG 链路**——对应"知识问答""模拟面试中的对话""复盘对话"这些"对话式"场景。入口是 `POST /api/v1/agent/chat` 或 `POST /api/v1/chat/sse/{session_id}`。
>
> **链路二：Agent Harness 链路**——对应"Agent 智能任务"这种需要多步推理、多次工具调用的复杂场景。入口是 `POST /api/v1/agent/react/stream`。

**为什么要分成两条链路？** 这两类需求的行为模式完全不同。RAG 链路追求"响应快、结果稳"——用户问八股、用户和 AI 聊天，希望几百毫秒就能看到第一个字蹦出来，希望回答不会出现"AI 突然去搜网络、突然写文件"这种意外行为。Agent 链路追求"能力强、可观察"——它要花十几秒甚至一分钟，会一边思考一边调用工具，过程中前端要看到"正在搜索网页""正在读取简历""正在写文件"这种实时反馈。这两种行为如果硬塞到一条链路里，要么会让简单问答因为携带了重型工具机制而变慢，要么会让复杂任务因为限制了工具调用而无法完成。

**用户如何显式选择？** 前端的会话页面上有两个不同的入口按钮。用户点"普通对话"，前端就调 `chat/sse` 这个端点，走 RAG 链路；用户点"Agent 模式"，前端就调 `agent/react/stream` 这个端点，走 Agent 链路。**这个选择权握在用户手里**，不是系统自动判断的。

**为什么不让 Planner 自动路由？** Planner（规划器，下一章会详细讲）虽然能识别问题类型，但它工作在 RAG 链路内部，职责是"决定要不要检索""决定回答模式"，不负责跨链路切换。让 Planner 做跨链路路由有两个坏处：第一，Planner 是基于一次 LLM 调用的判断，会有误判风险，误判一次就会把"我想让 Agent 帮我做事"识别成"我想问八股"，体验断崖；第二，Agent 链路有它独有的预算、工具、事件流机制，需要前端配合渲染（实时事件、工具进度、预算条），让 Planner 凭一句话就触发整套机制是不合适的。显式选择是更可控的设计。

### 1.4 完整技术栈清单

下面这张表是系统用到的所有外部技术组件。每一项的具体使用方式会在后续对应章节展开，这里先做"通俗解释"，让读者建立心智模型。

| 层级 | 技术 | 通俗解释 |
|---|---|---|
| 后端 Web 框架 | **FastAPI** | Python 的异步 Web 框架。"异步"意思是服务器在等待一个请求（比如等 LLM 返回）时可以处理其它请求，就像餐厅服务员把菜单递给后厨之后立刻去服务下一桌客人，而不是傻站着等菜出锅。 |
| ORM（对象关系映射） | **SQLAlchemy** | ORM = Object-Relational Mapping。让你用 Python 对象操作数据库表，比如写 `user.name = "张三"` 它会自动翻译成 SQL `UPDATE users SET name='张三' ...`，省去手写 SQL 的烦琐。 |
| 数据库迁移工具 | **Alembic** | 它就像数据库的"Git"。每次你给数据库加字段或建表，它会生成一个迁移脚本记录这次改动，并可以回滚。 |
| 关系数据库 | **PostgreSQL** | 存所有结构化数据：用户账号、会话记录、消息历史、记忆条目、面试记录、上传文件元数据、Agent 运行轨迹、LlamaIndex 的 Docstore 节点。强一致、关系清晰。 |
| 向量数据库 | **Milvus** | 专门用来存"向量"的数据库。向量就是一串数字（比如 1024 个浮点数），用来表示一段文字的"含义坐标"。Milvus 支持"语义相似度搜索"——给一个向量，找出"含义最接近"的那些向量。 |
| 内存数据库/消息中间件 | **Redis** | 做两件事：一是给 Celery 当"消息中间人"，把要做的活儿排队让 Worker 去取；二是辅助缓存。 |
| 异步任务队列 | **Celery** | 把耗时长的活儿（比如转写一段 30 分钟录音）放到后台执行，避免阻塞 HTTP 接口。"分布式任务队列"在 Python 圈用得最多。 |
| 对象存储 | **MinIO** | 兼容 AWS S3 协议的本地对象存储。所有用户上传的文件（简历 PDF、面试录音、知识文档）都存它。S3 协议是行业标准，未来从本地切到 AWS 只要改一个 endpoint。 |
| 文本嵌入模型 | **BGE-M3** (BAAI/bge-m3) | 把一段中文/英文文本变成 1024 维向量的模型。同义/同主题的文本，向量距离也近。这是让 Milvus 能做"语义搜索"的核心。 |
| 重排序模型 | **BGE-Reranker-Base** (BAAI/bge-reranker-base) | 在粗排（向量+BM25 拿到 Top-K 候选）之后，对每对"查询-文档"做更精细的相关性打分，把最贴题的文档排到最前面。 |
| 语音识别 | **Faster-Whisper / WhisperX** | OpenAI Whisper 的两个高速变体。Faster-Whisper 用 ctranslate2 引擎大幅加速，WhisperX 在此基础上加了精确时间戳对齐和说话人分离。 |
| 说话人分离 | **Pyannote** (pyannote-community/speaker-diarization-community-1) | "声纹分离"模型。给一段两人对话音频，它能告诉你"第 0-5 秒是 A，第 5-10 秒是 B"。 |
| 主对话 LLM | **DeepSeek V4 Flash / Pro** | DeepSeek 的最新一代模型。Flash 偏速度便宜，用于日常对话和系统内部辅助任务；Pro 偏推理能力强，用于 Agent 的工具调用与复杂决策。 |
| 备用 LLM 路由 | **NVIDIA NIM** | NVIDIA 的模型托管服务，提供 Meta Llama、Gemma、Qwen Coder、NVIDIA 自家发布的 DeepSeek V3.x 等多个模型作为备选。 |
| RAG 框架 | **LlamaIndex** | 提供向量索引、检索器、文档解析、节点切分、Reranker 后处理、Docstore 等 RAG 基础设施的 Python 库。 |
| 高质量文档解析 | **LlamaParse** | LlamaIndex 官方的云端文档解析服务（有 LLAMA_CLOUD_API_KEY 才启用）。能把复杂排版的 PDF/PPTX/DOCX 转成保留表格、标题、列表结构的 Markdown。 |
| 数据模型/校验 | **Pydantic** | Python 的数据校验库。所有 API 请求/响应、Agent 工具的参数定义都用 Pydantic 描述，类型不对就直接报错。 |
| 用户认证 | **JWT** (JSON Web Token) | 一种"自包含、无状态"的认证方式。服务器签发一个加密字符串给前端，前端每次请求都带上它，服务器靠验证签名识别用户。 |
| 前端框架 | **Vue 3 + Vite + TypeScript** | Vue 3 是渐进式前端框架；Vite 是构建工具（启动比 Webpack 快几十倍）；TypeScript 是带类型检查的 JavaScript。 |
| 前端路由 | **Vue Router 5** | 把 URL 路径映射到对应页面组件，并提供"路由守卫"做登录拦截。 |
| 反向代理 | **Nginx** | 用户访问统一域名，Nginx 根据请求路径决定转发给前端服务器还是后端 API。 |
| Agent 网络搜索 | **Tavily** | 专为 LLM 设计的搜索 API，返回结构化的标题/URL/摘要，避免直接爬网页的复杂度。 |
| Token 计数 | **tiktoken** | OpenAI 开源的 Token 分词器。给一段字符串，准确返回它对应多少 Token。系统用它做上下文预算控制。 |
| RAG 评测框架 | **RAGAS** | 专门评测 RAG 系统的开源工具。它用 LLM 充当裁判（"LLM-as-a-Judge"），对回答的忠实度、上下文精确度等做自动评分。 |

> **延伸定义：什么是 Token？** 大语言模型不是按"字"或"单词"理解文本，而是按 Token。Token 是模型词表里的最小单位，大致相当于 0.5 个中文字或 0.75 个英文单词。所有 LLM 都有"上下文窗口上限"（比如 DeepSeek 是 128K Token），超过这个上限就处理不了。本系统对每一段输入都做 Token 计算和预算控制。

### 1.5 它和系统其他部分如何衔接

总览这一章相当于"地图的图例"。下一章开始我们会从 RAG 链路切入，从用户点击发送按钮的那一刻开始，一步一步走完整条链路。中间所有出现的"会话 (Session)"、"上下文 (Context)"、"向量检索"、"Reranker"、"防幻觉"、"流式输出"等概念，都会在它们第一次出现的位置展开。

---

## 二、链路一：RAG 知识问答链路

### 2.1 这个模块解决什么问题

LLM 自己的"知识"是训练时灌进去的，它可能不知道 Redis 7 的新特性，也不知道用户私人上传的某份面经文档里的具体表述。如果直接问 LLM，它可能会编一个看起来合理但实际错误的答案——这种现象叫"幻觉 (Hallucination)"。

RAG（Retrieval-Augmented Generation，检索增强生成）就是为了解决幻觉而生。核心思想：先从一个外部知识库里"检索"出和用户问题相关的几段文本，再把这些文本作为"参考资料"塞进给 LLM 的提示词里，让它基于资料回答——就像开卷考试。

本系统的 RAG 链路在此基础上还做了更多事：它还要追踪当前会话、处理多轮代词（"那它的持久化呢？"中的"它"）、按需召回用户的长期记忆、按预算组织最终的提示词、并把答案逐字流式推给前端。下面我们用一个完整例子把整条链路走一遍。

### 2.2 完整流程：当用户问"Redis 的持久化机制有哪些？"

**前置场景**：用户已经登录，已经选了某个"通用对话"会话，正在和系统聊天。他在前面已经问过"Redis 是什么？"，系统回答过。现在他打字"那它的持久化呢？"并点了发送。

#### 步骤 1：前端建立 SSE 连接

前端调用 `POST /api/v1/chat/sse/{session_id}`，请求体里只有一行 `{"message": "那它的持久化呢？"}`。这个接口返回的不是普通 JSON，而是 `text/event-stream`——这是 SSE 协议。

> **什么是 SSE？** SSE = Server-Sent Events，服务器推送事件。它是 HTTP 协议之上的一种"流式响应"约定：客户端发起一个普通 HTTP 请求，服务器不立刻返回完整响应，而是保持连接打开，把响应内容分成一段一段地、按时间顺序"推"过来，每段以 `data: ...\n\n` 这样的格式分隔。前端用 `ReadableStream.getReader()` 一边读一边解析，就能做到"AI 的回答一个字一个字蹦出来"的效果。
>
> **SSE 和 WebSocket 的区别**：WebSocket 是真正的双向通道，客户端和服务器都能随时主动发消息。SSE 是单向的——服务器→客户端推数据，客户端只能在一开始发一次。RAG 对话场景里，用户发一次问题、服务器需要持续把回答推过来，根本不需要双向通道，用 SSE 比 WebSocket 简单很多：不需要握手协议升级、不需要心跳保活、能直接享受 HTTP 的 CORS/认证/反向代理生态。响应头里还会带上 `X-Accel-Buffering: no`，告诉 Nginx "别帮我攒着推，让数据立刻穿过去"。

#### 步骤 2：后端入口 `stream_chat_with_agent`

请求落到后端，路由层 (`/api/v1/chat/sse/{session_id}`) 把请求交给 `app.api.chat.sse_chat_endpoint`。它做两件事：一是校验当前用户是不是这个 `session_id` 的所有者（基于 JWT 中的 `username` 字段比对 `chat_sessions.user_id`），二是开启一个 Python 异步生成器 `event_generator()`，里面循环调用 `stream_chat_with_agent(message, user_id, session_id)`——这是 RAG 链路的总调度器，所有后续步骤都从它里面发起。

它每收到一段 `chunk`，就把 `chunk` 包装成 `data: {"type": "chunk", "content": "..."}\n\n` 推给前端。当生成器结束时再推一条 `data: {"type": "done"}\n\n`。

#### 步骤 3：确保会话存在 `ensure_session`

`stream_chat_with_agent` 第一件事就是调用 `transcript_service.ensure_session(session_id, user_id)`。

> **什么是"会话 (Session)"？** 在系统里，每个"会话"是一条聊天记录的容器，对应数据库表 `chat_sessions` 的一行。它有四个核心字段：
> - `id`：会话的唯一标识。
> - `user_id`：会话的所有者。
> - `session_state`：一个 JSON 字符串，存放与会话相关的可结构化状态。普通对话里它通常是 `{"mode": "general", "summary": ""}`；模拟面试里它会存放当前阶段、当前问题序号、问答历史；复盘会话里它会存放对应的 `interview_id`。
> - `turn_count`：当前会话已经发生过多少轮对话。
> - `compaction_cursor`：一个序号游标。游标之前的对话已经被"会话压缩"成摘要塞进 `session_state.summary` 里了，游标之后的对话是"还没被压缩的最近原始对话"。

`ensure_session` 的作用是：拿 `session_id` 去查 `chat_sessions`。如果存在，直接返回；如果不存在（比如前端传了一个全新的 ID），就建一行新记录，写入默认的 `session_state`。这一步存在的原因是后续的"上下文组装""持久化""压缩"全都要靠 session 行做载体——没有它，对话历史无处可存。

#### 步骤 4：组装改写上下文 `assemble_rewrite_context`

接下来要做"查询改写"。系统调用 `context_pipeline.assemble_rewrite_context(session_id, current_query)`。

为什么需要改写？因为用户当前的问题是"那它的持久化呢？"——直接拿这句话去检索，搜索引擎完全不知道"它"是谁。系统需要先把"对话最近发生过什么"拼接成一个上下文，配合用户的原始问题一起交给 Planner，让 Planner 把"它"还原成"Redis"。

`assemble_rewrite_context` 是 `_assemble` 的轻量版变体，它只组装四个东西：
1. `session_state`（会话的状态字典，含 `summary`）。
2. `recent_turns`（从 `compaction_cursor` 之后拉取的最近 N 轮对话）。
3. 当前用户问题。
4. 把以上三者按"[Session State]"、"[Recent Turns]"、"[Current Query]"几个标签拼成一段纯文本。

它不召回记忆、不检索知识库——因为这个上下文只用来给 Planner 看，不需要太重。

#### 步骤 5：Planner 查询规划 `plan_query`

`plan_query(user_message, rewrite_context)` 是整条 RAG 链路最关键的"决策点"。它把改写上下文 + 用户原始问题打包，发给一个"快速 LLM"（`agent_fast_llm`，角色名是 `fast`，默认是 DeepSeek V4 Flash），要求它输出一个严格的 JSON 对象——这个对象就是 `QueryPlan`。

`QueryPlan` 有 9 个字段：

| 字段 | 含义 |
|---|---|
| `standalone_query` | 把"它"这种代词消解掉之后的独立查询。比如把"那它的持久化呢？"改写为"Redis 的持久化机制有哪些？"。 |
| `dense_query` | 用于向量语义检索的自然语言查询。通常和 `standalone_query` 一样。 |
| `sparse_query` | 用于 BM25 关键词检索的短语，通常是关键词的串接，比如"Redis 持久化 RDB AOF"。 |
| `needs_memory_retrieval` | 是否需要去召回用户的长期记忆。闲聊一般不需要，问"我之前是不是面试过 Redis"这种就需要。 |
| `memory_types` | 要召回的记忆类型，是 `user_profile / interaction_preference / feedback_rule / project_reference` 中的子集。 |
| `needs_knowledge_retrieval` | 是否需要查知识库。打招呼、闲聊就不需要；问八股、技术概念就需要。 |
| `knowledge_sources` | 要查哪些知识源，是 `interview_qa / official_docs` 中的子集。 |
| `answer_mode` | 五种回答模式之一：`direct_chat`（直接对话）、`knowledge_qa`（八股问答）、`interview_learning`（学习计划）、`review`（复盘）、`preference_update`（更新偏好）。 |
| `reasoning` | 一段 Planner 给出的简短说明，方便后期排查。 |

**为什么要把 `dense_query` 和 `sparse_query` 分开？** 因为向量检索和 BM25 检索喜欢的输入形态不同。向量检索喜欢"完整自然语言"，因为嵌入模型本来就是在完整句子上训练的；BM25 检索喜欢"关键词串"，因为它本质是按词频排序，长句里的连词/虚词会稀释关键词权重。让 Planner 各自定制一份输入，能让两路检索都发挥到最好。

**为什么要让 LLM 输出 JSON？为什么用 `response_format=json_object`？** Planner 的输出要被代码解析成结构化对象。如果让 LLM 自由发挥，它可能输出 "根据用户的问题，我认为需要……" 这种自然语言，没法解析。`response_format={"type": "json_object"}` 是 OpenAI 兼容 API 的一个开关，告诉模型"你只能输出合法 JSON"，模型会在解码阶段强制走 JSON 语法。即使如此 LLM 偶尔还是会出错，所以 `_extract_json_payload` 会再用正则兜底地把 `{...}` 部分抠出来。

**为什么要有 `fallback_query_plan` 降级？** LLM 总有可能调用失败：超时、限流、网络抖动、JSON 解码失败。这种时候系统不能让整个对话崩掉。`fallback_query_plan` 是一份"保守的、安全的"默认计划：把用户原始问题既当 `standalone_query` 又当 `dense_query`，从原文里提取关键词作为 `sparse_query`，假定需要检索知识库 + 召回记忆，模式设为 `knowledge_qa`。这样即使 Planner 挂了，用户问的还是技术问题，系统也能正常走完检索→生成。`logger.warning` 会把失败原因记下来，便于后期分析。

#### 步骤 6：并发召回——记忆 + 知识

Planner 出了 QueryPlan，下一步是并发地去拉数据。系统同时启动三件事：

> **什么是"并发"？** 并发 = Concurrency。指多个任务"穿插进行"——一个任务在等网络的时候让出 CPU 给另一个任务去发请求。它和"并行 (Parallelism)"不一样，并行是真的多个 CPU 核同时跑，但并发对 I/O 密集型任务（比如等数据库、等 LLM）就够用了，因为这些任务大部分时间都在等。Python 用 `asyncio.create_task(...)` 启动一个并发任务。

**① `load_user_profile(user_id)`**：直接从 PostgreSQL 的 `memory_items` 表里读所有 `type='user_profile'` 的条目。`user_profile` 是"用户档案"——技术栈、求职方向、工作经验之类的稳定个人信息。这一步是同步查询，但它本来就快（毫秒级），不需要 await，作为后续上下文的固定部分。

**② `recall_relevant(user_id, query, memory_types=['interview_fact'])`**：从 Milvus 的记忆专用 collection 里语义召回 `interview_fact`（面试中积累的学习记录）。这一步耗时 100-300ms，所以用 `asyncio.create_task` 包裹。

**③ `knowledge_retriever.retrieve(dense_query, sparse_query, source_types, user_id)`**：从知识库做混合检索。这一步是最重的，可能耗时 300-800ms，必须 `asyncio.create_task`。

**串行 vs 并发的开销对比**：假设三件事分别耗时 50ms / 200ms / 500ms。串行就是 50+200+500=750ms。并发是 max(50,200,500)=500ms。差不多省 1/3 时间，对用户体验影响显著——尤其是当 LLM 还没开始生成第一个字之前，每一毫秒都直接体现在"等待感"里。

注意：`memory_task` 和 `knowledge_task` 是有条件创建的——`needs_memory_retrieval=False` 就不创建 memory_task，闲聊场景就直接跳过这两个重操作。

#### 步骤 7：混合检索管线 `query_knowledge_base`

这是整条 RAG 链路最精密的部分。它在 `app/rag/retriever.py` 里。下面我们一路展开。

##### 7.1 Milvus 单例 + 懒加载

系统启动时不会立刻连 Milvus。第一次有请求要查知识库时，`_get_milvus_index()` 才会真正建立连接：它创建一个 `MilvusVectorStore` 对象，再包装成 `VectorStoreIndex` 全局单例。后续所有查询复用这个单例。这种"懒加载"策略让启动更快，也避免了 Milvus 暂时不可用导致整个 API 起不来。

> **什么是单例？** 单例 = 整个进程里只创建一个实例。多个请求都用同一个 Milvus 连接对象，避免每次查都重新握手。

锁机制 `_milvus_lock` 保证多个请求并发到达时只有一个能真正去创建，其他的都在锁外面等结果。这就是"线程安全的懒加载"。

##### 7.2 HNSW 索引参数

Milvus 的 collection 在创建时用了 HNSW 索引。

> **什么是 HNSW？** HNSW = Hierarchical Navigable Small World，分层可导航小世界图。这是当前最快的"近似最近邻搜索 (Approximate Nearest Neighbor Search)"算法之一。
>
> 直觉理解：想象一个城市的交通系统，最底层是社区小路（每个点能到附近几个邻居），上一层是主干道（每个点能跳到更远的几个城市），再上一层是高速公路（能跨省一步到位）。当你要找一个特定的人时，你先在最顶层用高速公路逼近大概方向，再下高速换主干道更精确接近，最后在社区小路找到目标。这就是 HNSW 的工作原理。它的搜索复杂度是 log(N)，而暴力搜索是 N，差距随着数据量增长而拉开。

系统配置了三个核心参数：

- **M = 16**（每层每个节点最大连接数）：决定每个节点"认识多少邻居"。M 越大，图越密，搜索越准但占内存越多。16 是工程界经典平衡点。
- **efConstruction = 200**（建索引时搜索宽度）：插入每个新节点时它会扫多少候选邻居。越高质量越好但建索引越慢。200 属"高质量"配置，反正索引只建一次，可以多花时间。
- **efSearch = 64**（查询时搜索宽度）：每次查询要探索多少候选节点才停止。越大召回越准但查询越慢。64 在召回率和延迟之间的工程经验值。

##### 7.3 相似度度量：IP 内积

向量之间的"距离"有多种度量方式：

- **L2 欧式距离**：直观但计算贵，对方向不敏感。
- **Cosine 余弦相似度**：忽略向量长度，只看方向。
- **IP 内积 (Inner Product)**：直接做点积，计算最快。

BGE-M3 输出的向量已经"归一化"过（向量长度恰好等于 1），在这种情况下 **IP 内积在数学上等价于 Cosine 余弦相似度**，但计算更便宜（少做一次除法）。所以系统选 IP。

##### 7.4 向量检索 + 多租户隔离 (P0 红线)

`VectorIndexRetriever` 配合 `MetadataFilters` 做带条件的向量检索。**多租户隔离**是这里的"P0 红线"——P0 在工程里表示最高优先级、绝不能违反的安全约束。

> **什么是多租户隔离？** 不同用户上传的私密资料必须严格物理隔离。用户 A 上传的简历不能被用户 B 搜到，用户 B 上传的面经也不能污染用户 A 的检索结果。

系统通过两条约束达成：
1. **入库时**：每个文档片段在写入 Milvus 时被强制绑定 `user_id` 这个 metadata 字段（在文档摄入章节详述）。
2. **查询时**：`_build_metadata_filters` 给每个查询构造 `MetadataFilter(key="user_id", value=user_id, operator=EQ)`，把"只搜这个用户的数据"作为 Milvus 服务端过滤条件。

代码注释里专门把这一段标为"P0 红线"。绝不能为了"调试方便"放宽这条规则。

`VECTOR_TOP_K = 8` 表示向量检索召回 Top-8 个候选。

##### 7.5 BM25 关键词检索

> **什么是 BM25？** BM25 = Best Matching 25。它是经典的关键词检索算法，TF-IDF 的改良版。
>
> **TF-IDF 是什么？** TF = Term Frequency（词频），IDF = Inverse Document Frequency（逆文档频率）。直觉：一个词在某篇文档中出现得越频繁、同时在其他文档中出现得越少，它就越能"代表"这篇文档。
>
> **BM25 比 TF-IDF 强在哪？** BM25 做了两个修正：① 给 TF 加了上限（避免某个词在一篇文档里出现 100 次和 50 次时被过度区分），② 引入了文档长度归一化（同一个词在短文档里出现一次比在长文档里出现一次更有分量）。

**为什么有了向量检索还需要 BM25？** 两者互补：
- 向量检索擅长"理解语义"——查"如何让数据不丢"也能匹配到"持久化机制"；
- BM25 擅长"精准命中关键词"——查"AOF"就能精确捞到所有包含 AOF 字样的文档；
- 反过来：向量检索碰到 BGE-M3 训练时没见过的新术语会失灵；BM25 对"换一种说法"的查询无能为力。

**per-user 缓存 TTL=300s**：BM25 要在内存里建一个倒排索引（一张"词 → 包含这个词的文档列表"的大表），这需要从 PostgresDocumentStore 把当前用户的所有文档节点都拉出来过滤一遍，成本不低（几百毫秒到几秒）。所以系统给每个用户的 BM25 索引做了缓存，有效期 300 秒。

> **什么是 TTL？** TTL = Time To Live，存活时间。300 秒之内的重复查询直接用缓存里的 BM25Retriever；过了 300 秒条目被视为"过期"，下次查询会重建。300s 是个折中：用户在一次连续会话里多次提问通常都在 5 分钟内，能享受到缓存收益；同时不会缓存太久导致新摄入的文档迟迟搜不到。

**缓存失效 invalidate_bm25_cache**：文档摄入完成时（`ingest_document` / `ingest_text` 的末尾）会立刻调用 `invalidate_bm25_cache(user_id)`，把这个用户的所有 BM25 缓存条目主动删除。这样新上传的文档下一次查询就能立刻出现在结果里，不需要等 5 分钟。

`BM25_TOP_K = 8`，和向量检索一样召回 Top-8。

##### 7.6 融合：RRF 倒数排名融合

> **什么是 RRF？** RRF = Reciprocal Rank Fusion，倒数排名融合。它的公式是 `score(doc) = Σ 1/(k + rank_i(doc))`，对每条检索路径，把文档在该路径里的排名取倒数（加常数 k 防止极端值），然后把多个路径的倒数加起来作为最终分。系统取 k=60（LlamaIndex 的 `QueryFusionRetriever` 默认值）。

**为什么不用加权求和（比如 0.7×向量分 + 0.3×BM25 分）？** 因为两路检索的原始分数量级完全不同。向量内积是 0~1 区间（归一化向量的余弦近似），BM25 分数没有上界，可能是 5、10、甚至 50。直接加权和会让 BM25 的高分把向量分完全淹没。RRF 把分数都换成"排名的倒数"，不管原始分多少都被压到 0~1/61 区间，天然规避了量纲问题。同时还有一个隐藏优点：**同时出现在两路 Top-K 里的文档自动获得加成**——这正是我们希望强化的"两种方法都认为相关，那大概率真的相关"。

`FUSION_TOP_K = 6`：融合后只保留 Top-6 进入下一步精排。

##### 7.7 精排：BGE-Reranker 交叉注意力

`init_reranker()` 在系统 lifespan 启动时加载 BGE-Reranker-Base 模型（`SentenceTransformerRerank`）。它做"精排"——重新评估每对（查询，文档）的相关性。

> **什么是 Cross-Attention（交叉注意力）？为什么 Reranker 用它？**
>
> 之前的向量检索是"双塔模型 (Bi-Encoder)"：查询和文档**各自独立**编码成向量，再比较距离。就像两个人各写一封自我介绍信，再让第三方比较两封信的相似度——第三方看不到他们当面交流。
>
> Reranker 是"交叉编码 (Cross-Encoder)"：把查询和文档**拼接在一起**输入模型，模型用 Cross-Attention 机制让每个词都能"看到"对面句子里的每个词，相互对照判断"这段文档是不是回答了这个问题"。就像让一个人同时看到问题和答案，直接说"对得上"或"对不上"。
>
> 这种方式**理解更深入、更准**，但计算成本高：每一对都要单独跑一次模型。

**Reranker 只能做精排，不能做全库搜索**——因为全库可能有几十万条文档，每一条都要和查询配对跑一遍模型，计算量爆炸。所以工程上的常规做法是：向量+BM25 先粗排选出 Top-6 候选，再让 Reranker 对这 6 条精排，把 Top-5 留下。

`RERANK_TOP_N = 5`：精排后保留 5 条进入提示词。

##### 7.8 防幻觉双闸门

精排完了，分数已经是"相关性概率"了。但仍有可能所有候选文档其实都和问题没什么关系（比如用户问了个知识库里完全没有的偏门问题）。如果还把这些"低相关性"文档塞给 LLM，LLM 反而会被误导编一个看起来合理的答案——这是最危险的幻觉源头。

系统设了两道防线：

**① Reranker 绝对分数阈值 ≥ 0.5**：`RAG_MIN_SCORE = 0.5`。Reranker 给每条候选打 0~1 分，低于 0.5 直接丢。这个阈值是 RAGAS 评测多次跑分调出来的——再低（如 0.3）会放进太多噪声拉低答案准确率，再高（如 0.7）会过滤掉部分边缘但有用的文档拉低召回。

**② 词面覆盖回退 ≥ 0.35**：`RAG_LEXICAL_FALLBACK_MIN_OVERLAP = 0.35`。如果 Reranker 没加载成功（模型加载失败、显存不足等降级场景），系统会用一个简单的备用方案：算"查询中的关键词有多少出现在文档里"。覆盖率低于 35% 就丢。

这两道防线在 `_score_passes` 里区分处理：`used_reranker=True` 时严格用 0.5；`used_reranker=False`（fallback 场景）时用 `RAG_FALLBACK_MIN_SCORE = 0.02`（更宽松，因为没 Reranker 的话原始向量分一般不高，需要放低门槛保住召回率），同时也允许走 lexical 兜底。

**SYSTEM_EMPTY_WARNING 兜底**：如果两道防线都过不去——所有候选都被过滤掉了，系统返回一个特殊文本 `"[SYSTEM_EMPTY_WARNING] 知识库中未检索到与该问题高度相关的参考信息。"`。这条文本被原样塞进 retrieved_context 槽位，告诉 LLM"知识库里没有靠谱资料，请如实回答你不知道，不要编造"。这一行的存在让幻觉率降到了一个可接受的水平。

#### 步骤 8：六槽上下文窗口组装

混合检索拿到 chunks，再加上前面并发拉到的 user_profile 和 relevant_memories，所有原料齐了。接下来要把它们组装成一段 LLM 能消化的提示词。

系统用"六槽上下文窗口"设计（`ContextAssemblyPipeline.assemble_answer_context`）：

| 槽位 | Token 预算 | 内容 |
|---|---|---|
| `system_prompt` | 3K | LLM 的角色指令（"你是 Interview Copilot..."） |
| `reference_material` | 2K | 复盘的分析报告、模拟面试的计划摘要等参考材料 |
| `retrieved_context` | 8K | 检索到的知识 chunks + 召回的记忆 |
| `session_state` | 2K | 会话摘要（之前对话被压缩成的简短文字） |
| `recent_turns` | 32K | 最近 N 轮原始对话 |
| `current_input` | 4K | 用户当前问题 |

总预算约 51K，预留巨大余量给 1M 上下文模型（系统假定 1M 窗口）。

**每个槽位的设计意图**：
- `system_prompt` 3K：因为它装的是"你的角色 + 用户档案 + 模式提示"，user_profile 字段加上规则文本不会很长。
- `reference_material` 2K：复盘报告或面试计划摘要通常一两段就够。
- `retrieved_context` 8K：5 条精排 chunk，每条平均 1-1.5K Token，正好。
- `session_state` 2K：CompactionService 把会话摘要压到 300 字以内（约 600-800 Token），2K 足够。
- `recent_turns` 32K：是大头，因为多轮对话累计起来很快，给得最多。
- `current_input` 4K：用户单条输入很少超过 1K，留 4K 余量足够长 prompt 输入。

**trim_messages 和 trim_items 的策略**：
- `trim_messages`：从最新一条往老的方向倒序累加，超过预算就截断早期消息。优先保最近，因为最近对话对当前回答影响最大。
- `trim_items`：按数组顺序累加，超过预算就停止。用在记忆/chunks 这种"已按相关性排序"的列表上，优先保高分项。

**_repair_pairs 修复对话对**：LLM 的对话历史习惯被组织成 User-Agent-User-Agent 交替。如果 trim 把第一条 Agent 砍掉了，剩下的 User 没人回复就显得诡异；如果最后一条是 User 没 Agent 回复，LLM 会以为对话不完整。`_repair_pairs` 在裁剪后做两件事：①开头如果是 Agent，丢掉它；②结尾如果是 User，也丢掉它。这样保证 LLM 看到的对话历史是干净的 User-Agent 配对。

**COMPRESS_THRESHOLD_RATIO = 0.75（针对 1M 上下文模型）**：本系统假定主模型上下文窗口为 1,000,000 Token（DeepSeek V4 / Mimo 这一档）。压缩阈值 75% 表示当 prompt 接近 750K Token 时就要触发"会话级压缩"。本链路实际并未在每一次请求中检查这个比率（它是为未来 1M 模型场景预留的设计常量），日常的压缩触发条件是"每 20 轮压缩一次"——会在记忆系统章节展开。

#### 步骤 9：LLM 选择和系统规则

组装完上下文，系统根据 `needs_knowledge_retrieval` 选不同的 LLM 入口和系统提示词：

- 如果**没**走知识库检索（闲聊、表达偏好），走 `DIRECT_SYSTEM_RULES`，并用 `agent_fast_llm`（fast 角色，DeepSeek V4 Flash）。规则强调"使用提供的会话状态和记忆中相关的部分；信息不足就说缺什么"。这种快路径让简单对话延迟更低、成本更低。
- 如果走了知识库检索，使用 `RAG_SYSTEM_RULES`，并用 `Settings.llm`（primary 角色，默认也是 DeepSeek V4 Flash，但允许在前端"模型管理"页热切换到更强的模型）。规则强调"把检索到的知识当证据，不要编来源"。

**agent_fast_llm 和 Settings.llm 的角色分工**：
- `agent_fast_llm` 始终是 fast 角色，用于内部辅助任务：Planner、记忆提取、会话压缩、模拟面试官回应、批量评估。这些都是"系统内部消耗"，对响应延迟敏感、对成本敏感，且用户看不到原始输出，所以恒定 Flash。
- `Settings.llm` 是 LlamaIndex 全局变量，由 `refresh_primary_llm()` 在启动时绑定到 primary 角色当前选中的模型。它面向用户的最终生成，质量优先。primary 默认 V4 Flash，但用户在 `/models` 前端页面可以热切换到 V4 Pro 等。

#### 步骤 10：流式输出 `astream_complete`

系统把组装好的 prompt 交给所选 LLM 的 `astream_complete` 方法。它返回一个**异步迭代器**，每次 `async for chunk in response_generator` 就吐出一段 `chunk.delta`（delta 是"增量"，每次只包含新生成的几个字）。

`stream_chat_with_agent` 把每个 `chunk.delta` 通过 `yield` 抛出去。SSE 端点把它包成 `data: {...}\n\n` 推给前端。前端的 reader 实时拼接，用户看到的就是"AI 一个字一个字蹦出来"的效果。

同时系统用一个本地变量 `final_answer = ""` 把所有 delta 累加起来，留作步骤 11 持久化用。

#### 步骤 11：后处理——持久化 + 后台维护

`response_generator` 跑完之后，系统做两件事：

**①持久化对话**：`transcript_service.append_turn(session_id, user_id, user_msg, ai_msg, rewritten_query)` 把"用户那一轮"和"AI 那一轮"两条消息按 `seq` 序号写进 `chat_messages` 表，并把 `chat_sessions.turn_count += 1`、`updated_at` 刷新。`rewritten_query` 只在 standalone_query 和原始问题不同的时候保存（便于审计 Planner 的改写质量）。

**②后台维护**：`safe_background_task(post_turn_maintenance_service.run(session_id, user_id))` 把"对话后续维护"丢进异步后台。这件事不阻塞用户继续输入下一条，但它会做两个动作：
- 触发 `CompactionService`：判断 `turn_count >= 20` 且能整除时，把游标 `compaction_cursor` 之前的旧对话用 LLM 压成 300 字以内摘要，存到 `session_state.summary` 里。
- 触发 `MemoryExtractionService`：拿当前轮的对话给 LLM 看，让它结构化输出"值得长期记住的事"——`user_profile` 或 `interview_fact`，落库 + 写 Milvus 向量。

**锁机制 `_lock_for(session_id)`**：维护任务是异步的，理论上一个用户连续问两次，可能上一轮的维护还没跑完下一轮就启动了——两份维护同时改 `session_state` 会冲突。所以 `PostTurnMaintenanceService` 给每个 `session_id` 都维护一把 `asyncio.Lock`，同一个 session 的维护任务严格串行。锁表 `_locks` 上限 128，超出时丢最早的 key（FIFO），避免内存无限增长。

**safe_background_task**：它是对 `asyncio.create_task` 的封装，做三件事：① 把任务加入全局集合 `_background_tasks` 防止 GC 回收；② 加 `done_callback`，任务异常会记到 logger 而不是悄悄消失；③ 退出时 `cancel_and_wait_all` 能优雅取消所有未完成任务。

#### 步骤 12：异步埋点 `log_interaction_metrics`

最后在 `finally` 块里调用 `log_interaction_metrics`，把这次请求的 5 个数字写进 `data/logs/metrics.jsonl`：
- `latency`：总耗时（秒）。
- `prompt_tokens` / `completion_tokens` / `total_tokens`：由 LlamaIndex 的 `TokenCountingHandler` 全程记录。
- `retrieval_attempted`：本次有没有走过知识检索。
- `retrieval_hit`：检索是否真的拿到了非空且不是 SYSTEM_EMPTY_WARNING 的结果。

这个埋点也是 `await asyncio.to_thread(_write_log_sync, ...)`，避免文件 I/O 阻塞响应。失败也只是 `logger.warning`——埋点丢失不该影响用户体验。这些数据后续会喂给评测体系的 L1/L2 报告。

### 2.3 它和系统其他部分如何衔接

RAG 链路是"对话场景"的主路径。它的产物（持久化对话、新生记忆、新摘要）会被记忆系统、模拟面试系统、复盘会话复用。它依赖的下游有：Planner（其实就是 fast LLM 的封装）、知识库（来自文档摄入管线）、Milvus、PostgreSQL、Reranker。下一章我们看用户主动选择"Agent 模式"时走的另一条链路。

---

## 三、链路二：Agent Harness 智能体

### 3.1 这个模块解决什么问题

RAG 链路擅长"一问一答"，但有些任务必须分多步才能完成：先查这个，再读那个，再综合判断，最后输出结果。比如用户说"读一下我的简历，搜一下 XX 公司的面经，分析我和这个岗位的差距，最后写一份两周复习计划保存为 Markdown 文件"——这不是一次检索能解决的，必须有一个能自主推理、循环调用工具的"智能体"。

Agent Harness 就是这个智能体的运行框架。"Harness" 本意是"挽具/工装"，引申为"承载和约束某个东西运行的支架"。我们的 Harness 承载的是一个 LLM 驱动的 ReAct 循环，约束它的是预算、工具范围、错误恢复、上下文压缩。

### 3.2 ReAct 模式

ReAct = Reasoning + Acting，"思考 + 行动"交替循环。让 LLM 不再"一次性吐答案"，而是分多步：每一步先输出"思考"（我现在该干嘛），再决定"行动"（调用哪个工具、传什么参数），观察工具返回结果，再进入下一轮思考。

> **完整对话示例**：
> 
> 用户："分析一下 XX 公司的后端工程师 JD 和我简历的差距"
>
> Agent 第 1 步思考："我需要先知道用户的简历。先调 read_resume 工具。"  
> Agent 行动：调用 `read_resume()`  
> 工具返回：候选人简历分段（summary、project、education、skill）。
>
> Agent 第 2 步思考："简历有了，技术栈是 Java/Spring/Redis/MySQL。现在需要 JD 内容。用 web_search 找 XX 公司后端岗位。"  
> Agent 行动：调用 `web_search(query="XX公司 后端工程师 JD")`  
> 工具返回：5 条搜索结果（含 URL）。
>
> Agent 第 3 步思考："顶部结果是公司官网的招聘页，需要打开看具体职责。"  
> Agent 行动：调用 `read_url(url=...)`  
> 工具返回：页面正文 Markdown。
>
> Agent 第 4 步思考："JD 要求 Go + Kubernetes，简历只有 Java。差距：① 语言鸿沟 ② 容器编排经验缺失。让我同时召回这个用户之前是不是在面试中提到过这两个方向。"  
> Agent 行动：调用 `recall_memory(query="Go Kubernetes")`  
> 工具返回：用户记忆中没有相关记录。
>
> Agent 第 5 步思考："信息齐了，可以直接给最终答案。"  
> Agent 行动：（无工具调用，直接输出最终文本）  
> 最终答案：完整的 JD 差距分析报告。

### 3.3 为什么自研 Agent Harness 而不直接用 LangChain Agent

LangChain Agent 是这个领域最知名的开源 Agent 库。系统选择自研而不是直接拿 LangChain 用，理由有三：

1. **预算治理细粒度**：LangChain Agent 默认只控制 max_iterations，没有"最大工具调用次数""每个工具最多调几次""总 Token 预算""墙钟时间预算"这种多维约束。本系统的 `AgentBudget` 做了四维 + per-tool 的精细控制。

2. **错误恢复策略**：LangChain Agent 对 LLM API 错误处理较为粗糙，主要靠通用 retry。本系统借鉴 Anthropic Hermes 的设计，把错误分三类：FATAL（认证错误立刻终止）、CONTEXT_TOO_LONG（触发上下文压缩后重试）、RETRYABLE（带 jitter 的指数退避重试）。

3. **结构化事件流**：LangChain Agent 的回调（callback）机制是面向"日志"和"调试"的，事件不规整、不分层、难直接流给前端做 UI 渲染。本系统的 `HarnessEvent` 是面向前端可视化设计的 6 种结构化事件，前端可以直接消费。

参考 Hermes（Anthropic 内部 Claude Code 的 Agent 架构）的设计哲学：**工具注册表自治、预算严格治理、上下文按需压缩、事件流面向前端**。这些设计的具体落地在下面章节展开。

### 3.4 ToolRegistry 工具注册中心

`ToolRegistry`（在 `app/agent_runtime/tool_registry.py`）是 Agent 知道"自己有哪些工具可用"的中心入口。

#### 3.4.1 自注册模式

所有工具文件（`tools/web.py`、`tools/knowledge.py`、`tools/resume.py` 等等）在文件末尾都有一行 `registry.register(ToolEntry(...))`。当 Python 第一次 `import app.agent_runtime.tools.web` 时，文件里所有顶层代码就会执行一次——这一行就生效了。

`react_agent.py` 顶部有一行 `import app.agent_runtime.tools  # noqa: F401`，这一行触发 `tools/__init__.py` 把所有子工具文件都 import 一遍，所有工具就自动注册到 `registry` 单例里。

**为什么用自注册而不是显式列举？** 显式列举意味着每加一个工具，都要去某个"工具列表"文件加一行。自注册模式让工具文件自己管理自己的注册，类似"每个新员工自己去前台签到，不需要 HR 挨个通知"。开发体验更顺，添加/删除工具的成本只在一个文件里。

#### 3.4.2 ToolEntry 字段

每个工具是一个 `ToolEntry` 实例，字段：

| 字段 | 含义 |
|---|---|
| `name` | 工具名（LLM 调用时用），如 `web_search`、`save_memory`。 |
| `description` | 工具描述，给 LLM 看的，告诉它这个工具什么时候用。 |
| `args_model` | Pydantic 模型类，描述这个工具接受什么参数。 |
| `handler` | 异步函数，实际执行工具逻辑。接收 (validated_args, context) 返回 dict。 |
| `toolset` | 工具集分组（默认 `"default"`），未来按场景启用不同工具组用的。 |
| `max_result_chars` | 工具结果的最大字符数。超过会截断并加 `_truncated=True` 标记。 |
| `check_fn` | 可选的"可用性检查"函数。比如 `web_search` 设了 `_tavily_available()`，没有 `TAVILY_API_KEY` 就在 schema/manifest 里隐藏这个工具。 |
| `emoji` | 给前端 UI 显示用的小图标，比如 🔍。 |

#### 3.4.3 Pydantic → OpenAI Function Calling Schema

> **什么是 Function Calling？** OpenAI 兼容 API 的一项能力。开发者把可用工具描述（名字、描述、参数 schema）传给 LLM，LLM 在回答时如果觉得需要调用工具，会返回一个特殊的 `tool_calls` 字段——里面包含工具名和按 schema 填好的参数 JSON。开发者执行工具，把结果传回 LLM，LLM 接着推理。这比"让 LLM 输出文本然后我们用正则解析"鲁棒得多。
>
> **OpenAI Function Calling Schema 是什么？** 一份 JSON 描述，结构形如 `{"type": "function", "function": {"name": "...", "description": "...", "parameters": {"type": "object", "properties": {...}, "required": [...]}}}`。

系统的工具参数用 Pydantic 模型定义（更熟悉、有类型校验、IDE 支持好）。`_pydantic_to_openai_schema(name, description, model)` 把 Pydantic 的 `model.model_json_schema()` 输出整理成 OpenAI 需要的格式，并清理掉 OpenAI strict 模式不接受的字段（如 Pydantic 自动加的 `title`、嵌套 `description`）。

#### 3.4.4 AGENT_TOOL_SCHEMA_STRICT 严格模式

`settings.AGENT_TOOL_SCHEMA_STRICT = True` 时，每个工具 schema 加上 `"strict": True` 字段。这是 OpenAI 的严格模式开关——开启后模型保证返回的 `tool_calls` 参数严格符合 schema（必填字段必须给、类型严格、不会出现 schema 外的额外字段）。代价是模型有时会卡住或拒绝。系统默认开启严格模式，让 dispatch 阶段省掉很多防御性 try/except。

#### 3.4.5 format_manifest 输出系统提示

`registry.format_manifest()` 把所有当前可用工具（`check_fn=True` 或没有 check_fn）的 schema 拼成一段 JSON 文本。这段文本会作为第二个 system 消息塞进 Agent 的 messages 列表里，让 LLM 在系统提示里就清楚"我手里有哪些武器、每个武器接受什么参数"。

### 3.5 完整工具集

下面是当前注册的所有工具，按使用频率排序：

| 工具 | 功能 | 参数 | 何时调用 |
|---|---|---|---|
| `search_knowledge` | 搜本地知识库（八股、官方文档） | `query`、`source_types`（默认 `["interview_qa"]`） | 用户问技术概念、八股、系统设计题。 |
| `web_search` | Tavily 网络搜索 | `query`、`limit`（1-10，默认 5） | 需要查公司信息、面经、最新技术资讯；`check_fn` 检查 `TAVILY_API_KEY` 是否设置，否则隐藏。 |
| `read_url` | 用 httpx 抓页面 + markdownify 转 Markdown | `url` | 在 web_search 拿到链接后，需要看具体页面内容。 |
| `read_resume` | 读用户简历的结构化分段 | `section_types`（可选过滤 summary/project/education/skill） | 给建议前需要先了解候选人背景。 |
| `read_file` | 读用户已上传的文件 | `upload_id` 或 `purpose`（resume/jd/audio） | 用户上传过 JD/笔记之类的文档，Agent 要直接读内容。 |
| `write_file` | 把内容写成可下载的文件 | `filename`、`content` | 输出学习计划、分析报告、复习笔记 Markdown。通过 `create_owned_upload` 创建一个所有权属于当前用户的 upload，把内容写到对应的 S3 对象键，再 `mark_upload_consumed`。 |
| `recall_memory` | 召回用户长期记忆 | `query`、`memory_types`（默认 `user_profile + interview_fact`）、`max_items` | 给建议前需要查看用户的过往学习记录、偏好。 |
| `save_memory` | 主动写入用户长期记忆 | `memory_type`、`description`、`content`、`normalized_key` | 重要发现、阶段性结论希望以后被想起。 |
| `read_interview_history` | 读历史面试记录 | `record_id`（指定查某次）或不传（列出最近 N 次） | 复盘场景、做学习计划前查薄弱点。 |
| `search_jobs` | Lever 招聘 API 搜岗位 / 查详情 | `keywords`、`city`、`limit`、`job_id` | 找符合用户技术栈的岗位，分析 JD。 |

### 3.6 AgentBudget 四维预算

Agent 的循环是 `while True`，如果不加限制，LLM 可能一直觉得"还差点意思再多调一个工具"陷入死循环。系统用 `AgentBudget` 做四维约束：

| 维度 | 上限 | 含义 | 设计依据 |
|---|---|---|---|
| `steps` | 8（`AGENT_MAX_STEPS`） | 总推理步数（每个 LLM 响应算一步） | 大部分实际任务在 4-6 步内能完成；8 步留出余量同时防止失控。 |
| `tool_calls` | 16（`AGENT_MAX_TOOL_CALLS`） | 累计工具调用次数（一步内可能 parallel 调多个） | 步数*平均每步工具数 ≈ 8*2，留一倍冗余。 |
| `total_tokens` | 32,000（`AGENT_MAX_TOTAL_TOKENS`） | prompt+completion 累计 Token 数 | 一次 Agent 任务的合理上限，远低于模型 128K/1M 窗口但足以做多步推理。 |
| `runtime` | 90 秒（`AGENT_MAX_RUNTIME_SECONDS`） | 墙钟时间 | 用户耐心极限。如果 90s 还没结束往往意味着出问题，宁可停。 |

外加 `AGENT_MAX_CALLS_PER_TOOL = 6`（每个工具最多调 6 次），防止 Agent 对同一个工具反复打——比如它觉得 `web_search` 没找到，就一直换关键词搜——超过 6 次就拒绝再调。

#### Budget Refund：失败退款

当一次工具调用失败（超时、未知工具、参数校验失败、底层抛异常），系统会调用 `budget.refund_step()` 把这一步退回来。这个设计借鉴自游戏机制中的"失败不惩罚"——外部依赖故障是 Agent 控制不了的，让它因此提前耗尽预算不公平。注意工具调用次数 (`tool_calls`) 不退，因为那是"做出的尝试本身"，但占用的"思考步数"会退。

#### 预算耗尽兜底

`budget.check()` 每轮循环开头检查，如果触发任何一个上限，设置 `stop_reason` 并跳出循环。最终如果还没有 `final_answer`，系统返回一段 "Agent 执行因预算策略停止: {stop_reason}. 请缩小目标范围后重试。"，保证用户至少能看到一个解释。

### 3.7 错误分类与重试

`call_with_retry`（在 `agent_runtime/retry_utils.py`）包裹每次 LLM API 调用。

`classify_api_error(error)` 根据异常类型和错误消息分三档：

- **FATAL**：401/403、`invalid_api_key`、`authentication`、`400`（非 context 类）。表示"我们这边配置错了"，重试也没用，立即抛出让上层处理。
- **CONTEXT_TOO_LONG**：消息含 `context_length_exceeded`、`maximum context length`、`token limit`、`reduce the length`。表示"输入太长了"。
- **RETRYABLE**：429、`rate_limit`、500/502/503、`overloaded`、`timeout`。临时性故障，可以等等再试。默认未识别错误也按 RETRYABLE 处理（乐观策略）。

#### CONTEXT_TOO_LONG 触发上下文压缩后重试

如果分类是 CONTEXT_TOO_LONG，`on_context_too_long` 回调被调用——它会调 `compactor.prune_old_tool_results(messages)` 把老的工具结果剪短，然后返回 True 表示"压缩成功了，再试一次"。这一次重试成功的概率非常高，因为压缩后的 messages 通常能落回模型窗口。

#### Jittered Exponential Backoff

对 RETRYABLE 错误，系统用"带抖动的指数退避 (Jittered Exponential Backoff)"。

> **什么是指数退避？** 第一次失败等 1 秒，第二次等 2 秒，第三次等 4 秒——每次等待时间翻倍。
>
> **什么是 Jitter（抖动）？** 在退避时间上加一个随机扰动。本系统公式是 `min(cap, base * 2^attempt) * uniform(0.5, 1.0)`，base=1.0，cap=30.0。也就是第 N 次重试等 0.5×2^N 到 1.0×2^N 秒之间的随机值。
>
> **为什么要加 Jitter？** 假设服务端因为限流挂了，1000 个客户端同时收到 429。如果它们都用"固定指数退避"，它们会在完全相同的时刻一起重试，再次把服务打挂。这叫"群体踩踏 (Thundering Herd)"。加随机抖动后，这些客户端的重试时间被分散开了，服务能逐步恢复。

`max_retries = 3`：最多重试 3 次后还失败就抛出。3 次重试的累计等待时间在 (0.5+1.0+2.0) ~ (1.0+2.0+4.0) = 3.5~7s 之间，对用户体验不至于太糟，又给了服务端足够缓冲。

### 3.8 AgentContextCompactor（消息级压缩）

`AgentContextCompactor`（在 `agent_runtime/context_compactor.py`）专门压缩 Agent 循环里的 `messages` 数组。

> **触发条件**：当本次 Agent 累计的 `prompt_tokens >= 0.65 × 128_000 = 83_200` Token 时压缩。0.65 是阈值比例，128K 是保守的模型窗口估计。注意它和 RAG 链路里那个 `COMPRESS_THRESHOLD_RATIO=0.75` 不是同一个东西——那个是面向 1M 模型窗口的会话级压缩比例，这个是 Agent 内部消息列表的压缩比例。

**保护策略**：

- **头保护**：所有 `role="system"` 的消息绝不动（包括 SYSTEM_PROMPT 和 tool manifest）。
- **尾保护**：最近的 `_PROTECT_TAIL_TOOL_RESULTS = 4` 条 `role="tool"` 消息绝不动。因为它们极可能是当前推理步骤所需的最新数据，丢了 Agent 直接懵。
- **中间剪枝**：除"尾部 4 条"以外的旧 tool 消息，被替换为 `_summarize_tool_result(tool_name, content)` 生成的结构化摘要——包含 `工具名 / 结果类型（JSON dict/array/text）/ 大小 / 首行预览`。这比直接截断好——LLM 知道"那个工具被调过、当时返回了一份带 N 条结果的 JSON 数组"，即使具体内容不在了，也能继续推理。

**和 RAG 链路 CompactionService 的根本区别**：

| 维度 | Agent ContextCompactor | RAG CompactionService |
|---|---|---|
| 作用对象 | 一次 Agent run 内部的 messages 列表 | 跨多轮对话的 chat 历史 |
| 触发频率 | 单次 run 内可能多次（每次 tool 批量后检查） | 每 20 轮触发一次 |
| 压缩方法 | 把旧 tool 结果替换为结构化摘要 | 用 LLM 把旧对话压成自然语言摘要 |
| 输出去向 | 当场喂回下一轮 LLM | 写入 `session_state.summary` 长期保存 |

### 3.9 主循环 dispatch 调度

Agent 主循环的每一轮分为几个阶段（在 `run_react_agent_stream` 里）：

1. **预算检查**：`budget.check()`，如果触发就 `stop_reason` 跳出。
2. **消费一步预算**：`budget.consume_step()`。
3. **LLM 调用**：通过 `call_with_retry` 调 `client.chat.completions.create(...)`，带工具 schemas、`tool_choice="auto"`（让模型自己决定调不调工具）、`temperature=settings.AGENT_TEMPERATURE=0.2`（低温度让推理更稳定，但还有少量随机避免死循环）。
4. **解析响应**：从 `response.choices[0].message` 拿 `content`（最终文本）和 `tool_calls`（工具调用列表）。Token 用量累加到预算。
5. **如果有工具调用**：把 assistant 这条消息（含 tool_calls）追加到 messages，然后对每个 tool_call 串行处理：
   - 调用 `_args_summary` 给前端推 `TOOL_START` 事件。
   - 检查 per_tool 上限（同一工具调用了 ≥6 次直接错误）。
   - 检查工具是否存在。
   - `parse_tool_arguments` 把 LLM 给的 JSON 字符串解析为 dict。
   - 用 `asyncio.wait_for(registry.dispatch(...), timeout=AGENT_TOOL_TIMEOUT_SECONDS=20)` 跑工具，超时丢 `tool_timeout` 错误。
   - `registry.dispatch` 内部会做 Pydantic 校验、字符数检查（`AGENT_MAX_TOOL_ARG_CHARS=4000`）、实际执行、结果序列化、`max_result_chars` 截断（带 `_truncated=True` 标记，让 LLM 知道有截断发生）。
   - 工具失败 → `budget.refund_step()`。
   - 把工具结果作为 `role="tool"` 消息追加到 messages（`_observation_for_llm` 把结果截断到 6000 字符避免炸 messages）。
   - 追加一条 `trace` 记录用于回看，并 `append_step` 持久化到 `agent_steps` 表。
   - 推 `TOOL_DONE` 事件给前端。
6. **工具批结束**，调用 `compactor.should_compact(budget.prompt_tokens)` 判断要不要压缩 messages。
7. **如果没工具调用且有 assistant_content**：那就是最终答案。写 `TEXT` 事件、记轨迹、`append_step(action_type="final_answer")`、break。
8. **如果空响应（没工具又没文本）**：追加一条 user 消息 "Please provide a final answer now based on gathered tool outputs." 推它一把。

### 3.10 HarnessEvent 实时事件流

Agent 的整个推理过程对前端透明。每一步的关键节点都通过 SSE 推送一种 `HarnessEvent` 事件。事件类型有 7 种（枚举里其实有 STATUS/TOOL_START/TOOL_DONE/TEXT/BUDGET/ERROR/DONE 七项）：

| 事件类型 | 数据字段 | 前端如何渲染 |
|---|---|---|
| `STATUS` | `message`（如"开始执行..."） | 灰色 ⏳ 行 |
| `TOOL_START` | `tool`（工具名）、`args_summary`（参数摘要） | 行显示工具 emoji + 名字 + 参数预览（k=v 缩写） |
| `TOOL_DONE` | `tool`、`result_summary`、`tool_latency_ms`、`is_error` | 缩进显示 ✅/❌ + 结果摘要 + 耗时 |
| `TEXT` | `content`（最终答案） | 主聊天气泡里逐段显示 |
| `BUDGET` | `steps`、`tool_calls`、`prompt_tokens`、`completion_tokens`、`elapsed_s` | 底部状态条，显示用量 |
| `ERROR` | `error`（错误消息） | ⚠️ 行 |
| `DONE` | （无） | 关闭流，触发 UI 收尾 |

前端组件 `AgentToolTrace.vue` 接收这些事件流，渲染成可折叠的"工具执行过程"面板。`displayEvents` 只过滤 `tool_start/tool_done/error/budget`（state 太碎不显示），`toolEmoji` 表把工具名映射到 emoji。

### 3.11 AgentRun / AgentStep 持久化

每次 Agent run 在 PostgreSQL 都留下完整轨迹，便于事后审计、复盘和评测。

- **AgentRun**：一条 run 一条记录。字段：`run_id`、`user_id`、`session_id`、`goal`（用户原话）、`mode`（"function_calling"）、`status`（completed/stopped/failed）、`final_answer`、`steps_used`、`tool_calls`、`prompt_tokens`、`completion_tokens`、`total_latency_ms`、`error_message`、`budget_stop_reason`。
- **AgentStep**：每一步一条记录。字段：`run_id`、`step_index`、`action_type`（tool_call/final_answer/error/budget_stop）、`tool_name`、`tool_call_id`、`tool_args`、`observation`、`assistant_content`、`is_error`、`latency_ms`。

- `create_run`：run 开始时插入。
- `append_step`：每个工具结束/最终答案时插入。
- `finish_run`：run 结束时把汇总信息写回 AgentRun。
- `aggregate_trajectory_metrics(user_id, session_id=None)`：聚合一段时间内的 runs，输出"平均步数""平均工具调用数""平均延迟""失败率"等，给前端的 `/api/v1/agent/metrics` 接口用。

### 3.12 Agent 链路对记忆的特殊处理

Agent 链路里**不经过 Planner**，因为 Agent 是用户显式选择的"复杂模式"，没必要再让 Planner 决定要不要召回。系统直接拿用户原始消息作为 query 调 `recall_relevant`，召回全部 memory_types，把记忆塞进 `assemble_answer_context` 的 retrieved_context 槽。

Agent 链路结束时，`safe_background_task(post_turn_maintenance_service.run(session_id, user_id, allow_memory_write=True))` 显式带 `allow_memory_write=True`。这是和 RAG 链路的另一个不同——Agent 模式下还允许 LLM 通过 `save_memory` 工具主动写入记忆（普通对话里只有自动提取那一条路径）。

### 3.13 它和系统其他部分如何衔接

Agent Harness 是"复杂任务"主路径。它依赖 ToolRegistry 上注册的所有工具（这些工具背后又依赖 RAG、记忆、简历、面试历史、上传、Tavily、Lever 等各种子系统）。它的产物（AgentRun + AgentStep）会进入评测体系的 L3 轨迹层做路由准确性评测。下一章我们看记忆系统——它既被 RAG 链路用，也被 Agent 链路用，是系统的"长期大脑"。

---
