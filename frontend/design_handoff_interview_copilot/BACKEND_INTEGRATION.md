# BACKEND_INTEGRATION.md

> 把这份原型接到你现有的 FastAPI 后端时，**逐项对照下表**。  
> 每个 section 都是：UI 触发点 → 该调用的真实端点 → 期望字段 → 后端现状 → ⚠️ gap & 建议。

约定：
- 所有路径示例都假设你按 README 第 6 节配了 Vite proxy（前端写 `/api/...`，被 rewrite 到 backend 根）。
- 认证：登录后把 `access_token` 放 `localStorage`，axios 请求头加 `Authorization: Bearer ${token}`。401 时尝试用 `refresh_token` 换新 access；二次 401 跳 `/auth`。

---

## 1. 认证 — `/auth` 页面

| UI 动作 | 方法 | 端点 | 请求 | 响应 |
|---|---|---|---|---|
| 注册按钮 | `POST` | `/register` | JSON: `{ username, password, email? }` | `{ message, user_id }` |
| 登录按钮 | `POST` | `/login` | **form-data** (`OAuth2PasswordRequestForm`): `username`, `password` | `{ access_token, refresh_token, token_type:"bearer" }` |
| 静默续期 | `POST` | `/refresh` | JSON: `{ refresh_token }` | 同 login |

**注意**：
- ⚠️ `/login` 接的是 **form-urlencoded**，不是 JSON。axios 调用：
  ```ts
  axios.post('/api/login', new URLSearchParams({ username, password }), {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
  })
  ```
- 没有 `email` 字段时注册仍允许（后端 `email: str = None`）。前端的"邮箱"输入框其实是 username，文案提示需要明确。
- ⚠️ 没有"忘记密码 / 邮箱验证"端点；登录页那两个链接先做成 `disabled` 或开发占位即可。
- 没有 `/logout`：前端直接清 localStorage 跳 `/auth`。

---

## 2. 复盘页 — `/review`

### 2.1 session 列表（左栏）

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| 拉取面试记录列表 | `GET` | `/interview-records` | 返回 `List[InterviewRecordListItem]`；这是"过往面试 session"，**不是** `/chat/sessions`。 |
| 拉某条详情（点击进入） | `GET` | `/interview-records/{record_id}` | 返回完整 QA 列表 |
| 拉这条的总结 | `GET` | `/interview-records/{record_id}/summary` | 可选，进入页面后 lazy load |
| 重命名 | ⚠️ **后端缺** | — | `interview_records` 当前**没有** PATCH 路由 |
| 删除 | ⚠️ **后端缺** | — | 当前**没有** DELETE 路由 |
| 新建空 session | 不需要单独建 | — | "新建"在前端只是新建本地 placeholder；真正的 `interview_id` 由 `/analyze` 生成 |

**⚠️ 后端最小改动建议**（在 `app/api/interview.py` 加两个）：

```python
@router.patch("/interview-records/{record_id}")
def rename_record(record_id: str, payload: RenameRequest,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    rec = db.query(InterviewRecord).filter_by(id=record_id, user_id=user.username).first()
    if not rec: raise HTTPException(404)
    rec.title = payload.title  # 你需要确认 InterviewRecord 模型里有 title 字段，没有就加迁移
    db.commit()
    return {"status": "ok"}

@router.delete("/interview-records/{record_id}")
def delete_record(record_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    rec = db.query(InterviewRecord).filter_by(id=record_id, user_id=user.username).first()
    if not rec: raise HTTPException(404)
    db.delete(rec); db.commit()
    return {"status": "ok"}
```

UI 期望的字段（请保证 list 接口返回这些 key，命名可改但要稳定）：

```ts
type InterviewRecordListItem = {
  id: string;
  title: string;          // 用户重命名；默认 "新建面试" 或文件名
  date: string;           // ISO 或 "5/08"，前端做格式化
  tag?: string;           // "Backend" / "Algorithm" / "HR" / "System"——可选，没有就不展示
  qa_count: number;       // 用来显示 "X 题"
};
```

