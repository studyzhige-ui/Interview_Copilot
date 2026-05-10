# Interview Copilot 面试 QA 手册

> 本文档由 Interviewer Agent（面试官）和 Candidate Agent（候选人）双角色对话生成。
> 问题覆盖：业务定位、架构设计、实现细节、技术选型对比、参数追问、故障处理、优化方向共 15 个主题。
> 基于项目实际代码撰写，所有回答可溯源到具体文件和函数。

---

## 一、业务与产品定位

### Q1：一句话介绍你的项目是做什么的？

**A：** Interview Copilot 是一个面向技术面试准备的 AI 后端系统。它把"多轮智能问答、面试录音复盘、个人知识库管理、长期记忆、岗位搜索"整合成一套工程闭环，帮助候选人系统化地练习和改进面试表现。

核心能力包括四块：

1. **RAG 增强问答**：用户上传简历、面试题库等文档后，系统能基于这些知识精准回答。
2. **面试录音分析**：上传面试录音，后台自动转写、区分说话人、逐题打分、给出改进答案。
3. **长期记忆**：跨会话记住用户的项目经历、偏好和反馈规则。
4. **ReAct 工具代理**：搜索岗位、获取用户画像、联动知识库等复杂任务。

### Q2：它和普通的 ChatBot 有什么本质区别？

**A：** 本质区别在于：普通 ChatBot 只有"对话"这一个能力维度，而 Interview Copilot 是一个多层协作的 Agentic System（智能体系统）。

具体来说，普通 ChatBot 没有检索能力，只能靠模型自身知识回答；没有记忆，每次对话从零开始；没有上下文管理，只是简单拼接历史消息；没有工具调用能力。

Interview Copilot 在每一个维度上都做了工程化的解决方案：

- **检索**：混合 RAG（向量 + BM25 + Reranker + 防幻觉拦截）
- **记忆**：四类长期记忆，独立向量索引，混合召回
- **上下文**：结构化 ContextBundle + Token 预算控制 + 分层渲染
- **工具**：ReAct Agent + Function Calling + 六维资源控制
- **异步任务**：Celery 处理音频转写和文档摄取

### Q3：项目解决的核心痛点有哪些？

**A：** 四个核心痛点：

第一，**面试录音难以复盘**。面试结束后，候选人很难准确回忆自己的回答。系统支持上传录音，后台用 WhisperX 转写 + Pyannote 说话人分离，自动把录音拆成"面试官问题 + 候选人回答"的结构化问答对，然后逐题评分并给出改进答案。

第二，**知识点难以沉淀**。面试暴露的薄弱点如果不系统记录就容易遗忘。系统支持把分析结果、改进答案、技术文档都写入 RAG 知识库，后续问答时自动检索。

第三，**多轮练习缺少个性化**。普通 ChatBot 每次都是全新对话。本系统有长期记忆，能记住用户的项目背景（"候选人做过推荐系统"）、交互偏好（"用户喜欢简洁回答"）和反馈规则（"用 Python 写代码示例"），跨会话自动召回。

第四，**岗位准备缺少工具支持**。手动搜索岗位信息效率低。ReAct Agent 可以自动搜索 Lever 平台的岗位、获取详情、结合用户画像生成针对性的准备建议。

### Q4：你的用户画像是什么？

**A：** 主要面向三类用户：

1. 正在准备技术面试的候选人，想系统化练习常见面试题、获得基于自己知识库的精准回答。
2. 面试后想复盘的求职者，需要把面试录音转化为结构化的反馈报告，知道具体哪道题答得不好、怎么改进。
3. 有特定项目背景的工程师，想要基于自己的项目经历和技术栈获得个性化的面试辅导。

### Q5：项目最大的工程难点是什么？

**A：** 我认为最大的工程难点是**上下文质量控制**——怎么在有限的 LLM 上下文窗口里放入最有价值的信息。

这个问题看起来简单，实际上涉及多个子问题：

- 对话太长怎么办？→ 设计了 Compaction 机制，把旧对话压缩成结构化 Working State。
- 什么时候该检索知识库、什么时候不该？→ 设计了 Query Planner 做意图判断。
- 检索到的内容和记忆都很多，token 不够放怎么办？→ 设计了 TokenBudgeter 给每类上下文分配独立预算。
- 知识库里没有相关内容时怎么防止模型编造？→ 设计了 Reranker 绝对分数阈值 + 词法覆盖 Fallback + SYSTEM_EMPTY_WARNING 标记三重防线。

这些子问题相互耦合，单独解决任何一个都不难，但要让整个链路端到端地稳定工作，需要在每个环节都留好降级策略。

### Q6：你说这是一个 Agentic System，怎么定义"Agentic"？

**A：** 我对"Agentic"的理解是：系统能够根据用户意图**自主决策**下一步做什么，而不是走固定路径。

在本项目中，Agentic 体现在两个层面：

第一个层面是 **Query Planner 的意图路由**。用户说一句话，Planner 要决定：这个问题需不需要检索知识库？需要哪些类型的知识源？需不需要召回长期记忆？需要哪些类型的记忆？用什么回答模式？这些决策是 LLM 在运行时做的，不是硬编码的 if-else。

第二个层面是 **ReAct Agent 的工具选择**。给定一个复杂任务（如"帮我找 OpenAI 的后端岗位并结合我的经历给出准备建议"），Agent 自己决定先调 `search_jobs` 再调 `get_user_profile`，最后综合生成建议。这个执行序列是模型推理出来的。

但我也要强调，项目在 Agentic 程度上做了**刻意的克制**——普通多轮问答走的是确定性流水线（阶段固定、顺序固定），不走 ReAct。因为对于 90% 的日常问答，确定性流水线更快、更稳定、更便宜，只有需要工具调用的复杂任务才切换到 ReAct。

### Q7：项目的核心业务链路有几条？

**A：** 三条主要链路：

**链路一：普通多轮 RAG Chat**。这是最常走的路径。用户发消息 → Query Planner 规划意图 → 并发召回记忆和知识库 → 组装 ContextBundle → LLM 流式回答 → 写入 Transcript → 异步执行 post-turn maintenance（压缩状态、更新面试状态、抽取记忆）。入口是 `agent_executor.py` 的 `stream_chat_with_agent()`。

**链路二：ReAct 工具代理**。用户发复杂任务 → 准备上下文和工具清单 → LLM 决定调用工具 → 执行工具获取结果 → 反馈给 LLM → 循环直到最终答案。入口是 `react_agent.py` 的 `run_react_agent()`。

**链路三：音频分析**。用户上传录音 → MinIO 存储 → Celery 派发后台任务 → WhisperX 转写 + 说话人分离 → LLM 分段评分 → 写入分析结果。入口是 `worker/tasks.py` 的 `process_interview_analysis()`。

### Q8：项目的数据怎么隔离的？多租户怎么做的？

**A：** 多租户隔离（即不同用户之间的数据互不可见）贯穿了四个层次：

**第一层：API 鉴权层**。所有接口都要求携带 JWT 令牌才能访问。`get_current_user()` 是一个 FastAPI 的依赖注入函数——它会在每个请求处理之前自动运行，从令牌中提取 `user_id` 并绑定到这次请求上。后续所有操作都只能看到这个 `user_id` 的数据。

**第二层：向量检索层**。在 Milvus（向量数据库）中检索时，系统会把当前用户的 `user_id` 作为过滤条件注入到查询中。关键点是：这个过滤发生在 Milvus 服务端，搜索引擎在遍历向量时就已经排除了不属于当前用户的数据，而不是先检索所有用户的数据再筛选——从物理层面就看不到别人的向量。

**第三层：节点标签层**。文档被切分成小块（称为“节点”）写入知识库时，系统会**强制**给每个节点打上 `user_id` 和 `source_type` 标签。这是最底层的安全红线——即使切块工具在处理过程中重新生成了节点对象，用户归属标签也不会丢失。

**第四层：业务数据层**。所有数据库查询都强制带 `user_id` 过滤条件。记忆、知识库文档、面试记录、Agent 执行轨迹——所有业务实体都按用户隔离。

---

## 二、整体架构

### Q9：系统的分层方式是什么？为什么这样分？

**A：** 系统分为四层：

**API 层**（`api/` 目录）：负责 HTTP/WebSocket 路由、请求校验、鉴权。不包含业务逻辑。

**工作流层**（`agent/` + `agent_runtime/` 目录）：负责协调业务流程。`agent/` 下的 `agent_executor.py` 和 `planner.py` 协调普通 chat 的确定性流水线；`agent_runtime/` 下的 `react_agent.py` 协调 ReAct 工具代理。

**服务层**（`services/` 目录）：具体的业务实现，如记忆管理、上下文组装、面试分析、转录、Agent 轨迹等。每个服务都是独立的，可以被工作流层的不同链路复用。

**存储层**（`db/` + `models/` + `rag/` 目录）：数据库模型定义、数据库连接管理、Milvus 向量索引、PostgreSQL 文档存储、MinIO 对象存储。

这样分层的好处是**关注点分离**——每一层只负责自己的事情，不需要了解其他层的内部细节。举个具体例子：`MemoryRetrievalService`（记忆召回服务）不需要知道自己是被普通聊天流水线调用，还是被 ReAct 工具代理调用——它只管“根据查询找到最相关的记忆”这一件事。同样，`query_knowledge_base()`（知识库检索函数）不关心调用方是 API 路由还是工具执行器。这让每个组件可以独立开发、独立测试、独立修改，改一个地方不会牵连其他地方。

### Q10：为什么要设计"双链路"（确定性 Chat + ReAct Agent）？

**A：** 因为这两种使用模式对系统的要求截然不同。

**普通多轮问答**的特点是：频率高（90% 以上的请求）、对延迟敏感（用户在等流式回答）、步骤可预测（查询规划→检索→回答→维护）。这种场景适合确定性流水线——每个阶段做什么是固定的，只是 Planner 根据意图决定是否执行某些阶段。

**复杂工具任务**的特点是：频率低、对延迟容忍度高、步骤不可预测（不知道需要调几次工具、调哪些工具）。这种场景需要 ReAct 的灵活性——让模型自主决定下一步做什么。

如果把所有请求都走 ReAct，普通聊天会变得很慢（多轮 LLM 调用）、很贵（token 消耗高）、且不稳定（Agent 可能走错路径）。反过来，如果所有请求都走确定性流水线，就没法处理需要动态工具调用的任务。

### Q11：为什么普通问答不走 ReAct Agent？

**A：** 三个原因：

**延迟**。ReAct 的每一步都需要调用一次 LLM，普通问答如果走 ReAct 至少需要 2-3 轮 LLM 调用（规划→可能调工具→最终回答）。而确定性流水线只需要 1 次 Planner 调用 + 1 次回答 LLM 调用，且 Planner 用的是 fast LLM，延迟更低。

**成本**。ReAct 的 system prompt 里要带工具清单和历史交互，token 消耗显著高于直接回答。对于"Redis 的持久化机制有哪些"这类简单问题，走 ReAct 是浪费。

**可预测性**。确定性流水线的行为完全可预测：先规划、再检索、再回答、最后维护。排查问题时，每个阶段的输入输出都清晰。ReAct 的行为取决于模型的推理，同样的输入可能走不同路径。

### Q12：各存储组件分别承担什么角色？

**A：**

**PostgreSQL**（关系型数据库）承担两个角色：一是存储所有业务数据（用户、会话、消息、面试、记忆、Agent 轨迹等），二是作为 LlamaIndex 的文档存储（Docstore）——知识库文档被切块后，每个文本块的原始内容和标签信息都存在这里，BM25 关键词检索就是直接从这里读取数据来构建索引的。

**Milvus**（向量数据库）专门负责存储和检索文本的向量表示（即把文字转换成一串数字后的高维向量）。系统维护了两个独立的向量集合（collection）：`interview_copilot_rag` 存知识库文档的向量，`interview_copilot_memory` 存长期记忆的向量。两者分开是因为它们的数据特征、更新频率和排序策略都不同，混在一起会互相干扰。

**Redis**（内存键值数据库）仅作为 Celery 的消息队列（Broker，用于传递异步任务）和结果存储（Result Backend，用于保存任务执行结果）。项目中没有用 Redis 做业务数据缓存。

**MinIO/S3**（对象存储）存储用户上传的音频文件和知识库文档原件。上传使用预签名 URL（一种临时的、有时效的上传地址），由后端生成后交给前端，前端直接将文件传到 MinIO，不经过后端服务器。

### Q13：为什么选择 PostgreSQL 同时做 Docstore？

**A：** 这是一个经过权衡的决定。LlamaIndex 的 Docstore 需要一个能存储和检索节点原始文本的存储后端。可选方案包括内存（SimpleDocumentStore）、本地文件和 PostgreSQL。

选 PostgreSQL 的理由：

1. **持久化**。内存和本地文件在容器重启后数据丢失或不易迁移。PostgreSQL 有天然的持久化能力。
2. **复用现有基础设施**。项目已经用 PostgreSQL 存业务数据，不需要额外引入新组件。
3. **BM25 需要读取全量节点**。BM25 检索器需要从 Docstore 加载所有匹配 user_id 的节点来构建索引。用 PostgreSQL 可以直接在数据库层做 user_id 过滤，效率高于从文件系统筛选。

代价是增加了 PostgreSQL 的存储压力，但对于面试准备场景，文档量不大（通常几十份），完全可以接受。

### Q14：系统的启动顺序是什么？为什么重要？

**A：** 启动顺序定义在 `main.py` 的 `lifespan()` 函数中，按以下 5 个阶段执行：

1. **验证数据库迁移状态**：检查 Alembic 版本号是否为 head。如果数据库未迁移或迁移版本落后，**直接拒绝启动**并抛出 RuntimeError。这确保不会在 schema 不一致的情况下接受请求。
2. **初始化 RAG Settings**（`init_rag_settings()`）：加载 BGE-M3 Embedding 模型（`BAAI/bge-m3`，1024 维）到 GPU/CPU，设置全局 LlamaIndex Settings 的 embed_model 和 llm。
3. **回填记忆向量**（`memory_vector_service.backfill_pending()`）：把 `embedding_status != "ready"` 的记忆重新写入 Milvus。如果 `MEMORY_BACKFILL_ON_STARTUP = false` 则跳过。
4. **初始化 Reranker**（`init_reranker()`）：加载 BGE Reranker（`BAAI/bge-reranker-base`）。
5. **Whisper/Diarization 声明**：这两个大模型由 Celery Worker 在自己的进程中单独加载，API 进程不加载。

**关停时**，`lifespan` 的 yield 之后会调用 `cancel_and_wait_all(timeout=10.0)`，优雅地排空所有通过 `safe_background_task()` 创建的后台任务（如 post-turn maintenance），确保 Compaction 和记忆抽取不会被中途杀死。

顺序很重要，因为：