### 2.2 中间 — 上传 / 转录 / QA 列表

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| 点上传卡片选音视频 | `POST` | `/upload/audio/direct` | multipart/form-data, field `file` |
| 触发分析 | `POST` | `/analyze` | 上传完成后立即调；返回 `interview_id` 或 task_id |
| 轮询分析状态 | `GET` | `/analyze/{interview_id}/status` | 每 1.5s 一次，直到 `status === "done"` |
| 拿 QA 列表 | `GET` | `/interview-records/{interview_id}` | done 后调 |
| 编辑某条 QA | ⚠️ **后端缺** | — | 当前没有 QA 级别的 update |
| 上传简历（也用于复盘） | `POST` | `/upload/resume/direct` | multipart/form-data |

**⚠️ 后端最小改动建议**：
- QA 编辑端点 `PATCH /interview-records/{record_id}/qa/{qa_index}`，body `{ question?, answer? }`。
- `/analyze` 应当返回 `{ interview_id, task_id }`，并把转录写入 `interview_records.qa_pairs`（JSON）；前端拿到 `done` 后用 record_id GET 全部。

UI 期望的 QA 形状：

```ts
type QA = {
  q: string;          // 问题文本
  a: string;          // 答案文本
  s?: string;         // 可选：LLM 生成的"优化回答" / 复盘建议（折叠区里展示）
  duration_ms?: number;
};
```

### 2.3 右侧 ChatPanel

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| session 内创建一个 chat | `POST` | `/chat/sessions` | body `{ session_type: "debrief", interview_id: <record_id>, title? }` |
| 列出当前 session 的 chat 列表 | `GET` | `/chat/sessions?session_type=debrief&interview_id=<id>` | ⚠️ 当前 `/chat/sessions` GET **不支持** 这两个过滤参数 |
| 切换 chat 时拉历史 | `GET` | `/chat/history?session_id=<chat_id>` | 已支持 offset/limit |
| chat 重命名 | `PATCH` | `/chat/sessions/{session_id}/title` | **title 是 query param**，不是 body |
| chat 删除 | ⚠️ **后端缺** | — | 当前没有 DELETE |
| 发送消息（流式） | `WS` | `/chat/ws/{session_id}` | 或 `POST /chat/sse/{session_id}` 用 SSE |
| AGENT 模式 | `POST` | `/agent/react/stream` | 切到 AGENT toggle 时用这个，response 是流 |
| 附件 📎 | ⚠️ **后端缺** | — | 当前没有 chat 内 attachment 端点；建议复用 `/knowledge/documents` 上传并把 `document_id` 作为 hint 注入下一条消息 |
| 模型切换 | `PUT` | `/models/runtime` | 选完模型后立即 PUT，body 见 §5 |

**⚠️ 后端建议**：
1. `GET /chat/sessions` 增加 query 参数 `session_type`, `interview_id`，否则前端无法按 interview 隔离对话。
2. 加 `DELETE /chat/sessions/{session_id}`。
3. `PATCH .../title` 现在用 query param 不太规范，建议改为 body `{ title }`；如果嫌兼容麻烦保留 query 也行，前端写法：
   ```ts
   axios.patch(`/api/chat/sessions/${id}/title`, null, { params: { title } })
   ```

UI 期望的消息形状（接 `/chat/history`）：

```ts
type MessageItem = {
  seq: number;
  role: "user" | "assistant" | "system";   // 前端展示时 user→"me"，assistant→"ai"
  content: string;
  created_at: string;
};
```

流式 token 协议（WebSocket payload）以后端实际为准，常见三种事件：
- `{ type: "token", delta: "..." }` → 追加到当前 ai 气泡
- `{ type: "tool_call", name, args }` → AGENT 模式下渲染工具调用 chip
- `{ type: "done" }` → 关闭气泡 loading 状态

---

## 3. 模拟面试 — `/mock`