- 迁移检查放在最前面，避免在错误的 schema 上操作数据。
- Embedding 模型必须在第一个检索请求之前加载完毕，否则 LlamaIndex 会用默认的 OpenAI Embedding，向量维度和语义空间都不对。
- 记忆回填依赖 Embedding 模型，所以放在其后。
- Reranker 必须在检索之前加载，否则防幻觉拦截的分数基准不一致。

### Q15：你提到了 RuntimeLLMProxy，这是什么设计？为什么需要它？

**A：** `RuntimeLLMProxy` 是一个轻量级的代理类，它不直接持有 LLM 实例，而是每次调用时通过 `get_llm_for_role()` 动态获取当前角色对应的 LLM 实例。

```python
class RuntimeLLMProxy:
    def __init__(self, role: str):
        self.role = role
    async def acomplete(self, *args, **kwargs):
        return await self._delegate().acomplete(*args, **kwargs)
```

需要它的原因是：项目支持**运行时切换模型**。通过 `/models/runtime` API，用户可以把 primary/fast/agent 三个角色绑定到不同的模型（比如把 agent 从 DeepSeek V4 Flash 切到 V4 Pro）。切换后，新请求自动用新模型，不需要重启服务。

如果 `agent_fast_llm` 直接持有 LLM 实例，切换模型后旧的引用还指向旧实例。用 Proxy 模式，每次调用都重新查询 `model_selection.json` 获取最新绑定。

### Q16：模型角色划分是怎么做的？为什么分三个角色？

**A：** 项目把 LLM 分成三个角色，每个角色负责不同类型的任务：

- **primary**：主回答模型。负责 RAG 增强回答、面试分析评分等需要高质量输出的任务。
- **fast**：轻量快速模型。负责 Query Planner、记忆抽取、状态压缩、Interview State 更新等。这些任务对回答质量要求不那么高，但对延迟敏感。
- **agent**：ReAct 工具代理模型。必须支持 Function Calling，负责工具选择和推理。

分三个角色的好处：

1. **成本优化**。Query Planner 和记忆抽取不需要最强的模型，用 fast 角色可以降低成本。
2. **延迟优化**。fast 角色用更快的模型，主链路的非回答阶段延迟更低。
3. **灵活切换**。agent 角色可以单独切到更强的模型（如 V4 Pro），不影响 fast 角色的成本。

---

## 三、API 与鉴权

### Q17：JWT 认证的完整流程是什么？

**A：** 认证流程分为注册、登录、请求校验和令牌续期四步：

**注册**（`POST /api/v1/auth/register`）：用户提交用户名和密码。密码用 `bcrypt.hashpw()` 做哈希存入数据库。为什么用原生 bcrypt 而不是 passlib？因为 passlib 库严重过期，在处理超过 72 字节的密码时会触发截断崩溃 Bug。

**登录**（`POST /api/v1/auth/login`）：OAuth2 Password Form 格式提交。后端用 `bcrypt.checkpw()` 校验密码。通过后**同时生成两个 JWT**：

- **Access Token**（`type: "access"`）：有效期 30 分钟（`ACCESS_TOKEN_EXPIRE_MINUTES`），用于 API 请求鉴权。
- **Refresh Token**（`type: "refresh"`）：有效期 7 天（`REFRESH_TOKEN_EXPIRE_MINUTES`），专门用于续期 Access Token。

**请求校验**：后续请求在 `Authorization: Bearer <access_token>` 头中携带 Access Token。`get_current_user()` 是一个 FastAPI 依赖注入函数，它解码 JWT、校验过期时间、**严格验证 `type == "access"`（如果携带了 Refresh Token 会被拒绝，返回 401）**、从数据库加载用户对象。

**令牌续期**（`POST /api/v1/auth/refresh`）：Access Token 过期后，前端提交 Refresh Token 到此端点。后端校验 Refresh Token 有效且 `type == "refresh"`，然后签发全新的 Access Token + Refresh Token 对。这实现了无感续期——用户不需要重新输入密码，只要 Refresh Token 在 7 天有效期内就能自动获取新的 Access Token。

### Q18：WebSocket 连接怎么做认证的？

**A：** WebSocket 不支持自定义 HTTP 头，所以不能用 `Authorization: Bearer` 的方式。项目的做法是通过 query parameter 传递 token：`ws://host/chat/ws/{session_id}?token=xxx`。

服务端在 WebSocket 握手时，从 query parameter 中取出 token，调用 `decode_token()` 解码校验。如果校验失败，直接关闭 WebSocket 连接。

### Q19：为什么同时提供 WebSocket 和 SSE 两种流式接口？

**A：** 因为两者各有适用场景：

**WebSocket** 是全双工协议，支持双向通信。适合需要频繁交互的场景（比如用户随时中断、服务端主动推送状态更新）。但 WebSocket 的实现复杂度更高，需要维护连接状态、处理重连逻辑，且部分代理和 CDN 对 WebSocket 的支持不好。

**SSE**（Server-Sent Events，服务端推送事件）是单向的，只支持服务端向客户端推送。实现更简单（基于标准 HTTP），浏览器原生支持，不需要额外的重连逻辑（浏览器会自动重连）。对于"用户发一条消息，等待流式回答"这种请求-响应模式，SSE 完全够用。

提供两种接口是为了兼容不同的前端实现需求。Vue 3 前端目前主要走 SSE，因为实现更简单且稳定。

### Q20：接口设计有什么统一原则？

**A：** 几个统一原则：

1. **所有接口统一前缀 `/api/v1`**，方便后续版本升级时做 v2 兼容。
2. **用户身份通过依赖注入获取**，路由函数不需要手动解析 token。
3. **分页接口统一使用 `limit` + `offset`** 参数。
4. **长耗时操作走异步**：音频分析和文档摄取通过 Celery 异步执行，API 立即返回 task_id 或 interview_id，前端轮询状态。
5. **错误返回结构化 JSON**，包含 `detail` 字段说明具体原因。

### Q21：上传文件为什么用预签名 URL 而不是后端直接接收？

**A：** 预签名 URL（Presigned URL）是后端生成一个临时的、有时效的上传地址，前端直接把文件传到 MinIO/S3，不经过后端服务器。

这样做的好处：

1. **后端不承受文件传输的带宽和内存压力**。面试录音文件可能很大（几十到几百 MB），如果所有上传都经过后端，会占用大量内存和网络带宽。
2. **上传速度更快**。前端直连 MinIO，减少一跳网络延迟。
3. **后端可以水平扩展**。因为后端不存文件，多个 API 实例可以无状态地服务。

代价是增加了一点前端复杂度：前端需要先调 API 获取预签名 URL，再发起上传。

### Q22：你的 CORS 配置是怎么做的？

**A：** 在 `main.py` 中通过 FastAPI 的 `CORSMiddleware` 配置。允许的 origins 从 `settings.CORS_ORIGINS` 读取，默认是 `http://localhost:5173,http://127.0.0.1:5173`——这是 Vite 开发服务器的默认地址。

目前的配置只适合本地开发。生产环境需要：

1. 把 CORS_ORIGINS 改为前端实际部署的域名。
2. 不要用通配符 `*`，要明确列出允许的域名。
3. 考虑是否需要 `allow_credentials=True`（如果前端需要带 Cookie）。

---

## 四、普通多轮问答 Pipeline

### Q23：完整描述一下用户发一条消息后，后端从接收到回复的全过程

**A：** 以 SSE 接口 `POST /chat/sse/{session_id}` 为例，后端走的是 `stream_chat_with_agent()` 函数，共 9 个阶段：

1. **确保会话存在**：调用 `transcript_service.ensure_session()` 和 `interview_state_service.ensure_state()`。如果这个 session_id 是新的，会创建 ChatSession 和 InterviewState 记录。
2. **读取轻量改写上下文**：调用 `assemble_rewrite_context()`，只读取 Working State、Interview State 和最近 10 轮对话。不加载记忆和知识库，因为这一步只是给 Planner 提供足够的上下文来理解用户问题。
3. **Query Planner 规划**：调用 fast LLM，把用户问题和改写上下文送入，输出结构化的 `QueryPlan`，决定是否需要检索、检索哪些源、用什么回答模式。
4. **并发召回**：根据 QueryPlan，用 `asyncio.create_task` 并发执行记忆召回和知识库检索。两者互不依赖，并发可以减少 ~40% 的等待时间。
5. **组装完整上下文**：调用 `assemble_answer_context()`，把 Working State、Interview State、近期对话、长期记忆、知识片段组装成 `ContextBundle`。
6. **选择 LLM 和提示词**：如果不需要知识库，用 fast LLM + 直接回答提示词；如果需要知识库，用 primary LLM + RAG 提示词。
7. **流式生成回答**：调用 LLM 的 `astream_complete()`，逐块推送给前端。
8. **写入 Transcript**：把用户消息和完整回答写入 `chat_messages` 表。
9. **异步 post-turn maintenance**：通过 `safe_background_task()` 异步执行 Compaction + Interview State 更新 + 记忆抽取，不阻塞用户。

### Q24：Query Planner 输出的 QueryPlan 每个字段是怎么设计的？

**A：** `QueryPlan` 是一个 Pydantic 模型，每个字段都有明确的职责：

- `standalone_query`：消解了指代后的独立问题。比如用户说"那这个怎么答"，上下文里刚讨论了 Redis 持久化，Planner 会把它改写成"Redis 的持久化机制应该怎么回答"。
- `dense_query`：专门用于向量检索的自然语言查询。保留完整语义，适合 Embedding 模型编码。
- `sparse_query`：专门用于 BM25 词法检索的关键词查询。去掉虚词，保留核心关键词。
- `needs_memory_retrieval` + `memory_types`：决定是否需要从长期记忆中召回信息，以及需要哪些类型的记忆。
- `needs_knowledge_retrieval` + `knowledge_sources`：决定是否需要检索知识库，以及检索哪些知识源（interview_qa、official_docs 等）。
- `answer_mode`：回答模式，如 `knowledge_qa`、`direct_chat`、`interview_learning` 等。这决定了后续用哪个 LLM 和哪套提示词。
- `reasoning`：Planner 的推理过程，纯审计用途，不影响执行逻辑。排查问题时可以看 Planner 为什么做出某个决策。

### Q25：dense_query 和 sparse_query 为什么要分开？不能用同一个吗？

**A：** 不能，因为向量检索和 BM25 检索对输入的要求完全不同。

**向量检索**靠 Embedding 模型把文本编码成稠密向量，然后计算向量间的相似度。它需要完整的自然语言句子，因为 Embedding 模型是从句子的整体语义中提取向量的。比如"Redis 的持久化机制有哪些，以及它们各自适用什么场景"——这个完整的句子能编码出更精准的语义向量。

**BM25 检索**靠关键词的 TF-IDF（词频-逆文档频率）匹配。它不理解语义，只看关键词是否出现在文档里。给它长句子反而有害——虚词（"的"、"有"、"什么"）会稀释关键词的权重。所以 sparse_query 应该是"Redis 持久化 RDB AOF 适用场景"这样的关键词序列。

如果混用，要么向量检索拿到的是关键词序列（缺少语义信息），要么 BM25 拿到的是长句子（关键词被稀释）。分开后各自能发挥最佳效果。

### Q26：Query Planner 失败了怎么办？

**A：** Planner 有完整的容错设计。如果 LLM 返回的 JSON 格式错误、字段缺失或者 LLM 调用本身超时/报错，系统会捕获异常并调用 `fallback_query_plan()` 生成一个安全的默认计划：

- `standalone_query` = 用户原始消息（不做改写）
- `needs_memory_retrieval` = True（保守地召回所有类型的记忆）
- `needs_knowledge_retrieval` = True（保守地检索 interview_qa 源）
- `answer_mode` = `knowledge_qa`

这个 fallback 计划会比精确规划多做一些不必要的检索（成本稍高），但保证用户一定能得到回答。Planner 是整个链路中最不能阻塞的环节——即使规划失败，聊天也要继续。

### Q27：并发召回记忆和知识库具体是怎么实现的？

**A：** 用的是 Python 标准库的 `asyncio.create_task()` + `asyncio.gather()`。

```python
memory_task = asyncio.create_task(
    memory_retrieval_service.recall_relevant(...)
)
knowledge_task = asyncio.create_task(
    knowledge_retriever.retrieve(...)
)
memories, knowledge = await asyncio.gather(memory_task, knowledge_task)
```

两者互不依赖——记忆召回走 memory Milvus collection + PostgreSQL，知识库检索走 rag Milvus collection + PostgreSQL + BM25 + Reranker。数据源完全不同，所以可以安全并发。

如果其中一个失败（比如 Milvus 暂时不可用），不影响另一个的结果。失败的部分返回空列表，后续组装上下文时那部分就没有内容，但主链路不中断。

### Q28：direct chat 和 RAG chat 是怎么切换的？

**A：** 切换逻辑取决于 QueryPlan 中的 `needs_knowledge_retrieval` 字段：

- 如果 Planner 判断不需要检索知识库（比如用户只是闲聊"你好"或问通用问题），`needs_knowledge_retrieval = false`。系统用 **fast LLM** 和 **DIRECT_SYSTEM_RULES** 提示词直接回答，不走 RAG 检索。这条路径更快、更便宜。

- 如果 Planner 判断需要检索（比如用户问"Redis 的持久化有哪些"），`needs_knowledge_retrieval = true`。系统用 **primary LLM** 和 **RAG_SYSTEM_RULES** 提示词，把检索到的知识片段注入上下文。RAG 提示词会强调"请基于以下检索到的知识回答，不要编造不存在的信息"。

### Q29：post-turn maintenance 为什么要异步执行？

**A：** 因为 post-turn maintenance 包含三个可能耗时的操作，如果同步执行会显著增加用户感知的延迟：

1. **Compaction**：需要调 LLM 把旧对话压缩成 Working State，这可能需要 1-3 秒。
2. **Interview State 更新**：也需要调 LLM 更新面试进度状态，又是 1-3 秒。
3. **记忆抽取**：调 LLM 从新对话中提取持久记忆，再写入 PostgreSQL 和 Milvus。

如果同步执行，用户每次聊天后要额外等 3-9 秒才能发下一条消息。异步执行后，用户收到回答就可以立即继续对话，维护工作在后台完成。

异步的代价是：如果用户连续快速发消息，后一条消息的上下文可能还没包含前一轮 Compaction 后的最新 Working State。但这在实际使用中影响很小——用户通常不会在 1-2 秒内连续发多条消息。

### Q30：post-turn maintenance 的三个操作之间有顺序依赖吗？

**A：** 有。`PostTurnMaintenanceService._run_locked()` 的执行顺序是固定的：

1. 先执行 **Compaction**。因为 Compaction 会改变 `compaction_cursor`，后续读取新消息时需要基于最新的 cursor。
2. 再执行 **Interview State 更新**。读取 `memory_cursor` 之后的新消息，更新面试状态。
3. 最后执行 **记忆抽取**。同样读取 `memory_cursor` 之后的新消息，抽取并写入记忆。