> **后端事实核对**（参照 GitHub `main` 分支 `backend/app/api/chat/mock_interview.py`、`backend/app/services/voice/audio_transcription_service.py`）：
> - 当前 `/chat/mock-interview/start` 的 body 只接收 `{ session_id, resume_upload_id? }`，**没有 `jd_text` 字段**。
> - 当前 `/chat/mock-interview/answer` 只接收文本 `{ session_id, answer }`，**没有 multipart / 音频流**。
> - 后端 STT 实现是 **WhisperX + Pyannote diarization**（`audio_transcription_service.transcribe_media`），只通过 `/upload/audio/direct` + `/analyze` 这条复盘链路使用，**没有面向模拟面试的 realtime / short-clip 端点**。
> - `/chat/mock-interview/finish` 已经自动建 `InterviewRecord`，返回 `{ record_id, debrief_session_id, summary }`，前端跳 `/review?id={record_id}` 即可。

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| Setup：创建 mock_interview session | `POST` | `/chat/sessions` | body `{ session_type: "mock_interview", title }`，拿 `session_id` |
| Setup：上传简历 | `POST` | `/upload/resume/direct` | multipart `file`，拿 `resume_upload_id` |
| Setup：上传 JD | ⚠️ **复用** | `POST /knowledge/documents` | category=`jd`；后端 start 当前用不到 JD（见下方 P1 建议） |
| 开始模拟 | `POST` | `/chat/mock-interview/start` | body `{ session_id, resume_upload_id }`，返回 `{ plan_phases, current_question }` |
| 拉当前问题 | `GET` | `/chat/mock-interview/question?session_id=...` | |
| 提交答案 | `POST` | `/chat/mock-interview/answer` | body `{ session_id, answer }`（**纯文本**） |
| TTS 朗读问题 | `POST` | `/chat/mock-interview/tts` | body `{ text, voice? }`，返回 `audio/mpeg` 流 |
| 结束面试 | `POST` | `/chat/mock-interview/finish?session_id=...` | 返回 `{ record_id, debrief_session_id, summary }`，前端跳 `/review?id={record_id}` |

### 3.1 录音 → 转写（前端实现策略）

**已确定方案：浏览器 `MediaRecorder` 录 webm/opus，提交给后端新增的短时转写端点，后端复用已加载的 WhisperX 模型。**

前端流程：

```ts
// 点击麦克风开始：
const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
const rec = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
const chunks: Blob[] = [];
rec.ondataavailable = (e) => chunks.push(e.data);
rec.start();

// 再点一下结束：
rec.stop();
await new Promise((r) => (rec.onstop = r));
const blob = new Blob(chunks, { type: "audio/webm" });

// 1) 转写成文字
const fd = new FormData();
fd.append("file", blob, "answer.webm");
const { text } = await api.post("/chat/mock-interview/transcribe", fd); // ⚠️ P1 需新增

// 2) 用文字走原有 answer 链路
await api.post("/chat/mock-interview/answer", { session_id, answer: text });
```

**为什么不用 WebSpeech**：Chinese-mainland Chrome WebSpeech 走 Google CN 服务，可用性差；且与后端 WhisperX 同账户语料/口音偏好无法对齐。**WhisperX 已经在 lifespan 里加载**，转写一段 < 60s 的 opus 几乎零额外开销。

**⚠️ P1 后端缺口（必须补）**：

```python
# backend/app/api/chat/mock_interview.py 新增
@router.post("/chat/mock-interview/transcribe")
async def transcribe_answer(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Short-clip STT for mock interview. Single speaker, no diarization."""
    from app.services.voice.audio_transcription_service import whisper_model
    import tempfile, whisperx
    # 写临时文件 → whisperx.load_audio → whisper_model.transcribe(audio, batch_size=16)
    # 不跑 diarize_model（单人，省时间）
    # 直接拼 segments → return {"text": "..."}
```

**JD 处理（最终方案）**：

我建议**走 `/knowledge/documents` + category=`jd`**，并把 `start` 改成支持可选 `jd_upload_id`。理由：
- 资料库本身就有 JD 这个 category，复用一套权限/存储/分类。
- 不需要新端点。
- 但 `start_mock_interview` 当前**完全不读 JD**——这是 **P1 后端改动**：

```python
# MockStartRequest 加字段
class MockStartRequest(BaseModel):
    session_id: str
    resume_upload_id: Optional[str] = None
    jd_upload_id: Optional[str] = None   # ⬅ 新增

# start_mock_interview 内：拿到 jd_upload_id 后从 KnowledgeDocument 读 text，
# 拼入 generate_plan(resume_context, jd_context) 的第二个参数
```