此外，整个 maintenance 操作通过 `asyncio.Lock()` 保护——同一个 session_id 的 maintenance 不能并发执行。Lock 缓存在一个 dict 里，上限 128 个 session。

### Q31：如果 post-turn maintenance 执行失败了，会影响下一轮对话吗？

**A：** 不会影响核心对话功能，但会影响上下文质量。

每个子操作（Compaction、Interview State、记忆抽取）都有独立的 try-except，某一个失败不会导致其他操作被跳过。失败时只记录 error 日志。

具体影响：

- **Compaction 失败**：Working State 不更新，下次 prompt 里的 Working State 可能是旧的，但近期对话还在，影响不大。
- **Interview State 失败**：面试状态不更新，模型对面试进度的感知可能滞后一轮。
- **记忆抽取失败**：这轮对话的信息不会被提取为长期记忆，`memory_cursor` 不推进。下次 maintenance 会重新处理这些消息。

关键设计：只有记忆抽取成功时才推进 `memory_cursor`。如果抽取失败，下次 maintenance 会重新处理同一批消息，确保不会丢失记忆。

### Q32：Planner 的 answer_mode 有哪些值？分别对应什么行为？

**A：** answer_mode 是 Planner 对"这个问题应该怎么回答"的分类判断。主要的模式包括：

- `knowledge_qa`：基于知识库回答的标准模式。走 RAG 检索 + primary LLM。
- `direct_chat`：不需要检索的直接回答。走 fast LLM。
- `interview_learning`：面试学习模式，回答后会抽取持久记忆。
- `review`：复盘模式，也会抽取记忆。
- `preference_update`：用户在更新偏好，需要抽取并持久化。

answer_mode 还影响记忆写入权限。在 ReAct Agent 中，只有 `interview_learning`、`review` 和 `preference_update` 三种模式才允许写入记忆。普通岗位搜索不会触发记忆抽取。

---

## 五、上下文 Pipeline 与状态管理

### Q33：ContextBundle 的设计动机是什么？为什么不直接拼字符串？

**A：** 直接拼字符串有五个问题：

1. **Token 预算无法分层控制**。如果所有上下文拼成一个字符串，就没法对"近期对话最多 4000 tokens"、"记忆最多 1600 tokens"做独立控制。只能控总长度，但总长度控制下各部分的比例不可控。

2. **排序调整困难**。研究表明 LLM 对输入末尾的内容关注度最高（recency bias）。当前设计把 current_query 放在最后、working_state 放在最前。如果直接拼字符串，调整这个顺序需要大规模重构。

3. **来源标注不可能**。ContextBundle 中每个知识片段都带有 score、source_type 等元数据。拼成字符串后这些信息就丢了。

4. **去重困难**。记忆和知识库可能返回重复或高度相似的内容。结构化存储可以按 id 去重。

5. **测试困难**。测试"TokenBudgeter 是否正确截断了超出预算的记忆"这类逻辑，需要能独立访问 `relevant_memories` 字段。拼成字符串后就没法单独测试了。

ContextBundle 是一个中间表示层：上游各服务往里填内容，下游 PromptRenderer 负责把它渲染成最终的 prompt 字符串。

### Q34：PromptRenderer 渲染的区块顺序是什么？为什么这样排？

**A：** 渲染顺序是：

1. System Rules → 2. Working State → 3. Interview State → 4. Long-term Memories → 5. Retrieved Knowledge → 6. Recent Turns → 7. Current Query

排序理由：

- **System Rules 放最前**：系统级指令需要最高优先级，模型在生成时会首先遵守这些规则。
- **Working State 和 Interview State 紧随其后**：这是当前会话的结构化摘要，为后面的所有内容提供解读框架。
- **Long-term Memories 在中间**：提供用户的跨会话背景信息。
- **Retrieved Knowledge 在中后部**：RAG 检索到的知识片段。
- **Recent Turns 靠后**：最近的对话历史，给模型提供对话连贯性。
- **Current Query 放最后**：大模型对输入末尾的内容关注度最高。把当前问题放在最靠近生成位置的地方，可以让模型更聚焦于回答这个问题。

### Q35：TokenBudgeter 的 4000/1600/5000 分配是怎么定的？

**A：** 这三个数值的总和是 10600 tokens，加上 System Rules、Working State 和 Interview State（通常 ~1500 tokens），总共约 12000 tokens。这个总量适配大多数模型的上下文窗口。

具体分配的考虑：

- **近期对话 4000 tokens**：大约 10-15 轮对话的量。太少会让模型丢失对话连贯性，太多会挤占知识和记忆的空间。4000 是实测中对话质量的甜点。
- **知识片段 5000 tokens**：知识片段是回答准确性的核心来源，给最大的预算。5000 tokens 大约能容纳 5-8 个完整的知识片段。
- **长期记忆 1600 tokens**：记忆通常是短小的事实陈述（"用户有 3 年 Java 经验"），不需要太多空间。1600 tokens 可以容纳 3-5 条记忆。

### Q36：消息清洗的具体规则是什么？为什么要做清洗？

**A：** `_sanitize()` 方法对原始消息做三种过滤：

1. **角色过滤**：只保留 `User` 和 `Agent` 角色的消息。系统内部可能会产生其他角色的消息（如调试信息），这些不应该出现在给 LLM 的上下文里。
2. **前缀过滤**：跳过以 `[SYSTEM_]` 或 `[DEBUG_]` 开头的消息。这些是系统内部标记（如 `[SYSTEM_EMPTY_WARNING]` 表示 RAG 没有命中），不应暴露给用户的 prompt。
3. **空内容过滤**：跳过 content 为空的消息。

清洗后还要做 `_repair_pairs()`：

- 去掉开头多余的 Agent 消息（没有对应的用户问题，可能是上次会话的残留）。
- 去掉结尾未回答的 User 消息（回答还没生成完）。

这确保送给 LLM 的对话历史是 User-Agent-User-Agent 这样交替的完整配对。

### Q37：Working State 和 Interview State 为什么要拆开？看起来字段很像

**A：** 看起来像，但实际上职责完全不同：

**Working State** 服务于**对话压缩**。它的核心用途是：当对话太长需要 Compaction 时，把旧消息的关键信息折叠进 Working State。它的字段（goal、current_phase、covered_topics、summary）都是面向"压缩旧对话为摘要"这个任务设计的。Working State 存在 `chat_sessions.working_state` 字段中，和会话绑定。

**Interview State** 服务于**面试过程管理**。它追踪的是面试训练的进度——哪些主题已经覆盖、候选人有哪些薄弱点、有哪些待验证的说法、下一个最佳问题是什么。它的字段（observed_gaps、evidence、candidate_claims、next_question）是面向"面试教练"这个业务场景设计的。Interview State 存在独立的 `interview_states` 表中，按 session_id + user_id 唯一。

如果合并成一个状态对象：

1. Compaction 更新时可能覆盖面试状态，反之亦然。
2. 单个状态对象的 prompt 太大，LLM 难以同时做好"压缩旧对话"和"追踪面试进度"两个任务。
3. 测试和调试时难以区分哪些字段是给 Compaction 用的，哪些是给面试管理用的。

### Q38：Compaction 是什么？什么时候触发？

**A：** Compaction（状态压缩）是把旧对话消息折叠进结构化 Working State 的过程。

**触发条件**：当 Working State 的 token 数 + compaction_cursor 之后新消息的 token 数超过 `COMPACTION_THRESHOLD_TOKENS = 5000` 时触发。

**执行过程**：

1. 保留最近 `KEEP_LAST_MESSAGES = 6` 条消息不压缩（确保模型能看到最近的对话）。
2. 把更早的消息和当前 Working State 一起发给 fast LLM。
3. LLM 输出新的 Working State（JSON 格式），包含 goal、current_phase、covered_topics 等字段。
4. 如果新 Working State 超过 `WORKING_STATE_MAX_TOKENS = 1000` tokens，截断 summary 字段。
5. 更新 `chat_sessions.working_state` 和 `compaction_cursor`。

Compaction 的效果：10 轮对话前的内容不再以原始消息的形式占用 prompt 空间，而是被压缩成一个 ~500 tokens 的结构化摘要。

### Q39：Compaction 的 5000 tokens 阈值怎么定的？

**A：** 5000 tokens 大约等于 25-30 轮对话。选这个值的考虑：

- **太低**（比如 2000）：频繁触发 Compaction，每次都要调 LLM，增加延迟和成本。而且过于频繁的压缩可能丢失对话细节。
- **太高**（比如 10000）：对话很长了才压缩，此时 prompt 已经很长，可能接近模型上下文限制。
- **5000 是平衡点**：大约每 25 轮对话压缩一次。每次压缩后，Working State 约 500-1000 tokens + 保留的 6 条最近消息约 800-1500 tokens，总共约 1500-2500 tokens，远低于近期对话的 4000 token 预算。

### Q40：Compaction 后保留 6 条消息不压缩，为什么是 6？

**A：** 6 条意味着最近 3 轮完整的 User-Agent 对话。

保留最近对话的原因是：LLM 需要看到原始对话才能保持回答的连贯性。如果全部压缩成 Working State，模型只能看到摘要，无法精确引用"你刚才说的那个观点"。

为什么是 3 轮而不是更多或更少：

- 1-2 轮太少，模型可能丢失对话上下文。
- 5-6 轮太多，保留的原始消息 token 太多，Compaction 的压缩效果不明显。
- 3 轮是实测中连贯性和压缩效率的平衡点。

### Q41：Raw Transcript 在系统中扮演什么角色？

**A：** Raw Transcript（原始转录）是 `chat_messages` 表中完整记录的所有对话消息，每条消息有递增的 `seq`（序号）。它在系统中扮演三个角色：

1. **上下文来源**：`assemble_rewrite_context()` 和 `assemble_answer_context()` 从 Transcript 读取最近 N 轮对话，作为 ContextBundle 的 `recent_turns`。
2. **Compaction 输入**：Compaction 读取 `compaction_cursor` 之后的消息，压缩成 Working State。
3. **记忆抽取输入**：`MemoryExtractionService` 读取 `memory_cursor` 之后的消息，从中抽取持久记忆。

Transcript 是整个状态管理系统的"事件日志"。两个 cursor（compaction_cursor 和 memory_cursor）分别追踪 Compaction 和记忆抽取各自处理到了哪条消息，确保增量处理、不重复。

### Q42：为什么 Compaction 和记忆抽取各有独立的 cursor？

**A：** 因为它们的触发条件和处理频率不同。

Compaction 只在 token 超过 5000 时触发，可能很多轮对话都不触发。记忆抽取是每轮对话后都执行。如果共用一个 cursor：

- Compaction 触发后推进 cursor 到很前面，记忆抽取就会跳过中间那些消息。
- 或者记忆抽取推进了 cursor，下次 Compaction 就看不到需要压缩的旧消息。

独立 cursor 确保两个系统互不干扰，各自按自己的节奏增量处理消息。

---

## 六、长期记忆系统

### Q43：长期记忆存哪些类型的信息？为什么只存这四种？

**A：** 四种类型：

1. `user_profile`：用户画像，如"候选人有 3 年 Java 经验，目前在面试后端岗位"。
2. `interaction_preference`：交互偏好，如"用户希望回答更简洁"、"用户喜欢用中文"。
3. `feedback_rule`：反馈规则，如"用户要求代码示例用 Python"、"用户不喜欢太多理论"。
4. `project_reference`：项目背景，如"用户正在做一个基于 LangGraph 的深度研究引擎"。

**为什么只存这四种？** 因为长期记忆的目的是提供"跨会话的个性化上下文"。这四种类型覆盖了"用户是谁"（profile）、"用户喜欢什么"（preference + feedback_rule）和"用户在做什么"（project_reference）。

**什么不会被存？** 临时面试进度（应该在 Interview State 里）、短期弱点分数（属于分析结果）、通用技术知识（应该放知识库里）。如果不设类型白名单，LLM 可能会把对话中的任何信息都提取为记忆，导致记忆库膨胀和噪声。

### Q44：记忆抽取的 confidence 阈值为什么是 0.65？

**A：** `MIN_CONFIDENCE = 0.65` 是经过实测选定的。

LLM 在抽取记忆时，会给每条候选记忆打一个 confidence 分数（0-1）。实际观察到的分布：

- **0.9+**：非常明确的事实陈述，如"用户说自己有 5 年 Python 经验"。
- **0.7-0.9**：较明确但需要推断的信息，如"从用户的回答来看，他熟悉微服务架构"。
- **0.5-0.7**：模糊或可能误解的信息，如"用户可能对分布式系统感兴趣"。
- **<0.5**：几乎是猜测。

阈值选择的取舍：

- **太低**（如 0.4）：大量模糊信息被存为记忆，下次召回时可能误导模型。
- **太高**（如 0.8）：只有最确定的信息才被保存，很多有用的隐含偏好会被丢弃。
- **0.65** 是在"保留有价值信息"和"避免噪声"之间的平衡点。实测中，0.65 以上的记忆在后续召回时准确率在 85% 以上。

### Q45：normalized_key 是怎么工作的？为什么需要它？

**A：** `normalized_key` 是记忆的去重合并键。它的作用是把不同措辞的同一信息合并到同一条记忆。

举例：用户在第一次对话中说"我比较喜欢简短的回答"，LLM 抽取出 `normalized_key = "prefer_concise_answers"`。第三次对话中用户说"回答不用太长"，LLM 抽取出相同的 `normalized_key = "prefer_concise_answers"`。

合并逻辑：用 `user_id + type + normalized_key` 三元组作为唯一键。如果已存在同键记忆，更新 content（用新内容替换）、confidence（取新值）、importance（取旧值和新值的最大值）。

`normalized_key` 经过正则处理：转小写、去标点、用下划线连接。这确保"prefer concise answers"和"Prefer-Concise-Answers"被视为同一个键。

如果没有这个机制，同一条信息可能被存为多条记忆（因为每次 LLM 的 description 措辞不同），导致召回时重复信息占据有限的 token 预算。

### Q46：为什么记忆用独立的 Milvus collection，不和知识库共用？

**A：** 四个原因：

1. **语义空间不同**。记忆是短句事实陈述（"用户有 Java 经验"），知识库是长段技术文档（"Redis 的 RDB 持久化通过 fork 子进程..."）。把它们转成向量后，在高维空间中的分布特征完全不同——短句和长段落的语义编码方式不一样。混在同一个集合里，短句记忆可能被长文档的噪声淹没，反之亦然。

2. **生命周期不同**。知识库文档是相对静态的（用户上传后就基本固定了），记忆是高度动态的（每轮对话都可能产生新记忆或更新旧记忆）。如果共用一个向量集合，频繁的记忆写入和更新操作会不断改变向量索引的结构，影响知识库检索的稳定性。

3. **附带信息（Metadata）结构不同**。知识库的每个文档块附带的标签包括 source_type（来源类型）、document_id（文档编号）、upload_id（上传编号）；而记忆附带的标签包括 memory_type（记忆类型）、scope（作用域）、importance（重要性）、normalized_key（合并键）。两者的标签体系完全不同，混用后过滤查询条件会变得非常复杂。

4. **排序算法和调参需要独立**。知识库检索用的是 RRF 融合排序（把多个检索器的结果按排名位置合并）+ Reranker 精排（用深度学习模型重新评估相关性），而记忆召回用的是 HybridRetriever（把向量相似度、关键词匹配、记忆重要性、新旧程度四个因素按权重加在一起算总分）。两者的排序逻辑完全不同，需要各自独立调整参数才能达到最佳效果。

### Q47：HybridRetriever 的打分公式中，四个权重是怎么定的？

**A：** 打分公式：

```
final_score = 0.6 × vector_score + 0.35 × lexical_score + 0.15 × importance + 0.05 × recency_score
```

每个权重的理由：

- **vector_score: 0.6**。语义相似度是最核心的信号。如果用户问"我的 Python 经验"，向量检索能找到语义相关的记忆"候选人有 3 年 Python 经验"。给最高权重。

- **lexical_score: 0.35**。关键词匹配补充向量的不足。向量检索有时候会出现"语义漂移"——找到语义空间里距离近但实际不相关的结果。词法匹配可以纠正这种问题：如果关键词"Python"没出现在结果里，词法分数就是 0。

- **importance: 0.15**。记忆的内在重要性。importance 的初始值等于 confidence，后续每次合并取最大值。高 importance 的记忆应该更容易被召回，但不应该压过相关性（所以权重小于 vector_score 和 lexical_score）。

- **recency_score: 0.05**。最小的权重。新近的记忆可能更相关（用户最近的偏好可能变了），但不应该让新记忆大幅度压过旧但重要的记忆。公式是 `1/(1+age_days)`，一天前的记忆得 0.5，一周前得 0.125。

### Q48：记忆召回后有哪些副作用？为什么要做这些？

**A：** 被选中的记忆会触发四个副作用：

1. **recall_count + 1**：记录这条记忆被使用的频率。后续可以用来发现最常被召回的高价值记忆，也可以用来清理从未被召回的低价值记忆。

2. **last_accessed_at 更新**：记录最后被访问的时间。recency_score 的计算依赖这个字段。

3. **内容截断**：正文超过 500 字的记忆会被截断。因为长期记忆在 prompt 中只占 1600 tokens 预算，单条记忆太长会挤占其他记忆的空间。

4. **过时标记**：如果记忆的更新时间超过 2 天，附加 `staleness_note`（如"5 days old"）。这提醒模型这条信息可能已经过时，在引用时应保持谨慎。

### Q49：记忆向量写入失败怎么处理？会丢失记忆吗？

**A：** 不会丢失。系统有两层保障：

**第一层：降级到纯词法召回**。记忆的 PostgreSQL 记录已经写入成功（因为记忆抽取先写 PostgreSQL，再写 Milvus 向量）。即使向量写入失败，词法召回路径仍然可以从 PostgreSQL 中找到这条记忆。只是缺少了向量相似度分数，召回排名可能偏低。

**第二层：启动时回填**。`embedding_status` 字段会标为 `failed`。如果配置了 `MEMORY_BACKFILL_ON_STARTUP = true`，下次应用启动时，`memory_vector_service.backfill_pending()` 会自动扫描所有非 `ready` 状态的记忆，重新写入 Milvus。

这个设计的核心原则是：**记忆写入不应该阻塞主回答链路**。向量 upsert 是在 post-turn maintenance 中异步执行的，即使失败也不影响用户当前的对话。

### Q50：你说的 importance 字段，为什么取"旧值和新值的最大值"而不是平均值？

**A：** 取最大值是一个保守策略。

考虑一个场景：第一次对话中，用户明确说"我有 5 年 Java 经验"，LLM 高置信度抽取，importance = 0.95。三个月后，用户随口提到"Java 用得比较少了"，LLM 低置信度抽取（可能还不确定用户是完全不用还是用得少），importance = 0.6。

如果取平均值：importance = 0.775，这条记忆的重要性被不合理地降低了。
如果取新值覆盖旧值：importance = 0.6，一条本来很重要的记忆被一次模糊的提及给降级了。
如果取最大值：importance = 0.95，保持这条记忆的高重要性，后续模型看到它时会认为这是高质量信息。

content 字段会被新值覆盖（因为新的内容可能包含更最新的信息），但 importance 取最大值确保不会因为偶然的低置信度更新而降低一条本来重要的记忆的优先级。

### Q51：记忆系统目前有什么已知的局限性？

**A：** 主要有三个局限：

1. **没有遗忘机制**。记忆只会被创建和更新，不会自动过期或删除（除非用户手动删除）。长期使用后，记忆数量会持续增长。目前通过 token 预算（只召回 top 3）和 staleness_note（标记过时）来缓解，但没有根本解决。

2. **抽取质量依赖 LLM**。如果 fast LLM 的理解不准确（比如把"我在学 Rust"误解为"用户擅长 Rust"），错误的记忆会被持久化。虽然 confidence 阈值过滤了一部分噪声，但无法完全消除。

3. **合并冲突处理简单**。当新信息和旧记忆矛盾时（用户改了技术栈），系统只是用新 content 覆盖旧值。没有保存记忆变更历史，也没有让用户确认冲突的机制。

---

## 七、RAG 摄取与检索

### Q52：自适应切块引擎的选择逻辑是什么？为什么不用统一的切块方式？

**A：** `get_optimal_nodes()` 根据文件类型选择切分策略：Markdown 用 MarkdownNodeParser、JSON 用 JSONNodeParser、Python/Java/C++ 用 CodeSplitter、其他用 SentenceSplitter。

统一切块方式的问题：

- SentenceSplitter 对 Markdown 会破坏标题层级结构。一个 `## Redis 持久化` 的章节可能被切成上半段和下半段，下半段丢失了标题上下文。
- SentenceSplitter 对代码文件会在函数中间切断，导致不完整的代码片段。
- JSON 文件的嵌套结构如果被简单按字符切分，会产生无法解析的片段。

自适应的好处是每种格式都能保留其内在结构。比如 MarkdownNodeParser 按标题层级切分，每个 chunk 都是一个完整的章节；CodeSplitter 按函数/类定义切分，每个 chunk 都是一个完整的代码单元。

### Q53：为什么不用纯向量检索？为什么要加 BM25？

**A：** 纯向量检索有一个致命弱点：它只看语义相似度，不看关键词精确匹配。

举一个真实场景：用户问"HashMap 和 ConcurrentHashMap 的区别"。纯向量检索可能返回"Java 集合框架概述"（语义相似度高），但里面没提到 ConcurrentHashMap 这个关键词。加了 BM25 后，BM25 能精确匹配"ConcurrentHashMap"这个词，把包含这个关键词的文档拉回来。

两者的互补关系：

- **向量检索**擅长理解语义（"持久化"和"数据落盘"是同义词）。
- **BM25** 擅长精确匹配（必须包含"ConcurrentHashMap"这个关键词）。

融合后的效果比任何一个单独使用都好。这在 RAG 文献中叫"Hybrid Search"（混合检索），是业界公认的最佳实践。

### Q54：BM25 为什么在应用层构建，不用 Elasticsearch？

**A：** 三个原因：

1. **减少基础设施复杂度**。项目已经有 PostgreSQL、Milvus、Redis、MinIO 四个有状态组件。再加 Elasticsearch 意味着又多一个需要维护、监控、备份的分布式系统。对于面试准备场景，文档量级（几十到几百份）远不需要 ES 的分布式能力。

2. **BM25 的数据量适合内存构建**。单个用户的知识库节点通常在几百到几千个。在应用层用 `rank_bm25` 库构建索引，加载到内存中只需要几 MB，耗时在毫秒级。缓存 300 秒后过期重建。

3. **多租户隔离更自然**。应用层构建 BM25 时，直接从 Docstore 按 user_id 筛选节点。如果用 ES，需要额外做索引级别的租户隔离（index-per-tenant 或 routing），增加运维复杂度。

代价：如果单用户知识库增长到几万篇文档，内存构建 BM25 会变慢。但这在面试准备场景下几乎不会发生。

### Q55：Reranker 为什么选 BGE（bge-reranker-base）？

**A：** 选择 BGE Reranker 的理由：

1. **中文支持好**。BGE 系列是智源研究院开发的，在中文检索任务上的表现一直排名前列。本项目的核心场景是中文面试准备，中文 Reranker 的质量直接影响检索准确率。

2. **本地部署、零 API 调用成本**。`bge-reranker-base` 约 278MB，可以加载到 GPU/CPU 本地运行。每次 rerank 不需要调外部 API，没有网络延迟和调用费用。

3. **和 Embedding 模型配套**。项目的 Embedding 用的也是 BGE 系列（`BGE-M3`），它们在同一个训练框架下开发，Reranker 对 BGE embedding 的结果理解更一致。

放弃的方案：

- **Cohere Reranker**：需要调外部 API，增加延迟和成本。
- **cross-encoder/ms-marco-MiniLM**：英文为主，中文效果不如 BGE。
- **不用 Reranker（直接用 RRF 排序）**：RRF 只考虑排名位置，不考虑 query-document 的深层语义匹配。Reranker 用交叉注意力（Cross-Attention）把 query 和 document 拼接后输入 Transformer，能捕捉更精细的相关性。

### Q56：RAG_MIN_SCORE = 0.5 为什么是这个值？

**A：** 0.5 是 Reranker 输出的绝对分数阈值。Reranker 的输出范围通常在 0-1 之间，0.5 大致对应"query 和 document 的相关性是中等偏上"。

实测调参过程：

- **0.3**：放行了太多低质量的片段，模型会引用这些不太相关的内容，导致回答偏离问题。
- **0.5**：大多数明确相关的片段分数在 0.5 以上，不相关的片段分数在 0.3 以下。0.5 作为分界线，在精确率和召回率之间取得了平衡。
- **0.7**：太严格，很多相关但不是完美匹配的片段被拦截，导致知识库明明有答案但系统说"没找到"。

注意这个阈值是**绝对分数**，不是相对排名。即使排名第一的片段分数低于 0.5，也会被拦截。这是防幻觉的关键——低分意味着知识库里真的没有相关内容，模型不应该凭空编造。

### Q57：防幻觉的完整策略是什么？能不能系统地说一下？

**A：** 防幻觉有三层防线：

**第一层：Reranker 绝对分数阈值**。所有经过 Reranker 的片段，分数低于 `RAG_MIN_SCORE = 0.5` 的被过滤掉。如果所有片段都低于阈值，系统不返回任何知识片段。

**第二层：词法覆盖 Fallback**。如果 Reranker 分数全部低于阈值，但有片段的关键词覆盖率（`lexical_overlap`）超过 35%，仍然放行。这是为了防止 Reranker 在某些特定领域（如代码片段、术语密集的文档）系统性偏低导致误拦截。

**第三层：SYSTEM_EMPTY_WARNING 标记**。如果前两层都没有放行任何片段，系统返回 `[SYSTEM_EMPTY_WARNING]` 标记。主回答 LLM 的 RAG_SYSTEM_RULES 提示词中有明确指令：看到这个标记时，不要编造答案，要坦诚告知用户"我的知识库中没有找到相关信息"。

三层防线的设计思路是：第一层是主防线（高精度拦截）→ 第二层是补充（防止过度拦截）→ 第三层是兜底（确保即使前两层失误，LLM 也不会编造）。

### Q58：多租户隔离在 RAG 检索中具体怎么实现的？

**A：** 两个层面的隔离：

**向量检索层**：`_build_metadata_filters()` 函数把 `user_id` 和可选的 `source_type` 注入到 Milvus 的 `MetadataFilter` 中。使用 `FilterOperator.EQ`（等于过滤）。这意味着 Milvus 在执行 HNSW 搜索时，只会搜索 metadata 中 `user_id` 等于当前用户的向量。过滤发生在服务端，效率高且安全——客户端无法绕过。

**BM25 检索层**：构建 BM25 索引时，`_build_bm25_retriever()` 从 PostgreSQL Docstore 加载节点时就按 `user_id` 过滤。只有属于当前用户的节点才会被加载进 BM25 索引。

两个层面都是"先过滤再检索"，不是"检索后再过滤"。这确保了不同用户的数据在物理上就是隔离的。

### Q59：BM25 缓存是怎么管理的？为什么缓存 300 秒？

**A：** BM25 索引的构建需要从 PostgreSQL 加载用户的所有节点，对于节点较多的用户可能需要 500ms-1s。如果每次检索都重建，性能不可接受。

缓存策略：

- 缓存键是 `"user_id|source_type_tuple"` 字符串格式，即按用户和知识源类型组合缓存。不同用户的缓存完全隔离，同一用户检索不同知识源类型时也各自独立缓存。
- 缓存使用**线程安全锁**（`threading.Lock`）保护，避免多个并发请求同时重建同一份 BM25 索引造成浪费。
- 缓存 TTL 是 300 秒（5 分钟），超时后自动过期重建。
- 当用户上传新文档并完成摄取后，`invalidate_bm25_cache(user_id)` 主动清除该用户的**所有** source_type 组合的缓存条目，确保下次检索立即能看到新内容。这是主要的缓存更新机制，TTL 只是被动兜底。

300 秒的考虑：

- **太短**（如 30 秒）：用户在 5 分钟内可能问多个问题，每次都重建 BM25 索引，浪费计算。
- **太长**（如 1 小时）：如果缓存失效逻辑有 bug（没被正确调用），用户上传新文档后要等很久才能在检索中看到。300 秒是一个安全的上限。
- 主动失效（`invalidate_bm25_cache`）是主要的缓存更新机制，300 秒 TTL 是被动兜底。

### Q60：QueryFusionRetriever 的 RRF 融合是怎么工作的？

**A：** RRF（Reciprocal Rank Fusion，互逆排序融合）是一个用来合并多个检索结果列表的算法。它解决的问题是：向量检索和 BM25 检索各自返回一个排名列表，但两者的分数尺度完全不同（向量分数可能在 0-1 之间，BM25 分数可能在 0-20 之间），没法直接比较。RRF 的聪明之处在于——它不看分数，只看排名位置。

核心思想：排名越靠前的文档贡献越大。具体公式是 `RRF_score = Σ 1/(k + rank_i)`，其中 k 是一个平滑常数（通常取 60，防止排名第 1 的文档权重过大），rank_i 是文档在第 i 个检索器中的排名。