**前端落地这版可以这样写**：
- Setup 页两块上传都返回各自的 `upload_id`（resume 走 `/upload/resume/direct`，JD 走 `/knowledge/documents` 拿到 `document.id` 当 `jd_upload_id`）。
- 调 `/chat/mock-interview/start` 时把两个 id 都传上去，后端补齐之前可以暂时无视 `jd_upload_id`，不影响前端编码。

---

## 4. 个人资料库 — `/library`

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| 列出文件 | `GET` | `/knowledge/documents` | 可加 query：`category`, `q` 搜索 |
| 单个详情 | `GET` | `/knowledge/documents/{id}` | |
| 上传文件 | `POST` | `/knowledge/documents` | multipart, fields `file`, `category?` |
| 通过 URL 抓取 | `POST` | `/knowledge/upload/url` | body `{ url }` |
| 重命名 | `PATCH` | `/knowledge/documents/{id}` | body `{ title }` 或类似 |
| 删除 | `DELETE` | `/knowledge/documents/{id}` | |
| 分类列表 | `GET` | `/knowledge/categories` | 用来填筛选下拉 |

UI 期望：

```ts
type Doc = {
  id: string;
  title: string;
  size_bytes: number;
  category: "resume" | "jd" | "system_design" | "interview_notes" | string;
  updated_at: string;
};
```

---

## 5. 模型选择 — `/models`

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| 拉所有厂家 + model 列表 | `GET` | `/models/catalog` | 返回按 provider 分组的目录 |
| 拉当前运行时配置 | `GET` | `/models/runtime` | 返回每个用途（chat / agent / embedding / rerank）当前选的 model + 来源 |
| 保存配置 | `PUT` | `/models/runtime` | body 同上 |

UI 期望的 catalog 形状：

```ts
type Catalog = {
  providers: Array<{
    id: string;           // "openai" | "anthropic" | "deepseek" | "qwen" | ...
    name: string;         // "OpenAI"
    logo?: string;        // 可选 url
    models: Array<{
      id: string;         // "gpt-4o"
      name: string;       // "GPT-4o"
      capabilities: ("chat"|"agent"|"embedding"|"rerank")[];
      context_window?: number;
    }>;
  }>;
};
```

UI 期望的 runtime 形状：

```ts
type Runtime = {
  chat:      { provider: string; model: string; api_key_set: boolean };
  agent:     { provider: string; model: string; api_key_set: boolean };
  embedding: { provider: string; model: string; api_key_set: boolean };
  rerank:    { provider: string; model: string; api_key_set: boolean };
  // PUT 时把 api_key 也传（明文 only 在 PUT 请求里，GET 永远不返回明文）
};
```

⚠️ 如果你后端目前 catalog/runtime 的形状和上面差很多，**前端去适配**，但请保证下面三点不动摇：
1. 一定能按 provider 分组渲染。
2. 一定有"是否已设置 API Key"的 boolean，让前端显示绿色对勾。
3. PUT 的 api_key 字段名稳定。

---

## 6. 能力分析 — `/analytics`

| UI 动作 | 方法 | 端点 | 备注 |
|---|---|---|---|
| 拉雷达图 + 薄弱点 | `GET` | `/analytics/report` | 这是当前唯一端点 |

UI 期望（如果后端返回不一样，**优先改后端**对齐这份契约——这是新功能）：

```ts
type AnalyticsReport = {
  overall: number;                       // 0–100
  axes: Array<{ k: string; v: number }>; // 固定 6 个：系统设计 / 算法 / 沟通节奏 / 项目深度 / 表达 / 抗压
  totals: { sessions: number; avg_duration_sec: number; strongest_axis: string };
  trends: Array<{ k: string; series: number[] }>;  // 每个 axis 最近 N 次得分
  weaknesses: Array<{
    k: string;            // 维度
    v: number;            // 当前得分
    why: string;          // 原因分析（LLM 生成）
    docs: Array<{ t: string; url: string }>;
    practice: Array<{ t: string; url: string }>;
  }>;
};
```

**⚠️ 后端建议**：在 `app/services/diagnostics_report_service.py` 里把 6 个固定维度和"薄弱点 → docs/practice"两个字段加上；docs/practice 可以先返回站内固定知识库 url + `/mock?focus=...` 链接。

---