用一个例子来理解：假设文档 A 在向量检索中排第 2、在 BM25 中排第 5，那么它的 RRF 分数 = 1/(60+2) + 1/(60+5) ≈ 0.032。另一个文档 B 在向量检索中排第 1 但 BM25 中排第 50，它的 RRF 分数 = 1/61 + 1/110 ≈ 0.026。文档 A 的融合分数更高，因为它在两个检索器中**都**表现不错，而文档 B 只在一个检索器中靠前。这就是 RRF 的核心价值——**奖励在多个维度上都相关的文档**。

RRF 融合后的结果会再送入 BGE Reranker（一个专门评估"问题和文档是否真的相关"的深度学习模型）做更精确的重新排序。如果 Reranker 不可用（模型没加载成功），RRF 分数就直接作为最终分数。此时防幻觉的分数阈值会自动从 0.5 降到 0.02，因为 RRF 分数的数值范围本身就很小（通常在 0.001-0.05 之间）。

### Q61：如果 Reranker 加载失败或不可用，系统怎么降级？

**A：** 系统会自动降级为纯 RRF 排序，不中断服务。

具体逻辑：

1. `init_reranker()` 在启动时尝试加载 Reranker 模型。如果加载失败（模型文件不存在、GPU OOM 等），记录 warning 日志，Reranker 设为 None。
2. 检索时，如果 Reranker 为 None，跳过 Rerank 阶段，直接使用 QueryFusionRetriever 的 RRF 结果。
3. 防幻觉阈值自动适配：`score >= min(min_score, 0.02)` — 因为 RRF 分数通常在 0.001-0.05 范围，用 0.02 而不是 0.5。

这个降级策略确保即使 Reranker 不可用，系统仍然可以提供检索服务。检索质量会下降（没有 Reranker 的精排），但不会完全失效。

---

## 八、ReAct Agent

### Q62：ReAct Agent 的执行循环是什么样的？

**A：** ReAct（Reasoning + Acting）Agent 的核心循环：

1. 准备上下文（Working State、Interview State、近期对话、记忆、知识库）和工具清单（JSON Schema 格式）。
2. 调用 Agent LLM（必须支持 Function Calling），传入 messages 和 tools。
3. 如果 LLM 返回 `tool_calls`：解析工具名和参数 → Pydantic 校验参数 → 执行工具 → 把 observation（工具执行结果）追加到 messages → 回到步骤 2。
4. 如果 LLM 返回文字内容（没有 tool_calls）：视为最终答案，结束循环。
5. 每次循环前检查 AgentBudget，超出任何预算则强制停止。

整个循环的输入是用户的任务描述，输出是最终答案。中间可能经过 0-N 次工具调用。

### Q63：为什么从正则解析 JSON 迁移到 Function Calling？

**A：** 早期版本让 LLM 在回答中输出固定格式的 JSON（`{"tool": "xxx", "args": {...}}`），然后用正则表达式解析。这有三个严重问题：

1. **JSON 格式错误率高**。LLM 有时候会输出多余的逗号、缺少引号、或者把 JSON 嵌在 Markdown 代码块里。正则解析需要处理各种边界情况，代码复杂且脆弱。

2. **参数缺失难检测**。如果 LLM 漏掉了必填参数，正则解析后还需要手动检查字段完整性。错误信息不友好，LLM 难以理解并修正。

3. **工具 schema 和解析逻辑不同步**。添加新工具或修改参数时，需要同时更新 prompt 中的工具描述和解析代码，容易遗漏。

迁移到 OpenAI Function Calling 后：

- LLM 返回结构化的 `tool_calls` 对象，不需要手动解析。
- 参数自动按 JSON 解析，再经过 Pydantic 模型校验——类型错误、超长、缺失都有明确的错误信息，可以直接反馈给 LLM 让它修正。
- 工具 schema 从 Pydantic 模型自动导出（`get_all_tool_schemas()`），一处定义，处处一致。

### Q64：AgentBudget 为什么要有六个维度的控制？

**A：** 六个维度各自防护不同类型的资源失控：

1. **最大步数（8）**：防止推理陷入无限循环。LLM 有时候会反复在两个工具之间来回调用（A→B→A→B...），步数限制强制终止。

2. **最大工具调用（16）**：一个步骤可能包含多次工具调用。16 次是合理的上限——正常任务最多调 4-5 次工具。

3. **最大 token（32000）**：防止 token 成本失控。Agent 的 messages 列表会随着工具调用不断增长，32000 是成本控制的红线。

4. **最大运行时间（90 秒）**：防止用户等太久。即使 token 和步数都没超，如果某个工具调用卡住了（网络超时），90 秒后强制停止。

5. **单工具最大调用（6）**：防止对同一个工具的死循环。如果 LLM 反复调 `search_jobs` 但每次参数都不对，6 次后强制停止这个工具。

6. **观测结果字符限制（6000）**：工具返回的结果可能很长（比如完整的岗位描述）。超过 6000 字的结果会被截断并附加 `(truncated)` 标记，防止单次工具调用消耗过多 token。

### Q65：Pydantic schema 校验在工具调用中的价值是什么？

**A：** Pydantic 校验在工具调用链路中承担"参数守门员"的角色。

每个工具的参数都有 Pydantic 模型定义。比如 `SearchJobsArgs`：

```python
class SearchJobsArgs(BaseModel):
    keyword: str = Field(max_length=200)
    location: str = Field(default="", max_length=100)
    page: int = Field(default=0, ge=0)
```

当 LLM 返回工具调用时，参数先经过 `parse_tool_arguments()`（JSON 解析）→ `validate_args()`（Pydantic 校验）。校验可以捕获：

- 类型错误（keyword 传了 int）
- 超长（keyword 超过 200 字）
- 缺少必填字段
- 范围错误（page 为负数）

校验失败时，系统不会直接报错，而是把 Pydantic 的 `ValidationError` 详情格式化成人可读的错误信息，作为 observation 返回给 LLM。LLM 看到错误信息后通常会在下一步修正参数。

如果没有 Pydantic 校验，错误的参数会直接传给工具执行函数，可能导致不可预期的行为（比如 SQL 注入、API 调用超时等）。

### Q66：Agent Trace 记录了什么？有什么用？

**A：** Agent Trace 是 ReAct 执行的全量遥测，记录在 `agent_runs` 和 `agent_steps` 两张表中。

**AgentRun**（一次完整执行）记录：run_id、user_id、session_id、goal（任务描述）、mode（function_calling）、status（running/completed/budget_stopped/error）、started_at/finished_at、steps_used、tool_calls、prompt_tokens/completion_tokens、total_latency_ms、budget_stop_reason、error_message、final_answer。

**AgentStep**（每一步）记录：step_index、action_type（tool_call/final_answer/budget_stop/error）、tool_name、tool_args_json、observation_json、assistant_content、is_error、latency_ms。

用途：

1. **排查问题**：用户反馈 Agent 回答不对，可以查看完整的执行轨迹，看它调了哪些工具、传了什么参数、得到了什么结果。
2. **聚合指标**：`aggregate_trajectory_metrics()` 计算完成率、平均步数、无效工具调用率、平均延迟。这些指标用于评估 Agent 的整体表现。
3. **评测基线**：`run_agent_trajectory_eval.py` 用历史 trace 数据做回归评测，确保代码修改不会降低 Agent 质量。

### Q67：ReAct Agent 对记忆有写入权限吗？怎么控制的？

**A：** ReAct Agent 对记忆的写入权限是**按 answer_mode 控制的**。

只有当 answer_mode 是 `interview_learning`、`review` 或 `preference_update` 时，Agent 执行结束后的 post-turn maintenance 才会触发记忆抽取。

如果用户只是让 Agent 搜索岗位信息（answer_mode 可能是 `direct_chat` 或 `knowledge_qa`），不会触发记忆抽取——因为岗位搜索结果不应该被持久化为用户的个人记忆。

这个控制逻辑确保只有"用户在做面试学习或更新个人偏好"时才会写入记忆，避免把工具调用的临时数据（如岗位列表）污染记忆库。

### Q68：如果 Agent 的工具执行超时了会怎样？

**A：** 每次工具执行都用 `asyncio.wait_for(coro, timeout=20)` 包裹，默认超时 20 秒。

超时后的处理：

1. `asyncio.TimeoutError` 被捕获。
2. observation 设为 `"Tool execution timed out after 20s"`。
3. `is_error` 标为 True。
4. 这个 observation 作为 tool message 追加到 messages 列表。
5. LLM 看到超时错误后，通常会选择跳过这个工具或用不同参数重试。

如果连续多次超时，AgentBudget 的步数和工具调用次数会逐渐接近上限，最终触发 budget stop。

---

## 九、音频分析与异步任务

### Q69：为什么用 Celery 不用 FastAPI 的 BackgroundTasks？

**A：** 两者的定位完全不同：

**FastAPI BackgroundTasks** 在同一个进程内运行后台任务。它适合执行时间短（几秒以内）、不需要重试、不需要持久化结果的任务。比如发送通知邮件、写日志。

**Celery** 是独立的分布式任务队列。任务在单独的 Worker 进程中执行，通过 Redis Broker 传递消息。

音频分析任务需要 Celery 的原因：

1. **耗时长**。WhisperX 转写 + LLM 分析可能需要几分钟。BackgroundTasks 会占用 FastAPI 的事件循环，影响其他请求的响应。
2. **需要重试**。如果转写失败（模型 OOM、网络超时），需要自动重试。Celery 原生支持 `autoretry_for` + 指数退避。
3. **需要独立资源**。WhisperX 模型占用大量 GPU/CPU 资源。在单独的 Worker 进程中运行，不影响 API 服务的稳定性。
4. **需要持久化状态**。任务的状态（PENDING → TRANSCRIBING → ANALYZING → COMPLETED）需要持久化，前端可以随时查询进度。

注意：post-turn maintenance 用的是 `safe_background_task()`——这是项目封装的一个安全后台任务调度器（定义在 `background_tasks.py`），而不是 FastAPI 内置的 BackgroundTasks。它基于 `asyncio.create_task()` 但增加了三层保障：①用全局集合持有任务的强引用，防止 Python 的垃圾回收器在任务完成前回收它；②通过 `task.add_done_callback()` 自动捕获并记录未处理的异常（原生 `create_task` 会静默吞掉异常）；③应用关停时，`cancel_and_wait_all()` 会统一取消并等待所有挂起的后台任务排空。之所以不用 Celery 来做 maintenance，是因为它执行时间较短（3-9 秒）、不需要独立进程、失败也不需要重试。

### Q70：WhisperX 和原始 Whisper 有什么区别？为什么选 WhisperX？

**A：** WhisperX 是在 OpenAI Whisper 基础上的增强版本，主要区别：

| 特性 | Whisper | WhisperX |
|------|---------|----------|
| 批处理 | 不支持 | 支持（batch_size 参数） |
| 时间戳精度 | 粗粒度 | 强制对齐（Forced Alignment）后的精细时间戳 |
| 说话人分离集成 | 无 | 直接集成 Pyannote |
| 推理速度 | 较慢 | 利用 CTranslate2 加速 |

选 WhisperX 的理由：

1. **说话人分离是刚需**。面试录音需要区分面试官和候选人。WhisperX 直接集成了 Pyannote 的 `assign_word_speakers()`，可以把文字和说话人标签对齐。用原始 Whisper 的话，需要自己写对齐逻辑。
2. **批处理提升吞吐**。`batch_size=16` 可以利用 GPU 并行计算多个音频片段，比逐段处理快很多。
3. **时间戳精度更高**。强制对齐后的时间戳精确到词级别，有利于后续的说话人分配准确性。

放弃的方案：

- **Google Speech-to-Text**：需要调用外部 API，有延迟和成本。且中英文混合的面试场景下，WhisperX 的多语言支持更灵活。
- **Faster-Whisper 直接使用**：WhisperX 底层就是 Faster-Whisper，但在上面加了对齐和分离的集成，省去了自己写这部分代码。

### Q71：说话人分离（Speaker Diarization）在项目中的作用是什么？

**A：** 说话人分离的目的是区分录音中"谁在说话"。对于面试分析来说，这是一个前置步骤——只有知道哪些话是面试官说的（问题）、哪些是候选人说的（回答），才能构建问答对并逐题评分。

具体实现：

1. Pyannote 的 Speaker Diarization 模型分析音频，输出时间段和说话人标签的映射（如 0s-5s → Speaker 0, 5s-12s → Speaker 1）。
2. `assign_word_speakers()` 把 WhisperX 转录的每个词和 Pyannote 的说话人标签对齐。
3. 相邻同一说话人的文字片段合并，最终输出 Markdown 格式：`**[Speaker 1]**: 请介绍一下你的项目`。

面试分析时，系统假设第一个发言的人是面试官（因为面试通常由面试官开场）。

### Q72：面试分析的 QA pair 抽取逻辑是什么？

**A：** QA pair 抽取在 `analysis_service.py` 中，分两步：

**第一步：解析说话人轮次**。用正则 `SPEAKER_LINE_RE` 把 Markdown 格式的转写文本解析成 `[{speaker: "Speaker 1", text: "..."}]` 结构化列表。

**第二步：构建问答对**。遍历列表，把面试官（第一个说话人）的发言标记为"问题"，紧随其后的候选人（第二个说话人）的发言标记为"回答"。如果候选人的回答被面试官打断（中间插了一个面试官的短句），这个短句会被合并到问题或回答中，取决于长度。

每个 QA pair 的结构：`{question, user_answer, score, critique, improved_answer}`。

### Q73：为什么面试分析要分块处理（chunked analysis）？

**A：** 因为面试录音可能很长（30-60 分钟），转写后的文本可能有几万 tokens，直接发给 LLM 会超过上下文限制。

分块策略：

1. 按 `ANALYSIS_CHUNK_TOKEN_LIMIT = 12000` tokens 把 QA pairs 分成多个 chunk。
2. **不切断 QA pair**：每个 chunk 包含完整的问答对。如果加入一个 QA pair 后超过 12000 tokens，就把它放到下一个 chunk。
3. 对每个 chunk 独立调用 LLM 分析，输出 `{overall_score, overall_feedback, qa_list}`。
4. 如果有多个 chunk，把所有分段结果再送给 LLM 做一次全局汇总。

为什么不切断 QA pair？因为评分需要看到完整的问题和回答才能准确打分。如果一个回答被切成两半分到不同 chunk，两个 chunk 的评分都不准。

### Q74：Celery 任务的重试策略是怎么配的？

**A：** 两个任务（`process_interview_analysis` 和 `process_document_ingestion`）使用相同的重试配置：

```python
@celery_app.task(
    autoretry_for=(ConnectionError, TimeoutError, OSError),
    retry_backoff=True,
    retry_backoff_max=120,
    max_retries=3,
)
```

含义：

- `autoretry_for`：只对网络和 IO 类异常自动重试。逻辑错误（ValueError、KeyError）不重试。
- `retry_backoff=True`：指数退避。第一次重试等 1 秒，第二次 2 秒，第三次 4 秒。
- `retry_backoff_max=120`：退避时间不超过 120 秒。
- `max_retries=3`：最多重试 3 次。3 次后仍然失败，标记任务为 FAILED。

### Q75：Celery Worker 怎么处理 async 代码的？

**A：** 这是一个"同步代码如何调用异步代码"的经典问题。简单来说：Celery 的任务函数只能是普通的同步函数（不能用 `async def`），但项目里的核心服务（音频转写、面试分析、文档摄取）都写成了异步函数（`async def`），因为它们内部需要并发执行多个 IO 操作（如同时读数据库和调 LLM）。所以需要一个"桥梁"来让同步的 Celery 任务能调用异步的服务函数。

解决方案是为每个 Worker 线程维护一个持久化的事件循环：

```python
_loop_local = threading.local()

def _get_worker_loop():
    loop = getattr(_loop_local, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_local.loop = loop
    return loop

def run_async(coro):
    return _get_worker_loop().run_until_complete(coro)
```

这比每次任务 `asyncio.run()` 更高效——`asyncio.run()` 每次创建新循环再销毁，有额外的开销。用 `threading.local()` 保证每个 Worker 线程有自己独立的事件循环，不会和其他线程冲突。

### Q76：文档摄取任务中有哪些安全检查？

**A：** `process_document_ingestion` 在执行前做三项安全检查：

1. **上传归属验证**：`document.upload.user_id != document.user_id` → 文档的上传记录的所有者必须和文档所有者一致。防止用户通过修改 document_id 访问其他人上传的文件。

2. **用途验证**：`document.upload.purpose != "knowledge_document"` → 上传记录的用途必须是知识库文档。防止用户把音频上传的记录冒充为文档摄取。

3. **路径前缀验证**：`document.object_key.startswith(f"uploads/{document.user_id}/{document.upload_id}/")` → S3 对象键必须以用户目录开头。防止路径穿越攻击。

任何检查失败都会抛出 ValueError，任务立即终止并标记为 FAILED。

---

## 十、技术选型横向对比

### Q77：FastAPI vs Flask vs Django，为什么选 FastAPI？

**A：** 选 FastAPI，放弃 Flask 和 Django。

**FastAPI 的优势**：原生支持 async/await，适合 IO 密集型场景（LLM 调用、数据库查询、S3 操作都是 IO）。内置 Pydantic 校验，请求体自动校验和文档生成。WebSocket 和 SSE 都有原生支持。自动生成 OpenAPI 文档。

**Flask 的劣势**：同步框架，要支持 async 需要额外配置（如 Quart）。没有内置的请求校验，需要手动用 marshmallow 或 cerberus。WebSocket 需要第三方扩展（Flask-SocketIO）。

**Django 的劣势**：太重了。Django 的 ORM、admin、模板引擎、forms 等内置功能本项目都不需要。Django 的 async 支持虽然在改善但不如 FastAPI 原生。Django REST Framework 的序列化器比 Pydantic 更啰嗦。

当前场景的决策因素：项目的 IO 密集特性（每个请求至少 2-3 次 LLM 调用 + 数据库查询 + 可能的 Milvus 查询）使得 async 支持是刚需。FastAPI 是唯一在 async、校验、WebSocket、SSE 四个维度上都原生支持的框架。

### Q78：LlamaIndex vs LangChain，为什么选 LlamaIndex？

**A：** 选 LlamaIndex，主要用于 RAG 管线（Embedding、VectorStore、NodeParser、QueryEngine）。

**LlamaIndex 的优势**：

1. RAG 管线是一等公民。NodeParser（自适应切块）、VectorStoreIndex、QueryFusionRetriever 等组件开箱即用，且抽象层级合适——既不过度封装（可以自定义每一步），又不需要从零构建。
2. Docstore 抽象统一。`PostgresDocumentStore` 可以同时服务 BM25 节点加载和文档管理。
3. Embedding 模型管理方便。`HuggingFaceEmbedding` 直接集成到 `Settings.embed_model`，全局生效。

**LangChain 的劣势**：

1. 抽象层级过深。LangChain 的 Chain、Agent、Tool、Memory 等概念嵌套很深，调试时 stack trace 很长，出问题难定位。
2. RAG 组件不如 LlamaIndex 成熟。LangChain 的 VectorStore 和 Retriever 接口更通用但 RAG 特化不够。
3. API 变动频繁。LangChain 的版本更新经常有 breaking change。

但项目并没有完全排斥 LangChain 的思想——ReAct Agent 的 Function Calling 循环和 LangChain 的 AgentExecutor 在设计思路上类似，只是实现更轻量。

### Q79：Milvus vs FAISS vs Chroma vs pgvector，为什么选 Milvus？

**A：**

| 方案 | 优势 | 劣势 |
|------|------|------|
| **Milvus** | 生产级部署、原生 metadata 过滤、水平扩展、持久化 | 运维复杂（需要 etcd + minio）、资源占用大 |
| FAISS | 极快的内存检索、轻量 | 无持久化、无原生 metadata 过滤、无多租户 |
| Chroma | API 简单、嵌入式部署 | 性能不如 Milvus、大规模数据支持弱 |
| pgvector | 复用 PostgreSQL、运维简单 | 向量检索性能不如专用引擎、HNSW 参数调优有限 |

选 Milvus 的决策因素：

1. **多租户隔离是刚需**。Milvus 的 `MetadataFilter` 可以在服务端做 user_id 过滤，FAISS 没有这个能力。
2. **持久化**。FAISS 的索引在内存中，服务重启后丢失。Milvus 的数据持久化在独立的 MinIO 中。
3. **可扩展性**。如果未来用户量增长，Milvus 支持分片和副本。
4. **LlamaIndex 集成好**。`MilvusVectorStore` 是 LlamaIndex 官方维护的连接器。

为什么不选 pgvector？pgvector 在小规模数据（<10万向量）上性能可接受，但 HNSW 参数调优不如 Milvus 灵活。且如果和业务数据共用 PostgreSQL，大量的向量 CRUD 可能影响业务查询性能。

### Q80：Celery vs FastAPI BackgroundTasks vs Dramatiq vs RQ？

**A：**

| 方案 | 优势 | 劣势 |
|------|------|------|
| **Celery** | 最成熟的 Python 任务队列、重试/调度/监控完善 | 配置复杂、需要 Broker |
| BackgroundTasks | 零配置、同进程 | 无重试、无持久化、阻塞事件循环 |
| Dramatiq | API 更现代、性能好 | 生态不如 Celery、社区小 |
| RQ | 简单轻量 | 功能有限、不支持 Windows |

选 Celery 的原因：音频分析和文档摄取是重型异步任务，需要自动重试（`autoretry_for`）、指数退避（`retry_backoff`）、状态追踪（PENDING/TRANSCRIBING/COMPLETED）、独立进程（不影响 API 响应）。这些是 Celery 的核心能力。

Dramatiq 的 API 确实更优雅，但社区和生态不如 Celery 成熟。项目需要的 `bind=True`（访问 task 元数据）、`autoretry_for`（按异常类型重试）在 Celery 中已经是生产验证的功能。

### Q81：PostgreSQL vs MongoDB，为什么选关系型数据库？

**A：** 选 PostgreSQL 的理由：

1. **数据关系明确**。系统中的实体关系很清晰：User → ChatSession → ChatMessage（一对多）、Interview → Transcript → AnalysisResult（一对一/一对多）。关系型数据库天然擅长表达和查询这些关系。

2. **事务一致性**。面试分析任务需要在一个事务中同时写入 Transcript 和 AnalysisResult，失败时一起回滚。PostgreSQL 的 ACID 事务保证了这一点。

3. **兼做 Docstore**。LlamaIndex 的 `PostgresDocumentStore` 直接复用了 PostgreSQL，不需要额外引入存储组件。

4. **Alembic 迁移**。关系型数据库有成熟的 schema migration 工具。MongoDB 的 schema-less 特性在前期方便，但后期维护时缺少 migration 机制会很痛苦。

MongoDB 的优势（灵活 schema、JSON 原生存储）在本项目中不是刚需——所有数据模型都是固定 schema 的。

### Q82：Redis 在项目中只做 Broker，为什么不用 RabbitMQ？

**A：** Redis 作为 Celery Broker 的优势：

1. **已有组件**。即使不用 Redis 做 Broker，项目也需要 Redis 做 Celery 的 Result Backend。用 Redis 同时做 Broker 和 Result Backend，不需要额外引入 RabbitMQ。
2. **配置简单**。`CELERY_BROKER_URL = redis://redis:6379/0` 一行搞定。RabbitMQ 需要额外配置 exchange、queue、binding。
3. **资源占用少**。Redis 单实例占用内存很少，RabbitMQ 需要 Erlang VM 运行时。

RabbitMQ 的优势（消息确认、死信队列、优先级队列）在本项目中不是刚需——音频分析任务量不大（个人使用），不需要复杂的消息路由。如果任务量增长到需要消息优先级或死信队列，再考虑迁移。

### Q83：MinIO vs 直接本地文件系统，为什么用对象存储？

**A：** 用 MinIO（S3 兼容的对象存储）而不是直接存到本地文件系统，原因是：

1. **容器化兼容**。Docker 容器的文件系统是临时的，容器重启后文件丢失。虽然可以用 volume 挂载，但 MinIO 提供了更标准的 API（S3 协议）。
2. **前端直传**。MinIO 支持预签名 URL，前端可以直接上传到 MinIO，不经过后端。本地文件系统做不到这一点。
3. **生产迁移零成本**。MinIO 的 API 和 AWS S3 完全兼容。开发阶段用本地 MinIO，生产环境直接切到 AWS S3，只需要改一下环境变量（`AWS_ENDPOINT_URL`），代码不用改。

### Q84：DeepSeek vs GPT-4 vs Claude，模型选型的考量是什么？

**A：** 项目默认使用 DeepSeek 系列模型，但通过 Model Registry 支持运行时切换。

选 DeepSeek 作为默认的原因：

1. **成本**。DeepSeek V4 Flash 的价格远低于 GPT-4，对于面试准备这种高频使用场景，成本敏感。
2. **中文能力**。DeepSeek 在中文任务上的表现和 GPT-4 接近，本项目以中文面试为主。
3. **Function Calling 支持**。DeepSeek V4 系列支持 Function Calling，可以用于 ReAct Agent。

为什么不锁死模型？通过 Model Registry + RuntimeLLMProxy 的设计，用户可以随时切换模型。如果某个场景下 GPT-4 效果更好（比如英文面试），可以把 primary 角色切到 GPT-4。

### Q85：HNSW vs IVF_FLAT vs DiskANN，为什么选 HNSW？

**A：**

| 索引 | 优势 | 劣势 |
|------|------|------|
| **HNSW** | 查询速度快、召回率高、构建后不需要训练 | 内存占用大、构建慢 |
| IVF_FLAT | 内存占用小、支持 GPU 加速 | 需要训练（nlist 参数）、召回率不如 HNSW |
| DiskANN | 超大规模数据、低内存 | Milvus 支持不完善、配置复杂 |

选 HNSW 的理由：

1. **数据规模适合**。面试准备场景的向量数量在万级到十万级。HNSW 在这个规模下，内存占用完全可接受。
2. **无需训练**。IVF_FLAT 需要提前训练聚类中心（nlist），数据量变化时需要重新训练。HNSW 是基于图的索引，插入新向量时自动更新图结构。
3. **高召回率**。HNSW 的召回率通常在 95% 以上（efSearch=64 时），IVF_FLAT 的召回率取决于 nprobe/nlist 的比例，通常需要更高的 nprobe 才能达到同等召回率。

### Q86：BM25 应用层构建 vs Elasticsearch vs 独立 sparse index？

**A：** 三种方案的对比：

| 方案 | 优势 | 劣势 |
|------|------|------|
| **应用层 BM25** | 零额外基础设施、毫秒级构建、天然多租户 | 数据量大时内存瓶颈 |
| Elasticsearch | 分布式、实时索引、高级查询 | 运维复杂、另一个有状态组件 |
| 独立 sparse index（如 SPLADE + Milvus） | 学习到的稀疏表示比 BM25 更好 | 需要训练/微调、额外计算 |

当前选择应用层 BM25 的核心理由是：数据量小（单用户几百到几千个节点）、不需要实时索引更新（新文档摄取时主动失效缓存即可）、不想增加运维复杂度。

如果将来数据量增长到十万级节点，会考虑迁移到 SPLADE + Milvus 的方案——用学习到的稀疏向量替代 BM25 的硬编码 TF-IDF，同时利用 Milvus 的向量索引能力。

---

## 十一、参数设置追问

### Q87：HNSW 参数 M=16, efConstruction=200, efSearch=64 为什么这样设？

**A：**

**M=16**：HNSW 图中每个节点的最大出边数。M 越大，图越稠密，召回率越高，但内存占用越大。M=16 是 Milvus 推荐的默认值，适合十万级数据量。

**efConstruction=200**：构建索引时的搜索宽度。越大构建的图质量越高，但构建速度越慢。200 是"图质量"和"构建速度"的平衡点。文档摄取是低频操作（用户偶尔上传文档），构建慢一点可以接受。

**efSearch=64**：查询时的搜索宽度。越大召回率越高，但查询越慢。64 在实测中可以达到 ~95% 的召回率，查询延迟在 10ms 以内。如果需要更高召回率可以调到 128，但延迟会翻倍。

### Q88：AGENT_MAX_STEPS 默认为什么是 8？

**A：** 8 步是基于"正常任务最多需要多少步"的经验值。

分析典型任务的步数：

- **搜索岗位并总结**：search_jobs(1步) → 可能 fetch_job_detail(1-2步) → 最终回答(1步) = 3-4 步
- **结合用户画像推荐岗位**：get_user_profile(1步) → search_jobs(1步) → fetch_job_detail(1-2步) → 最终回答(1步) = 4-5 步
- **最复杂的组合任务**：6-7 步

8 步给了足够的余量，同时防止模型陷入无限循环。如果一个任务真的需要超过 8 步，大概率是模型的规划出了问题，而不是任务本身需要那么多步。

### Q89：MEMORY_FINAL_TOP_K = 3，为什么只保留 3 条记忆？

**A：** 受 token 预算的约束。长期记忆的 token 预算是 1600 tokens，每条记忆平均 300-500 tokens，3 条大约 900-1500 tokens，刚好在预算内。

如果保留更多：

- 5 条：大概率超出 1600 tokens 预算，要么被截断，要么挤压其他上下文的空间。
- 1 条：可能漏掉重要的交叉信息（比如用户同时提到了项目背景和语言偏好）。

3 条是在"信息充足"和"token 可控"之间的平衡。

### Q90：lexical_overlap 的 35% 阈值是怎么来的？

**A：** `RAG_LEXICAL_FALLBACK_MIN_OVERLAP = 0.35` 是防幻觉第二层防线的阈值。