## 7. 个人中心 — `/me`

后端目前**没有专属端点**。建议先实现两个最小接口：

- `GET /me` → `{ username, email, joined_at, plan }`
- `PATCH /me` → 改 email / 显示名
- （以后再加 plan / billing / preferences）

前端先拿 `/me` 渲染头像（用 username 首字母 + 马卡龙色）+ 加入时间 + "登出"按钮。

---

## 8. 全局 cross-cutting

### 8.1 错误处理
- 后端用 FastAPI `HTTPException`，统一返回 `{ "detail": "..." }`。
- 前端 axios interceptor：
  - 401 → 尝试 refresh → 失败则清 token + 跳 `/auth`
  - 429 → toast "请求过于频繁"
  - 5xx → toast 后端报错文案，并在控制台 console.error

### 8.2 流式（WebSocket / SSE）
- 复盘 chat：优先用 `WS /chat/ws/{session_id}`
- agent 模式：用 `POST /agent/react/stream`（SSE）
- 模拟面试问答：HTTP POST 即可，不需要流

### 8.3 文件大小限制
- 音视频：建议前端先检查 < 200MB，超过给提示。后端实际限制以 nginx + FastAPI 配置为准（看 `nginx/conf.d/`）。
- 简历 / JD：< 10MB。

### 8.4 国际化
- 文案默认中文（zh-CN）。如果以后做 i18n，把 `screens.jsx` 里的所有字符串抽到 `frontend/src/i18n/zh.ts`。

---

## 9. 一份"先做什么"清单（给 Claude Code）

按这个顺序实现，每步都能在 UI 看到东西，不会卡死：

1. **脚手架**：Vite + React + TS + Tailwind + react-router + zustand + axios + lucide-react；把 `colors_and_type.css` 当 global token 引入；`@font-face` 指向 `fonts/Inter-var-2.ttf`。
2. **AuthLayout + Login/Register**：连 `/register`, `/login`, `/refresh`；存 token；登录后跳 `/review`。
3. **AppShell**：左侧 SideNav + 顶部 TopBar（用户头像 + logout），按 README 第 3 节实现 7 个路由 placeholder。
4. **Review 静态版**：列表用假数据，左中右三栏，所有交互完整（rename / delete / 双击编辑等），不接接口。
5. **Review 接口接入**：依次接 `interview-records`（list/detail/summary），上传 + analyze 轮询，chat/sessions + chat/history + WS。
6. **Mock**：先实现 setup → live 的 UI 状态机，再接 `/chat/mock-interview/*`。
7. **Library**：完整 CRUD，接 `/knowledge/documents`。
8. **Models**：先用 mock catalog 渲染 UI，再接 `/models/catalog` + `/models/runtime`。
9. **Analytics**：用 `/analytics/report`；如果后端返回字段不全，先 mock 补齐前端再让后端跟上。
10. **Profile**：等后端加 `/me`，先做"登出"+"账户信息（username only）"。

---

## 10. 反向：后端**确定**需要补的端点 / 字段

把这一段直接发给写后端的同学（或后端 Claude Code session）即可。

```
P1 必须补：
- PATCH /interview-records/{id}          —— body { title }
- DELETE /interview-records/{id}
- GET /chat/sessions?session_type&interview_id  —— 增加 query 过滤
- DELETE /chat/sessions/{session_id}
- PATCH /interview-records/{id}/qa/{idx}  —— 编辑某条 QA 的 q/a
- GET /me + PATCH /me

P1 模拟面试链路（前端已按这套设计）：
- POST /chat/mock-interview/transcribe   —— 短时 STT，复用已加载的 WhisperX，无 diarization
- MockStartRequest 增加 jd_upload_id     —— JD 走 /knowledge/documents (category=jd)，start 时读出拼到 plan 上下文

P2 建议补：
- /chat/mock-interview/finish 已返回 record_id（已确认）—— 前端跳 /review?id={record_id}
- /models/runtime 区分 chat/agent/embedding/rerank 四个用途
- /analytics/report 输出 6 axes + weaknesses[].docs/practice 链接

P3 nice-to-have：
- /logout（黑名单 jwt）
- /chat/sessions/{id} attachments
- WebSocket 协议文档化（events 列表）
```