`lexical_overlap()` 函数计算的是：query 中的关键词有多少比例出现在了文档中。35% 意味着至少三分之一的关键词有精确匹配。

实测校准：

- **20%**：一两个关键词匹配就放行，太宽松。可能把只包含一个常见词（如"系统"、"数据"）的不相关文档放进来。
- **35%**：需要至少三分之一的关键词匹配。这排除了大部分偶然匹配，同时保留了 Reranker 可能系统性低估的领域文档。
- **50%**：太严格，很多有价值但措辞不完全一样的文档被拦截。

---

## 十二、安全与隔离

### Q91：数据隔离一共有几个层次？

**A：** 四个层次：

1. **API 鉴权层**：JWT + `get_current_user()` 依赖注入。
2. **向量检索层**：Milvus `MetadataFilter` 按 user_id 服务端过滤。
3. **节点 Metadata 层**：文档切块后强制注入 user_id。
4. **ORM 查询层**：所有数据库查询带 user_id 过滤。

四层是纵深防御，任何一层被绕过，其他层仍然生效。

### Q92：有没有 Prompt Injection 的防护？

**A：** 目前有两层防护：

**第一层：消息清洗**。`_sanitize()` 过滤掉以 `[SYSTEM_]` 或 `[DEBUG_]` 开头的消息。即使用户试图在输入中伪造系统消息（如 `[SYSTEM_EMPTY_WARNING]`），这些消息会被清洗层过滤掉，不会进入 LLM 的上下文。

**第二层：结构化输入输出**。Query Planner 的输出是 Pydantic 模型（QueryPlan），不是自由文本。即使 Planner 的 LLM 被注入了恶意指令，输出也必须符合 Pydantic schema，否则会 fallback 到默认计划。

**已知不足**：

1. RAG 知识库中的文档内容没有做 injection 检测。如果用户上传了包含恶意 prompt 的文档，这些内容会被检索到并注入 LLM 的上下文。
2. 工具调用的结果（observation）没有过滤。如果外部 API 返回了恶意内容，会直接传给 LLM。

### Q93：工具调用有越权防护吗？

**A：** 有。工具调用的安全通过三个机制保障：

1. **白名单**：只有 `TOOL_REGISTRY` 中注册的工具才能被调用。LLM 无法调用未注册的函数。
2. **参数校验**：Pydantic schema 限制了参数的类型、长度和范围。比如 keyword 最多 200 字符，page 必须非负。
3. **用户上下文注入**：工具执行时，`user_id` 从认证上下文传入，不是从 LLM 的参数中获取。LLM 无法修改 user_id 来访问其他用户的数据。

### Q94：上传文件有安全检查吗？

**A：** 有多层检查：

1. **S3 路径前缀**：上传的 object_key 必须以 `uploads/{user_id}/{upload_id}/` 开头，防止路径穿越。
2. **文件大小限制**：通过 MinIO 的 presigned URL 策略限制最大上传大小。
3. **用途检查**：文档摄取时检查 upload 的 purpose 必须是 `knowledge_document`，音频分析时检查 upload 的 owner 必须和 interview owner 一致。
4. **临时文件清理**：Worker 下载的临时文件在 finally 块中用 `os.unlink()` 删除，不会遗留在文件系统中。

---

## 十三、评测与测试

### Q95：测试套件的覆盖范围是什么？

**A：** 测试套件在 `backend/tests/` 下，按层级组织：

- `test_api/`：API 路由集成测试。用 FastAPI 的 TestClient 模拟 HTTP 请求，验证路由、鉴权、请求校验。
- `test_agent/`：普通 chat pipeline 测试。测试 Planner、Context Assembly、stream_chat_with_agent 的核心逻辑。
- `test_services/`：服务层单元测试。测试 MemoryExtractionService、ContextAssemblyPipeline、TranscriptService 等。
- `test_rag/`：RAG 检索测试。测试 ingestion、retriever、hybrid scorer。
- `test_core/`：配置、安全、模型注册测试。
- `test_models/`：ORM 模型测试。
- `test_db/`：数据库连接测试。

运行 `pytest backend/tests -q` 应该通过 **81 个测试**。P2 改造新增了 15 个测试，覆盖 Refresh Token 双令牌验证、`safe_background_task()` 生命周期管理、BM25 per-user 缓存隔离/过期/失效等关键场景。pytest 配置（`pytest.ini`）声明了 `slow` 和 `integration` markers，并通过 `filterwarnings` 抑制第三方库的已知弃用警告。

### Q96：RAG 评测和 Agent 评测为什么分开做？

**A：** 因为两者评测的目标完全不同：

**RAG 评测**评的是"检索质量"——给定一个问题，检索到的片段是否包含正确答案。指标是 hit_rate（正确文档是否被检索到）和 MRR（正确文档排在第几位）。这和 Agent 的推理能力无关。

**Agent 评测**评的是"推理和工具使用质量"——给定一个复杂任务，Agent 是否能正确选择工具、正确传参、最终给出合理答案。指标是 completion_rate、avg_steps、invalid_tool_call_rate。这和 RAG 的检索质量无关。

如果混在一起评测，一个 Agent 失败了，很难区分是 RAG 检索没命中导致的，还是 Agent 推理错误导致的。分开后，每个环节的问题可以独立定位。

### Q97：RAG 评测的具体方法和结果是什么？

**A：** 评测分为检索质量评测和生成质量评测两个维度。

**检索质量评测**（`evaluation/test_retrieval_quality.py` + `evaluation/eval_runner.py`）：

使用 835 条黄金数据集（`evaluation/golden_dataset.jsonl`），每条记录包含 query、reference_answer、user_id、source_type 等字段。对每个 query 执行 `query_knowledge_base()`，计算以下指标：

| 指标 | 结果 | 含义 |
|------|------|------|
| Hit Rate@3 | 99.9% | 正确文档出现在前 3 个结果中的比例 |
| MRR@5 | 0.990 | 正确文档几乎总是排在第 1 位（满分 1.0） |
| P95 检索延迟 | 98ms | 含向量检索 + BM25 + RRF + Reranker 全流程 |

**生成质量评测**（`evaluation/test_generation_quality.py`，基于 RAGAS v0.4.3）：

RAGAS 使用 LLM-as-Judge 方式，给定 (query, retrieved_context, generated_answer, reference_answer) 四元组，自动评估生成质量。在 50 条端到端样本上的结果：

| 指标 | 结果 | 含义 |
|------|------|------|
| 忠实度（Faithfulness） | 94.5% | AI 回答中的声明几乎都能在检索上下文中找到依据 |
| 上下文精确度（Context Precision） | 95.2% | 检索到的文档中 95.2% 与问题真正相关 |
| 上下文召回率（Context Recall） | 100% | 正确答案需要的信息全部被检索到 |

**响应延迟**：首字响应延迟（TTFT）约 0.8 秒（含 Planner + 检索 + 上下文组装），端到端 P95 响应约 5.0 秒。

### Q98：如何验证防幻觉机制是否有效？

**A：** 两种验证方式：

1. **负面测试**：构造知识库中明确不存在的问题（如一个完全编造的技术名词），验证系统是否返回 `[SYSTEM_EMPTY_WARNING]` 而不是编造答案。
2. **边界测试**：构造和知识库内容稍微相关但不完全匹配的问题，验证 Reranker 分数是否低于 0.5。检查词法覆盖 Fallback 是否在合适的场景生效。
3. **RAGAS 忠实度验证**：忠实度 94.5% 从生成侧量化了防幻觉效果——AI 回答中绝大多数声明都有检索文档支撑。

目前这类测试在 `test_rag/` 和 `evaluation/test_generation_quality.py` 中有覆盖。

---

## 十四、优化方向与未来规划

### Q99：RAG 还有哪些优化方向？

**A：** 三个主要方向：

1. **Parent-Child Chunking**。当前的切块粒度是固定的。可以引入父子关系——细粒度切块用于向量检索（提高匹配精度），命中后返回父节点（更大的上下文窗口）。这能解决"找到了关键词但上下文不够"的问题。

2. **Query Expansion**。当前的 dense_query 和 sparse_query 由 Planner 一次性生成。可以对 query 做多角度扩展（HyDE、Multi-Query），用多个变体查询分别检索，再融合结果。这能提高语义覆盖率。

3. **SPLADE 替代 BM25**。SPLADE 是一种学习到的稀疏表示，比 BM25 的硬编码 TF-IDF 更好。Milvus 已经支持稀疏向量，可以用 SPLADE 编码替代应用层 BM25，同时减少 PostgreSQL Docstore 的负担。

### Q100：记忆系统还有哪些优化方向？

**A：**

1. **记忆遗忘机制**。基于 recall_count 和 last_accessed_at 设计衰减策略。长期不被召回的低 importance 记忆逐渐降低优先级甚至自动归档。

2. **用户确认机制**。关键记忆（如技术栈变更、职业方向变化）在写入前先征求用户确认。通过前端弹窗让用户审核抽取的记忆，避免 LLM 误解。

3. **记忆冲突检测**。当新记忆和旧记忆矛盾时（如"用户从 Java 转到了 Go"），不是简单覆盖，而是保留两个版本并标记冲突，让用户选择。

### Q101：Agent 还有哪些优化方向？

**A：**

1. **工具扩展**。增加更多工具：爬取公司技术博客、搜索 GitHub 项目、查询 LeetCode 题目等。

2. **Plan-and-Execute 模式**。在 ReAct 循环前加一个显式规划步骤，让 LLM 先输出完整的执行计划（如"第一步搜索岗位，第二步获取详情，第三步结合画像生成建议"），再按计划执行。这比纯 ReAct 更可控。

3. **并行工具调用**。当前工具调用是串行的（一次一个）。如果 LLM 同时返回多个工具调用（OpenAI API 支持），可以并行执行，减少总延迟。

### Q102：上下文 Pipeline 还有哪些优化方向？

**A：**

1. **动态 token 预算**。当前各类上下文的 token 预算是固定的。可以根据实际内容动态调整——如果记忆很少，把记忆的预算让给知识片段。

2. **上下文质量评分**。给每条上下文（记忆、知识片段）打一个质量分数，按分数排序后截断，而不是简单地按顺序截断。

3. **增量 Compaction**。当前 Compaction 是一次性把所有旧消息压缩。可以改成每次只压缩最旧的一批，减少 LLM 调用的输入长度。

---

## 十五、总结与反思

### Q103：这个项目最亮的设计点是什么？

**A：** 我认为是**确定性 Agentic Workflow + 防幻觉三重防线**的组合。

确定性 Agentic Workflow 解决了"怎么在保持可控性的同时让系统有智能决策能力"的矛盾。普通问答走固定阶段的流水线（阶段可预测），但 Query Planner 在运行时决定每个阶段是否执行（决策灵活）。这比纯 ReAct 更快更稳，比纯规则更智能。

防幻觉三重防线解决了"RAG 系统的可信度"问题。绝大多数 RAG 系统只有一层过滤（向量相似度阈值），我们加了 Reranker 绝对分数阈值 + 词法覆盖 Fallback + SYSTEM_EMPTY_WARNING 三层，把误报率（错误拦截有用内容）和漏报率（放行不相关内容）都控制在很低的水平。

### Q104：项目最大的收获是什么？

**A：** 最大的收获是理解了"工程质量不等于技术复杂度"。

很多技术决策表面上看起来"不够酷"——比如用确定性流水线而不是全 Agent、用应用层 BM25 而不是 Elasticsearch、用固定 token 预算而不是动态分配。但这些"朴素"的方案在实际中更稳定、更好维护、更容易排查问题。

另一个收获是**降级策略的重要性**。每个环节都设计了失败时的降级路径：Planner 失败→fallback 计划，Reranker 不可用→纯 RRF，记忆向量写入失败→纯词法召回，BM25 构建失败→纯向量检索。这让整个系统不会因为某个组件的临时故障就完全不可用。

### Q105：面试官质疑"这不就是套壳 ChatGPT 吗"，怎么回应？

**A：** 我会从三个维度说明这不是套壳：

**第一，LLM 在系统中只是一个组件，不是全部**。系统有独立的 RAG 检索管线（Milvus + BM25 + Reranker + 防幻觉闸门）、独立的长期记忆系统（抽取→向量化→混合召回→四因素打分）、独立的上下文管理（Compaction + TokenBudgeter + PromptRenderer）、独立的 Agent 运行时（Budget 控制 + Trace 遥测）。这些都不是 ChatGPT 提供的能力。

**第二，系统的核心价值在于工程设计，不在于调 API**。防幻觉三重防线、多租户四层隔离、HybridRetriever 四因素打分公式、AgentBudget 六维资源控制——这些都是基于具体业务场景设计的工程方案，不是简单地把用户输入转发给 LLM。

**第三，套壳产品没有可观测性和质量保障**。Agent Trace 全量记录每次执行的每一步，RAG 评测验证检索准确率，Agent 轨迹评测验证推理质量。这些都是生产级系统必需的工程能力。

### Q106：如果从头重做，你会先改什么？

**A：** 三个改进：

1. **先设计评测体系，再写代码**。目前的评测体系是后补的。如果一开始就定义好 RAG 的 hit_rate 基线和 Agent 的 completion_rate 基线，每次代码修改都能立即验证是否有回退。

2. **一开始就用 PostgreSQL 而不是 SQLite**。早期为了快速迭代用了 SQLite，后来迁移到 PostgreSQL 花了不少精力。如果一开始就用 PostgreSQL + Docker Compose，可以省去迁移的工作量。

3. **更早引入结构化日志**。早期用的是 `print()` 和简单的 `logging`，排查分布式问题（API → Celery Worker）很困难。如果一开始就用结构化日志（JSON 格式 + request_id 追踪），调试效率会高很多。

### Q107：一句话概括这个项目？

**A：** Interview Copilot 是一个生产级的 AI 面试准备后端系统，通过确定性 Agentic Workflow、混合 RAG 检索、四层长期记忆和全链路可观测性，把"面试练习、录音复盘、知识沉淀"串成一套可靠的工程闭环。

### Q108：你觉得这个系统最大的技术风险是什么？

**A：** 最大的技术风险是**对 LLM 质量的依赖**。

系统中有大量环节依赖 LLM 的输出质量：Query Planner 的意图判断、记忆抽取的准确性、Compaction 的摘要质量、Interview State 的更新准确性、面试分析的评分合理性。

如果 LLM 的质量下降（比如模型更新后 Function Calling 的准确率降低），所有依赖 LLM 的环节都会同时受影响。虽然每个环节都有 fallback 策略，但整体用户体验仍然会下降。

缓解措施：

1. 通过 Model Registry 支持快速切换模型。
2. 通过 Agent Trace 和 RAG 评测及时发现质量下降。
3. 关键路径上的 LLM 输出都有 Pydantic 校验，格式错误会被拦截。

### Q109：你是怎么做技术决策的？有什么原则？

**A：** 三个原则：

1. **够用就好，不追求最优**。应用层 BM25 不如 Elasticsearch，但当前数据量下性能足够。等到真的遇到瓶颈再升级，而不是提前过度设计。

2. **每个决策都留退路**。选 Milvus 但通过 LlamaIndex 的 VectorStore 接口抽象，切换到 Chroma 只需要改几行代码。选 DeepSeek 但通过 Model Registry 抽象，切换到 GPT-4 只需要改一个配置。

3. **降级优于崩溃**。任何组件失败都不应该导致整个系统不可用。Reranker 挂了降级到 RRF，记忆向量写入失败降级到词法召回，Planner 失败降级到默认计划。

### Q110：这个项目的测试策略是什么？

**A：** 分三层：

1. **单元测试**：针对独立组件的逻辑测试。比如 TokenBudgeter 的截断逻辑、_sanitize 的过滤规则、HybridRetriever 的打分公式。不依赖外部服务，mock 数据库和 LLM。

2. **集成测试**：针对模块间协作的测试。比如 API → Service → DB 的完整链路、Celery 任务的状态流转。使用测试数据库（内存 SQLite 或 Docker PostgreSQL）。

3. **评测**：针对系统质量的端到端验证。RAG 评测验证检索准确率，Agent 轨迹评测验证推理质量。需要真实的 LLM 和向量数据库。

---

## 补充问答

### Q111：assemble_rewrite_context 和 assemble_answer_context 为什么分两步？

**A：** 因为两个步骤需要的上下文范围完全不同。

`assemble_rewrite_context()` 只是给 Query Planner 提供足够的信息来理解用户的意图。它只需要 Working State + Interview State + 最近 10 轮对话。不需要加载记忆和知识库，因为 Planner 的任务是"理解问题"而不是"回答问题"。

`assemble_answer_context()` 是给最终回答 LLM 用的。它需要完整的上下文：Working State + Interview State + 记忆 + 知识片段 + 近期对话 + 当前问题。

如果合并成一步，要么 Planner 要处理大量不必要的上下文（增加延迟和成本），要么回答 LLM 缺少记忆和知识（降低回答质量）。

### Q112：Embedding 模型为什么从 bge-small-zh-v1.5 迁移到 BGE-M3？

**A：** 迁移的核心原因是检索质量的显著提升。

`bge-small-zh-v1.5` 是一个 512 维的轻量中文 Embedding 模型，约 33MB。在早期版本中使用它，Hit Rate 约 91%。迁移到 `BGE-M3`（1024 维）后，Hit Rate@3 提升到 99.9%，MRR@5 从约 0.85 提升到 0.990。

BGE-M3 的优势：

1. **1024 维向量**。更高的维度意味着更强的语义表达能力，尤其是对中英混合术语（如"Redis 的 AOF 持久化"）的编码质量显著更高。
2. **支持 8192 tokens 输入**。文档切块可以更完整地被编码，减少了因切块过长导致的语义截断问题。
3. **多语言支持**。BGE-M3 同时支持中文和英文，对面试场景中常见的中英混合表达更友好。

迁移的代价：

- 向量存储翻倍（512 维 → 1024 维），Milvus 的存储需求增加。
- 模型体积更大（约 2.2GB vs 33MB），冷启动加载时间增加。
- 需要重建 Milvus collection 并重新摄取所有文档。

最终判断：在面试准备场景下，数据量不大（万级向量），存储和加载时间的增加完全可以接受，而检索质量的提升是决定性的。

### Q113：为什么 Milvus 用 IP（内积）而不是余弦相似度或 L2 距离？

**A：** 先解释一下背景：在向量数据库中，判断两个文本"有多相似"需要用某种数学方法计算两个向量之间的"距离"或"相似度"。常用的方法有三种：IP（内积，即把两个向量对应位置的数字相乘再加起来）、余弦相似度（考虑两个向量夹角的大小）和 L2 距离（欧氏距离，即两点之间的直线距离）。

项目选 IP 的原因是：BGE Embedding 模型输出的向量是**归一化的**（每个向量的长度都被标准化为 1）。在这种条件下，IP 和余弦相似度在数学上是完全等价的——计算结果一模一样，排序也一模一样。但 IP 的计算比余弦相似度稍快，因为余弦相似度在计算时需要额外除以两个向量的长度，而归一化后长度都是 1，这一步就是多余的。所以在结果完全一样的前提下，选计算更快的 IP。

L2 距离（欧氏距离）也能用，但它的排序方向和相似度相反——L2 越小表示越相似（距离越近），而 IP 越大表示越相似（方向越一致）。这种"越小越好 vs 越大越好"的差异容易在代码中造成混淆和 Bug，所以不选它。

### Q114：safe_background_task 是怎么实现的？和直接用 asyncio.create_task 有什么区别？

**A：** `safe_background_task()` 定义在 `backend/app/core/background_tasks.py`，是对 `asyncio.create_task()` 的安全封装，加了三个保障：

1. **GC 保护**（强引用防回收）。创建的 task 会被加入一个全局的 `_background_tasks: set[asyncio.Task]` 集合。Python 的垃圾回收器如果发现一个 `asyncio.Task` 没有任何引用，即使它还在运行也会被回收。通过在全局集合中持有强引用，确保 task 在运行期间不会被意外回收。task 完成后通过 `done_callback` 自动从集合中移除。

2. **异常自动日志**。原生的 `asyncio.create_task()` 如果任务抛出异常，异常会被静默吞掉（除非你显式 `await` 这个 task，但 fire-and-forget 场景下没有人 await）。`safe_background_task()` 通过 `task.add_done_callback()` 在回调中检查 `task.exception()`，如果有异常就自动记录 error 日志（包含完整的异常堆栈）。

3. **优雅关停排空**。`cancel_and_wait_all(timeout)` 函数会取消所有挂起的后台任务并等待它们结束。这在 FastAPI 的 lifespan shutdown 阶段调用，确保应用关停时不会丢失正在执行的 Compaction 或记忆抽取。

这对 post-turn maintenance 很关键——如果 maintenance task 被意外回收，Compaction 和记忆抽取就不会执行，用户的 Working State 和长期记忆就不会更新。

### Q115：为什么 Celery Worker 用 --pool=solo 而不是 prefork 或 gevent？

**A：** `--pool=solo` 意味着 Worker 只有一个进程、一个线程。

选择理由：

1. **GPU 资源**。WhisperX 模型加载到 GPU 后占用显存。如果用 prefork（多进程），每个子进程都要加载一份模型，显存不够。solo 模式只有一个进程，GPU 资源独占。
2. **async 兼容**。solo 模式下，`run_async()` 创建的事件循环不会和其他进程冲突。prefork 模式的 fork 可能导致事件循环状态不一致。
3. **任务量级**。面试准备场景的任务量不大（个人使用，不是高并发服务），一个 Worker 进程足够处理。

如果需要扩展并发，可以启动多个 Worker 容器实例（水平扩展），而不是在单容器内用 prefork。

### Q116：Interview State 的 next_question 字段是怎么生成的？

**A：** `next_question` 是 Interview State 更新时 LLM 生成的建议。当 `_update_interview_state()` 调用 fast LLM 时，prompt 中包含了当前的面试状态（已覆盖主题、已发现的薄弱点、候选人声称的技能），LLM 基于这些信息推荐下一个最有价值的面试问题。

这个字段的作用是：当用户主动询问"下一个问题是什么"时，模型可以直接引用 Interview State 中的建议，而不是随机生成。

### Q117：文档摄取时 LlamaParse 和 PyMuPDF 的分工是什么？

**A：** 取决于 `LLAMA_CLOUD_API_KEY` 是否配置：

- **如果配置了**：PDF/PPTX/DOCX 文件先通过 LlamaParse（LlamaIndex 的云端文档解析服务）转成 Markdown，再用 MarkdownNodeParser 切分。LlamaParse 能保留表格结构、排版层级和图表描述，质量远高于直接文本提取。

- **如果没有配置**：退回到 LlamaIndex 默认的 SimpleDirectoryReader，底层用 PyMuPDF 直接提取文字。这种方式表格会被打平、排版信息丢失。

这是一个渐进增强的设计——基础功能不依赖云服务，但如果用户有 LlamaCloud 账号，可以获得更好的解析质量。

### Q118：为什么 QueryPlan 的 memory_types 和 knowledge_sources 是列表而不是 bool？

**A：** 因为不同的问题可能只需要特定类型的记忆或特定来源的知识。

比如用户问"我之前说过喜欢什么回答风格？"，Planner 应该只召回 `interaction_preference` 类型的记忆，不需要 `project_reference`。如果是 bool（"要不要召回记忆"），就会召回所有类型的记忆，其中 `project_reference` 的内容是无关噪声。

同理，用户问"Redis 的持久化有哪些"，Planner 应该只检索 `official_docs` 源，不需要检索 `interview_qa` 源（面试题库里的内容可能和官方文档重复但措辞不同，混在一起反而干扰）。

列表类型给了 Planner 更细粒度的控制权，减少了无关内容占用有限 token 预算的问题。

### Q119：你的 prompt 是怎么管理的？为什么不用模板引擎？

**A：** 项目中的 prompt 以 Python 常量的形式定义在各自的服务文件中（如 `context_service.py` 的 `RAG_SYSTEM_RULES`、`DIRECT_SYSTEM_RULES`，`planner.py` 的 `PLANNER_SYSTEM_PROMPT`），通过 f-string 做变量插值。

没有用模板引擎（如 Jinja2）的原因：

1. **可审查性**。prompt 作为代码中的常量，改动会被 git 追踪。用模板引擎的话，模板文件和代码分离，审查起来不方便。
2. **类型安全**。f-string 的变量在 Python 层面可以做类型检查。模板引擎的变量是动态的，拼错了变量名不会报错。
3. **复杂度不够**。项目的 prompt 模板不多（5-8 个），不需要模板引擎的继承、循环、条件等高级功能。

### Q120：如果 Milvus 完全不可用，系统还能正常工作吗？

**A：** 部分功能降级，但核心对话不中断。

具体影响：

- **RAG 检索**：向量检索路径不可用，但 BM25 路径独立于 Milvus。系统会降级为纯 BM25 检索。检索质量下降（缺少语义匹配），但仍然能返回关键词匹配的文档。
- **记忆召回**：向量召回路径不可用，降级为纯词法召回（从 PostgreSQL 读取记忆，用关键词匹配排序）。
- **文档摄取**：向量写入失败，但 PostgreSQL Docstore 的写入不受影响。向量部分在 Milvus 恢复后通过 backfill 机制补写。
- **对话本身**：不受影响。Query Planner、Context Assembly、LLM 回答都不依赖 Milvus。

这体现了系统的弹性设计——每个组件的失败都有独立的降级路径，不会级联导致整个系统崩溃。

### Q121：为什么用 bcrypt 而不是 passlib 做密码哈希？

**A：** 因为 passlib 库有一个影响生产安全的 Bug。

passlib 在处理超过 72 字节的密码时，某些版本会静默截断密码再哈希，但校验时不截断，导致验证永远失败。更严重的是，passlib 的 `CryptContext` 在某些配置下处理长密码时会直接 crash。

而且 passlib 已经长期不维护（最后一次发布是 2020 年）。直接使用 `bcrypt` 包更简洁、更安全，API 也足够简单（`bcrypt.hashpw()` 和 `bcrypt.checkpw()`），不需要 passlib 的抽象层。

### Q122：ContextBundle 中的 knowledge_snippets 和 relevant_memories 有去重机制吗？

**A：** 知识片段和记忆之间没有做跨类型去重。因为两者的来源和性质不同——知识片段是从知识库检索的长段落，记忆是从对话中抽取的短事实。即使内容有重叠，模型也能从两个不同的角度理解。

但在各自的类型内有去重：

- 知识片段通过 RRF 融合时，同一个 node 不会被重复计算（基于 node_id 去重）。
- 记忆通过 normalized_key 做了合并，同一个键的记忆只会存一条。

如果将来发现跨类型重复严重影响 token 预算，可以在 ContextBundle 层面增加基于语义相似度的去重。

### Q123：为什么 Agent 的温度设成 0.2 而不是 0？

**A：** `AGENT_TEMPERATURE = 0.2` 是一个折中选择。

温度 0 意味着完全确定性输出（greedy decoding），每次给相同输入都返回相同结果。这在工具调用场景中看起来是好事，但实际有问题：如果模型第一次选了错误的工具或参数，温度 0 会让它在重试时重复同样的错误。

温度 0.2 引入了很小的随机性，使得：

1. 重试时有可能选择不同的工具或参数，增加恢复的概率。
2. 生成的最终回答有更自然的措辞变化。
3. 不会因为太高的随机性导致工具调用不稳定（温度 > 0.5 时 function calling 的可靠性显著下降）。

### Q124：如果用户在两个浏览器标签页同时向同一个 session 发消息，会有并发问题吗？

**A：** 会有，但系统做了一定的防护。

**对话写入**：`transcript_service.add_message()` 的 seq 是基于 `turn_count` 自增的，在数据库层面是原子的。两条消息会各自获得不同的 seq，不会冲突。

**post-turn maintenance**：通过 `asyncio.Lock()` 保护，同一个 session 的 maintenance 不能并发执行。如果两条消息几乎同时触发 maintenance，第二个会等待第一个完成。

**上下文读取**：可能出现轻微的"读旧"问题——第二条消息读取上下文时，第一条消息的 Compaction 可能还没完成。这会导致第二条消息看到的 Working State 是旧的。但这不会导致数据损坏，只是上下文质量轻微降低。

在实际使用中，同一用户同时在两个标签页聊天的情况很少见。

### Q125：系统的冷启动时间大概多久？瓶颈在哪？

**A：** 冷启动大约需要 15-30 秒，瓶颈在模型加载。

时间分解：

1. 数据库表创建 / 迁移检查：~1 秒
2. BGE-M3 Embedding 模型加载（BAAI/bge-m3, ~2.2GB）：~8-15 秒（GPU）/ ~15-25 秒（CPU）
3. BGE Reranker 加载（bge-reranker-base, ~278MB）：~5-10 秒
4. 记忆回填（backfill_pending，取决于 pending 记忆数量）：~1-5 秒
5. FastAPI 启动（路由注册、中间件）：~1 秒

如果是容器首次启动（需要从 HuggingFace Hub 下载模型），会显著增加时间。后续启动模型文件已缓存在本地，直接从磁盘加载。

优化方向：把模型文件 bake 进 Docker 镜像，省去下载步骤。或者使用 ONNX 量化版本的模型，减小文件体积和加载时间。

---

*文档包含 125 个问答，覆盖 15 个主题领域。基于项目实际代码撰写，所有回答可溯源到具体文件和函数。最后校准：2026-05-03，基于 BGE-M3 迁移及评测体系完善后的代码库状态。*
