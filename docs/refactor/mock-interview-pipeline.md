# 模拟面试 & 复盘链路重构方案

**作者**：studyzhige-ui
**日期**：2026-05-13
**状态**：Design Draft（待评审）

---

## 1. 背景与目标

### 1.1 现状问题

| # | 问题 | 证据 |
|---|------|------|
| 1 | 两套并行 DB：老 `Interview/Transcript/AnalysisResult` + 新 `InterviewRecord`，共存且互不一致 | `backend/app/models/` |
| 2 | 两条分析流水线：upload 走 Celery 三阶段；mock 在 finish 接口里**同步**跑 `batch_evaluate` | [backend/app/api/chat/mock_interview.py:206-279](backend/app/api/chat/mock_interview.py#L206-L279) |
| 3 | `analysis_json` 形状不统一：mock 用 `qa_history`，upload 用 `per_question`，前端 duck-type 兼容 | [backend/app/api/interview.py:534-538](backend/app/api/interview.py#L534-L538) |
| 4 | Mock 入口繁琐：每次都要显式传 `resume_upload_id`，且和 upload 路径不共享上传组件 | MockSetup.tsx |
| 5 | Mock finish 阻塞：`batch_evaluate` LLM 调用在 HTTP 请求内同步跑完 | mock_interview.py:236-260 |
| 6 | Mock 复盘体验弱：跳到复盘页但没有 SSE 进度、没有"原始文稿"tab、QA panel 渲染分支 | frontend/src/pages/review/* |

### 1.2 目标

- **唯一事实源**：`InterviewRecord + InterviewQA` 一套表覆盖 mock 和 upload 两种来源
- **统一分析流水线**：mock 和 upload 共用同一个 orchestrator，差异只在前置步骤
- **统一复盘体验**：跳到复盘页后，UI/进度/分析结果结构完全一致；SessionList 状态展示沿用现有前端设计
- **mock 入口对齐 upload**：默认即时上传简历 + JD；用户也可从资料库挑一份简历覆盖默认
- **快照不可变**：`InterviewRecord` 必须冻结当时使用的简历正文和 JD 正文，源文件后续改动/删除不影响历史复盘

---

## 2. 数据模型设计

### 2.1 资源对象

```
UserUpload                          # 既有，扩 purpose 枚举
  purpose: 'interview_resume'          # mock + upload 都用；可即时上传也可来自资料库导入
        | 'interview_audio'            # upload 专用
        | 'interview_jd_ephemeral'     # mock 一次性 JD，不入资料库
  status:  'pending_upload' | 'uploaded' | 'consumed' | 'archived'

KnowledgeDocument                   # 既有，资料库
  doc_type: 'resume' | 'jd' | ...
  # mock 可从这里挑 resume（可选项），JD 资料库不参与 mock 流程
```

**决策**：
- **简历**：默认每次即时上传（和 upload 路径完全一致的上传组件）；用户也可选择 "从资料库选一份简历" 作为替代入口。
- **JD**：每次即时上传，不入资料库。存为 `UserUpload(purpose='interview_jd_ephemeral')`，分析完成后标 `archived`，定期清理。
- **不在 User 表加 active_*_id 字段**：避免引入隐式全局状态；简历/JD 通过显式入参传入。

### 2.2 面试记录（核心，取代旧三表）

```sql
CREATE TABLE interview_records (
    id              VARCHAR PRIMARY KEY,           -- 'irec_xxx'
    user_id         INT NOT NULL REFERENCES users(id),
    source          ENUM('mock', 'upload') NOT NULL,
    status          ENUM('pending', 'transcribing', 'extracting',
                         'analyzing', 'completed', 'failed') NOT NULL,
    title           VARCHAR,
    tag             VARCHAR,

    -- 引用快照（用于追溯）
    resume_upload_id   VARCHAR REFERENCES user_uploads(id),       -- 必填
    resume_doc_id      VARCHAR REFERENCES knowledge_documents(id),-- 若来自资料库则有
    jd_upload_id       VARCHAR REFERENCES user_uploads(id),       -- mock/upload 都有
    audio_upload_id    VARCHAR REFERENCES user_uploads(id),       -- 仅 upload

    -- 内容快照（不可变）
    resume_text_snapshot   TEXT NOT NULL,
    jd_text_snapshot       TEXT NOT NULL,
    interview_plan_json    JSON,                    -- mock：generate_plan 产出

    -- 原始素材
    raw_transcript     TEXT,                        -- upload: ASR；mock: Q&A 拼接
    transcript_segments_json JSON,                  -- upload: WhisperX 时间戳；mock: null

    -- 顶层分析结果（逐题在 interview_qa）
    analysis_json      JSON,                        -- schema 见 §2.4
    analysis_schema_version INT NOT NULL DEFAULT 2,

    celery_task_id     VARCHAR,
    error_message      TEXT,

    created_at, updated_at, completed_at
);

CREATE INDEX idx_interview_records_user_created ON interview_records(user_id, created_at DESC);
```

### 2.3 逐题表（新增）

```sql
CREATE TABLE interview_qa (
    id              VARCHAR PRIMARY KEY,            -- 'qa_xxx'
    record_id       VARCHAR NOT NULL REFERENCES interview_records(id) ON DELETE CASCADE,
    order_idx       INT NOT NULL,
    phase           VARCHAR NOT NULL,               -- 模型推断，无枚举强约束；常见值见下
    phase_label     VARCHAR,                        -- 显示名（来自 plan 或 LLM 输出）

    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    question_summary VARCHAR,
    is_follow_up    BOOLEAN DEFAULT FALSE,
    parent_qa_id    VARCHAR REFERENCES interview_qa(id),

    source_segment_start FLOAT,                     -- upload 时间戳
    source_segment_end   FLOAT,

    -- 来源与扎根
    grounding_refs  JSON,                           -- ["exp_1.h1","req_2"] 或 ["fundamentals:gc"]
    follow_up_depth INT DEFAULT 0,                  -- 0=主问，>0=追问层级

    -- 语音
    question_audio_url VARCHAR,                     -- 面试官 TTS S3 URL（可选）
    answer_audio_url   VARCHAR,                     -- 用户语音 S3 URL（可选）
    answer_input_mode  ENUM('text','voice','voice_transcribed') DEFAULT 'text',

    -- 分析结果
    score           INT,                            -- 0-100
    critique        TEXT,
    improved_answer TEXT,
    key_points_json JSON,
    analyzed_at     TIMESTAMP,

    created_at      TIMESTAMP
);

CREATE INDEX idx_interview_qa_record_order ON interview_qa(record_id, order_idx);
```

**Phase 设计**：不做强枚举。常见值：`self_intro | resume | technical | behavioral | system_design | reverse_qa`，但**由 LLM 根据上下文判断输出**，DB 只存字符串。未来引入"岗位模板"系统时再做规范化映射，目前对用户无感。

### 2.4 `analysis_json` 统一 Schema (v2)

```jsonc
{
  "schema_version": 2,
  "overall": {
    "score": 78,
    "summary": "...",
    "strengths": ["...", "..."],
    "weaknesses": ["...", "..."],
    "improvement_plan": [
      { "area": "system_design", "actions": ["..."], "resources": ["..."] }
    ]
  },
  "phase_summary": {
    "technical":  { "score": 75, "feedback": "..." },
    "behavioral": { "score": 82, "feedback": "..." }
  },
  "meta": {
    "model": "deepseek-v4-flash",
    "analyzed_at": "2026-05-13T...",
    "qa_count": 12,
    "duration_sec": 1820                    // upload 有；mock 为 null
  }
}
// 逐题数据走 interview_qa 表，不冗余在这里
```

### 2.5 会话表拆分（命名澄清）

把现有 `ChatSession` 按职责拆成两张表，避免 "chat" 名字覆盖到 mock 进行中状态：

**`MockInterviewSession`（新表）—— mock 进行中的临时态**

```sql
CREATE TABLE mock_interview_sessions (
    id                  VARCHAR PRIMARY KEY,        -- 'mis_xxx'
    user_id             INT NOT NULL REFERENCES users(id),
    interview_record_id VARCHAR NOT NULL REFERENCES interview_records(id),  -- 1:1
    status              ENUM('in_progress', 'finished', 'abandoned') NOT NULL,
    current_phase       VARCHAR,
    current_question_idx INT DEFAULT 0,
    qa_buffer_json      JSON,                       -- 推进中的 Q&A 缓冲，finish 时灌入 InterviewQA
    plan_snapshot_json  JSON,                       -- 冗余存一份 plan，避免每次回查 record
    interviewer_style   ENUM('friendly','professional','rigorous','pressure') DEFAULT 'professional',
    voice_mode          ENUM('text','voice','hybrid') DEFAULT 'hybrid',  -- 默认 hybrid（语音默认）
    last_activity_at    TIMESTAMP,                  -- 用于超时回收
    archived_at         TIMESTAMP NULL,             -- finish/abandon 时设置（软删）
    created_at, updated_at
);
CREATE INDEX idx_mis_user_active ON mock_interview_sessions(user_id, archived_at);
```

**`ChatSession`（保留并收窄）—— 仅复盘聊天 + 通用聊天**

```sql
ALTER TABLE chat_sessions RENAME COLUMN session_type TO kind;
-- kind ENUM('debrief', 'general')      ← 'mock_interview' 枚举值移除
-- session_state 字段可移除（mock 走了，剩下两类不需要它）
-- 加 archived_at TIMESTAMP NULL
```

**生命周期**：

- mock 进行中：`MockInterviewSession(status='in_progress')`
- 用户 finish → `status='finished', archived_at=now()`；同时分析 orchestrator 异步跑
- 用户中途放弃 / 7 天无操作 → `status='abandoned', archived_at=now()`
- 复盘对话：用户在复盘页打开 ChatPanel 时创建 `ChatSession(kind='debrief', interview_record_id=...)`

---

## 3. 服务层设计

### 3.1 统一分析编排器

新建 [backend/app/services/interview/analysis_orchestrator.py](backend/app/services/interview/analysis_orchestrator.py)：

```python
class InterviewAnalysisOrchestrator:
    """统一面试分析流水线。Mock 和 Upload 共享，差异在 step 1。"""

    MODEL = "deepseek-v4-flash"                # 全程使用 DeepSeek V4 Flash
    BATCH_SIZE = 2                             # 每次 LLM 调用分析 2 题
    CTX_PREV = 3                               # 前置上下文 3 题
    CTX_NEXT = 2                               # 后置上下文 2 题

    def run(self, record_id: str) -> None:
        record = self.repo.get(record_id)
        try:
            # Step 1: 准备 transcript + 结构化 QA
            if record.source == 'upload':
                self._mark(record, 'transcribing')
                self._transcribe(record)                      # WhisperX + Pyannote(2 speakers)
                self._mark(record, 'extracting')
                qa_inputs = self._extract_qa_with_llm(record)
            else:  # mock
                qa_inputs = self._load_mock_qa_from_session(record)
                record.raw_transcript = self._compose_transcript(qa_inputs)

            # Step 2: 落 interview_qa 行（先无 score）
            qa_rows = self.qa_repo.bulk_insert(record.id, qa_inputs)
            self._mark(record, 'analyzing')

            # Step 3: 批量 + 滑动窗口逐题分析
            self._analyze_questions_sliding(record, qa_rows)

            # Step 4: 全局综合
            record.analysis_json = self._global_synthesis(record, qa_rows)

            self._mark(record, 'completed')
            record.completed_at = now()
            self.repo.save(record)
        except Exception as e:
            record.status = 'failed'
            record.error_message = str(e)
            self.repo.save(record)
            logger.exception("analysis failed for %s", record_id)
            raise
```

### 3.2 滑动窗口设计

```
QA 列表 = [Q1, Q2, Q3, Q4, Q5, Q6, Q7, Q8, Q9]
batch_size=2, ctx_prev=3, ctx_next=2

Call 1: 分析 [Q1, Q2]
        prev_ctx: []          (前面无)
        next_ctx: [Q3, Q4]

Call 2: 分析 [Q3, Q4]
        prev_ctx: [Q1, Q2]    (取最近 3 题，此处只有 2 题)
        next_ctx: [Q5, Q6]

Call 3: 分析 [Q5, Q6]
        prev_ctx: [Q2, Q3, Q4]
        next_ctx: [Q7, Q8]

Call 4: 分析 [Q7, Q8]
        prev_ctx: [Q4, Q5, Q6]
        next_ctx: [Q9]

Call 5: 分析 [Q9]
        prev_ctx: [Q6, Q7, Q8]
        next_ctx: []
```

**Prompt 形态**：

```
你正在分析一段面试。下面给出本批待评分的 N 题，以及前后上下文（仅供参考，不评分）。
请输出严格 JSON：[{qa_id, score, critique, improved_answer, key_points}]。

【前置上下文】
[Q-3]: ...  [A-3]: ...
[Q-2]: ...  [A-2]: ...
[Q-1]: ...  [A-1]: ...

【本批待评分】
[Q1, qa_id=...]: ...  [A1]: ...
[Q2, qa_id=...]: ...  [A2]: ...

【后置上下文】
[Q+1]: ...  [A+1]: ...
[Q+2]: ...  [A+2]: ...

【简历 & JD 摘要】
{resume_snippet}
{jd_snippet}
```

**容错**：批量返回解析失败 → 退回单题分析；单题再失败 → 该题 `score=null, critique='分析失败'`，不阻塞整体。

### 3.3 全局综合

输入：全部 QA + 每题 score/critique + 简历快照 + JD 快照
输出：`analysis_json.overall + phase_summary`
单次 LLM 调用，模型同为 `deepseek-v4-flash`。

### 3.4 进度上报

- 每个 status 变更写 DB
- SSE 端点 `GET /interview-records/{id}/events` 监听 `InterviewRecord.status` + `analyzed_qa_count`（可加聚合）
- **前端通知**：复用现有 SessionList 状态展示设计，**不发邮件**

```
status flow:
  upload: pending → transcribing → extracting → analyzing → completed
  mock:                                          analyzing → completed
```

---

## 4. Mock 面试进行中逻辑设计

让 mock 真正"像在被针对性面试"，而不是套八股的关键。

### 4.1 设计思路：双循环 + 显式 grounding

```
外循环：Plan + Coverage      保证 JD/简历"该问的都问到"
内循环：Dynamic Follow-up    根据上一答动态深挖
```

### 4.2 启动时素材结构化

`POST /mock-interview/start` 内部多做一步 LLM 调用，把简历和 JD 解析成**有 ref_id 的证据池**，落到 `InterviewRecord.resume_structured_json` / `jd_structured_json`：

```jsonc
// ResumeEvidence
{
  "experiences": [
    {
      "ref_id": "exp_1",
      "company": "字节", "role": "后端", "period": "...",
      "highlights": [
        { "ref_id": "exp_1.h1", "text": "推荐系统 QPS 3k→12k", "topics": ["性能","推荐"] }
      ]
    }
  ],
  "projects": [...],
  "skills_claimed": ["Go","Python","Redis","K8s"]
}

// JDRequirements
{
  "must_have": [
    { "ref_id": "req_1", "skill": "Python 后端", "depth": "expert" },
    { "ref_id": "req_2", "skill": "分布式系统设计", "depth": "expert" }
  ],
  "nice_to_have": [...],
  "responsibilities": [
    { "ref_id": "resp_1", "text": "负责支付稳定性..." }
  ],
  "seniority": "senior",
  "domain": "fintech"
}
```

每个原子项有 `ref_id`。后续生成的每道题必须挂 `grounding_refs`（含八股的特殊命名空间）。

### 4.3 计划骨架（不是脚本）

```jsonc
{
  "phases": [
    { "phase_id": "p1", "kind": "self_intro",        "question_budget": 1 },
    { "phase_id": "p2", "kind": "resume_deep_dive",  "question_budget": 3,
      "target_refs": ["exp_1.h1", "exp_1.h2", "proj_2"] },
    { "phase_id": "p3", "kind": "technical",         "question_budget": 4,
      "target_refs": ["req_1", "req_2", "resp_1"],
      "fundamentals_quota": 1,                       // 见 §4.5
      "difficulty_curve": "warm_up→core→stretch" },
    { "phase_id": "p4", "kind": "behavioral",        "question_budget": 2,
      "target_refs": ["resp_1"] },
    { "phase_id": "p5", "kind": "reverse_qa",        "question_budget": 2 }
  ],
  "total_budget": 12,
  "estimated_duration_min": 35
}
```

### 4.4 问题生成逻辑

```python
def next_question(session):
    coverage = compute_coverage(session)
    last = session.qa_buffer[-1] if session.qa_buffer else None

    # 内循环：是否追问
    if last and should_follow_up(last, session.current_phase):
        return generate_follow_up(last, depth=session.current_follow_up_depth)

    # 外循环：八股配额 vs grounded
    if should_emit_fundamentals(session.current_phase):
        return generate_fundamentals_question(session.current_phase)

    next_ref = pick_next_ref(
        phase=session.current_phase,
        uncovered=session.current_phase.target_refs - coverage,
        last_topic=last.topics if last else None,
    )
    return generate_grounded_question(next_ref, resume, jd, session)
```

**`should_follow_up` 触发条件**（LLM 判断）：

- 答案过于简短/笼统
- 提到新可挖点（"我们解决了那个性能问题"→怎么解决？）
- 暴露知识空白，深挖验证
- 当前追问深度 < 2（防止无限钻牛角尖）

**`pick_next_ref` 策略**：

- 优先 must-have 未覆盖项
- 主题平滑切换（避免突兀跳话题）
- 难度遵循 `warm_up → core → stretch`

### 4.5 八股配额（按 seniority 自动）

`fundamentals_quota` 按 JD 推断的 seniority 自动设置：

| Seniority | 八股比例 | 理由 |
|-----------|---------|------|
| junior | 30% | 基础重要 |
| mid | 20% | 平衡基础和经验 |
| senior | 10% | 看深度和 trade-off |
| staff+ | ≤5% | 几乎全程深度问 |

调度规则：

- 仅 `technical` 阶段出八股；behavioral / system_design / resume 阶段禁止
- 一道八股出现的位置：当前 phase 已扎根问数 ≥ 2 时插入，避免开场就八股
- 八股题 `grounding_refs: ["fundamentals:<topic>"]` 特殊命名空间
- 复盘页可单独归类"基础知识题"

### 4.6 面试官人设

**Seniority（从 JD 推断）** 决定**难度**：

| Seniority | 风格 |
|-----------|------|
| junior  | 引导式、给提示、肯定为主 |
| mid     | 专业、深度适中、追问 1 层 |
| senior  | 严谨、追问 2 层、引入边界 case |
| staff+  | 挑战式、考察 trade-off、系统思维 |

**Style（用户在 MockSetup 选）** 决定**氛围**，与 seniority 正交组合：

| Style | 氛围 |
|-------|------|
| friendly      | 友善引导、给思考时间、温和追问 |
| professional  | 标准节奏、就事论事（默认） |
| rigorous      | 追问尖锐、追究边界 case、压力较大 |
| pressure      | 连珠追问、质疑回答、模拟压力面 |

两者注入 system prompt 的人设段，**贯穿全程保持一致**。例：`senior + friendly` = 深度问题但语气温和。

### 4.7 Phase 退出条件（adaptive）

不是问够 budget 题就走，而是 OR：

```
phase 结束:
  ① target_refs must-cover 全部覆盖
  ② 已问题数 ≥ question_budget
  ③ 连续 2 题答得很好且 > budget*0.6  → 提前推进
  ④ 连续 2 题答得很差                  → 跳出避免折磨
```

让面试有真实节奏感 —— 强候选人不被低水平问题烦扰，弱候选人不被反复打击。

### 4.8 反向提问特殊处理

`reverse_qa` 阶段角色反转：

- AI 不再主动出问题，等用户提问
- 引用 JD 的 responsibilities 回答团队/职责类
- 薪资/福利类给合理但模糊回答（真面试官不承诺）
- 触发条件：用户输入是问句

### 4.9 防御性约束（写进 system prompt）

- ❌ 除八股配额外，不允许无 `grounding_refs` 的问题
- ❌ topic 相似度去重，已问过的不重问
- ❌ behavioral 阶段不出纯技术问题（反之亦然）
- ❌ 反向提问阶段 AI 不主动发问
- ✅ 严格 JSON schema 输出，违例自动重试 1 次

### 4.10 UX 细节

| 场景 | 做法 |
|------|------|
| 思考时间 | 不强制；输入框聚焦后才计时（仅展示） |
| 主动结束 | "提前结束面试"按钮 → 跳过剩余 phase 直接 finish |
| 追问透明 | UI 把追问题缩进/换色，让用户知道这是同主题深挖 |
| 阶段过渡 | 切 phase 时 AI 主动说"接下来想聊聊..." |
| 卡壳兜底 | 用户连续"不知道"→ 给提示性追问降低难度 |
| 中途断线 | `GET /mock-interview/in-progress` 检测 → 恢复弹窗 |

---

## 5. 语音方案（P0 落地）

**确定方案**：浏览器原生（Web Speech API + edge-tts）。**默认模式：hybrid**（面试官 TTS + 用户自由切换打字/语音）。

### 5.1 架构

```
┌─ Frontend ─────────────────────────────────────────┐
│  MediaRecorder (Opus chunks)                       │
│       │                                            │
│       ▼                                            │
│  Web Speech API (浏览器内 STT)                     │
│       │  partial transcript → 实时显示             │
│       │  final → 提交                              │
│       ▼                                            │
│  POST /mock-interview/answer                       │
│                                                    │
│  ◄── SSE / WS：question token stream               │
│       │                                            │
│       ├─ 文字 token → 打字机                       │
│       └─ 按句切分 → /tts/speak → MP3 chunk → 播放  │
└────────────────────────────────────────────────────┘

┌─ Backend ──────────────────────────────────────────┐
│  /mock-interview/answer  : 不变（接收文字）        │
│  /tts/speak (POST)       : body {text}             │
│                             → edge-tts 调用        │
│                             → 流式回 audio/mpeg    │
└────────────────────────────────────────────────────┘
```

**关键设计**：
- **STT 在前端**：Web Speech API 不走后端，零成本零延迟。Chrome/Edge 原生支持。
- **TTS 走后端**：用 edge-tts (Python 包) 调用微软免费端点。后端做一层代理 + 缓存，避免前端跨域和 key 暴露问题。
- **句级流式 TTS**：LLM token 流出时，按 `。？！\n` 切句，每句独立调 TTS。首句音频感知延迟 < 1s。
- **字幕同步**：前端文字打字机 + 当前播放句子高亮。不做精确词级时间戳，简单可靠。

### 5.2 后端新端点

```
POST /tts/speak
  body: { text: string, voice?: string }    # voice 默认 zh-CN-XiaoxiaoNeural
  response: Content-Type: audio/mpeg, 流式 chunks
```

实现位置：`backend/app/api/voice/tts.py`。
内部用 `edge-tts` Python 包（pip install edge-tts），无需注册任何账号。
**简单缓存**：相同 `(text, voice)` 哈希到 S3，5 分钟内重复请求复用。

### 5.3 前端组件

```
frontend/src/components/voice/
  ├─ MicButton.tsx           ← 按住说话 / 点击切换长按模式
  ├─ TtsPlayer.tsx           ← 接收 MP3 stream，Web Audio API 播放
  ├─ SubtitleTrack.tsx       ← 文字打字机 + 当前句高亮
  └─ useSpeechRecognition.ts ← Web Speech API 封装
```

MockLive 内组合：
```
┌──────────────────────────────────────────┐
│  [面试官头像]  [SubtitleTrack: 当前问题]  │  ← 字幕 + 自动 TTS 播放
│                                          │
│  [TtsPlayer 控制条：暂停/重听]            │
│                                          │
│  ──────────────────────────────────       │
│                                          │
│  [输入框: 打字]   或   [MicButton 按住说]  │  ← 用户切换
│                                          │
└──────────────────────────────────────────┘
```

### 5.4 浏览器兼容降级

- Chrome / Edge：STT + TTS 全功能
- Safari / Firefox：Web Speech API 不可用 → 自动退化为文字模式，前端给 toast 提示

### 5.5 不在 P0 范围

- VAD（声音端点自动检测）：先用"按住说话"
- 用户原始音频上传归档：DB 字段预留，前端不传
- 中断打断面试官：先不做
- 火山引擎等付费方案：留待 P1+

---

## 6. API 重构

### 6.1 删除/废弃

| 端点 | 处理 |
|------|------|
| `POST /analyze` (老) | 删除，迁到 `POST /interview-records` |
| `GET /analyze/{id}/events` (老) | 删除，迁到 `GET /interview-records/{id}/events` |
| `POST /chat/mock-interview/finish` 内的 `batch_evaluate` | 删除，改异步 dispatch orchestrator |
| `POST /chat/mock-interview/parse-jd` | 替换为 `POST /uploads/jd-ephemeral` |

### 4.2 新端点

```
# 资料库（可选简历入口）
GET  /me/resumes                    -> 资料库中所有 doc_type='resume' 的文档

# 即时上传（mock 和 upload 共用同一组件）
POST /uploads/resume-direct         -> body: file -> {upload_id, parsed_text}
POST /uploads/jd-ephemeral          -> body: file or text -> {upload_id, text}

# 面试记录（统一）
POST /interview-records             -> 创建 upload 类记录并 dispatch 分析
GET  /interview-records             -> 列表（mock + upload 混合）
GET  /interview-records/{id}        -> 详情（含 qa 数组）
GET  /interview-records/{id}/events -> SSE 进度
DELETE /interview-records/{id}

# Mock 流程
POST /chat/mock-interview/start    -> 见 §4.3
POST /chat/mock-interview/answer   -> 推进 plan（基本不变）
POST /chat/mock-interview/finish   -> 异步 dispatch；立即返回 {record_id}
```

### 4.3 Mock Start 请求形状

```typescript
POST /chat/mock-interview/start
{
  "resume_source": {
    "type": "upload" | "library",
    "upload_id"?: string,          // type=upload 时（先调 /uploads/resume-direct 拿到）
    "doc_id"?: string              // type=library 时
  },
  "jd": {
    "upload_id": string            // 先调 /uploads/jd-ephemeral 拿到
  },
  "job_role"?: string,
  "title"?: string
}

Response:
{
  "record_id": "irec_xxx",
  "session_id": "cs_xxx",
  "first_question": "...",
  "plan_summary": [...]
}
```

服务端在 start 时：
1. 解析简历/JD 正文 → 写入 `InterviewRecord.resume_text_snapshot / jd_text_snapshot`
2. `generate_plan()` → `InterviewRecord.interview_plan_json`
3. 创建 `ChatSession(session_type='mock_interview', interview_record_id=irec_xxx)`
4. 返回首问

---

## 5. 前端重构

### 5.1 MockSetup 重设计

```
[简历]
  ● 上传新的简历       [拖拽/选择文件]   ← 默认选中
  ○ 从资料库选择       [下拉列表]
[JD]
  [拖拽 PDF / 粘贴 JD 文本]              ← 必填
[职位名]（可选）：[___]
[开始面试]
```

- 上传简历调 `POST /uploads/resume-direct`
- 上传 JD 调 `POST /uploads/jd-ephemeral`
- 资料库选项调 `GET /me/resumes`
- 点击"开始面试"调 `POST /chat/mock-interview/start`，跳 MockLive

### 5.2 MockLive

- finish 调用返回 `{record_id, status: 'analyzing'}`
- 立刻 `navigate('/review?id=' + record_id)`
- 复盘页 SSE 显示进度

### 5.3 ReviewPage 统一渲染

- 不再区分 mock / upload 分支
- 数据源：`GET /interview-records/{id}` 返回 `record + qa_list`
- Tabs：
  - **原始文稿**：upload 显示 ASR 文本 + 时间戳；mock 显示 Q&A 拼接 + plan 概览
  - **逐题**：渲染 `qa_list`（统一形状）
  - **总结**：渲染 `analysis_json.overall + phase_summary`
- **进度态**：`record.status != 'completed'` → 显示 `AnalysisRunner`（SSE）；完成后自动切换到结果视图
- SessionList 状态色（你已设计好的部分）继续使用 `InterviewRecord.status`

### 5.4 ChatPanel（debrief）

`build_interview_reference()` 改为从 `InterviewRecord + InterviewQA` 拼装注入。接口 schema 不变。

---

## 6. 数据迁移

### 6.1 Alembic 迁移概要

```python
def upgrade():
    # 1. 创建 interview_qa
    op.create_table('interview_qa', ...)

    # 2. interview_records 加新字段
    op.add_column('interview_records', sa.Column('resume_text_snapshot', sa.Text(), nullable=True))
    op.add_column('interview_records', sa.Column('jd_text_snapshot', sa.Text(), nullable=True))
    op.add_column('interview_records', sa.Column('transcript_segments_json', sa.JSON(), nullable=True))
    op.add_column('interview_records', sa.Column('analysis_schema_version', sa.Integer(), server_default='2'))
    op.add_column('interview_records', sa.Column('celery_task_id', sa.String(), nullable=True))
    op.add_column('interview_records', sa.Column('error_message', sa.Text(), nullable=True))

    # 3. 数据迁移（Python 脚本，处理 JSON 字段）
    #    a) 老 Interview/Transcript/AnalysisResult → InterviewRecord(source='upload') + InterviewQA
    #    b) 现 InterviewRecord 中 mock 数据：解 analysis_json.qa_history → InterviewQA 行
    #       analysis_json 改为新 schema (v2)，只保留 overall/phase_summary
    #    c) NOT NULL 字段：补 snapshot（从老的 transcript / analysis 推算）

    # 4. 删除老表（同一迁移内）
    op.drop_table('analysis_results')
    op.drop_table('transcripts')
    op.drop_table('interviews')

def downgrade():
    raise NotImplementedError  # 有损迁移，不支持回滚
```

### 6.2 校验清单

- [ ] 备份生产 DB（pg_dump）
- [ ] staging 跑迁移，对比迁移前后总记录数
- [ ] 随机抽 5 条老 Interview → 在 InterviewRecord 查到 → 字段正确
- [ ] mock InterviewRecord 拆出的 qa 行数 = 原 `qa_history` 长度
- [ ] 删表前再单独 dump 三张老表保留 30 天

---

## 7. 实施计划

| PR | 内容 | 影响面 | 验证 |
|----|------|--------|------|
| **#1** | DB schema + 数据迁移 | backend models, alembic | staging 跑迁移 + 校验 |
| **#2** | `InterviewAnalysisOrchestrator` 抽象，upload 路径迁过去（行为不变） | services, worker | upload 端到端跑通，结果等价 |
| **#3** | Mock finish 改异步走 orchestrator；新 `analysis_json` v2 schema；删 `batch_evaluate` | mock_interview, schemas | mock 端到端跑通 |
| **#4** | 统一 ReviewPage 渲染；MockSetup 重设计；JD/简历直传端点 | frontend pages/review, pages/mock | UI 手测 |
| **#5** | 清理：老端点、duck-type 分支、未引用代码 | cleanup | 全量 grep 无引用 |

每个 PR 可独立部署、独立回滚（除 #1 的数据迁移）。

---

## 8. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 数据迁移丢数据 | 备份 + staging 演练 + 老表 dump 保留 30 天 |
| Mock 异步后用户等待 30-60s | SSE 进度 + SessionList 状态色，体验和 upload 对齐 |
| 滑动窗口 prompt 设计错 → 评分质量下降 | 抽 20 个历史 mock 跑新旧 pipeline 评分一致性对比 |
| 老 `/analyze` 删除后旧前端崩溃 | 前后端同 release；保留 410 Gone 提示一周 |
| JD ephemeral upload 占空间 | 定期清理：`purpose='interview_jd_ephemeral' & status='archived' & age > 30d` 物理删除 |
| DeepSeek V4 Flash 输出 JSON 不稳定 | strict json mode + 重试 1 次 + 单题回退兜底 |

---

## 9. 已确认的关键决策

| 决策点 | 决定 |
|--------|------|
| LLM 模型 | DeepSeek V4 Flash（贯穿全流程：QA 抽取 / 逐题分析 / 全局综合） |
| 批量大小 | `batch_size = 2` |
| 滑动窗口 | 前置上下文 3 题 + 后置上下文 2 题 |
| 通知方式 | 仅前端通知（沿用现有 SessionList 状态展示），不发邮件 |
| Phase 枚举 | 不做强枚举，LLM 根据上下文判断，DB 存字符串；未来岗位模板再规范化（用户无感升级） |
| 简历入口 | 默认即时上传；用户可改为"从资料库选" |
| JD 入口 | 仅即时上传，不入资料库 |
| 老表处理 | 写迁移脚本后删表（同迁移内） |

---

## 10. 开放问题

- [x] DeepSeek V4 Flash 上下文窗口：1M，足够，简历/JD 无需摘要化
- [x] 在 `InterviewRecord` 加 `analyzed_qa_count INT DEFAULT 0` 聚合字段，每完成一题 +1，SSE 推送细粒度进度
- [ ] `ChatSession` 在 mock 结束后是软删还是保留？
- [ ] Mock 中途用户关闭页面的恢复策略

---

## 11. 术语对照

| 旧术语 | 新术语 |
|--------|--------|
| `Interview` 表 | `InterviewRecord(source='upload')` |
| `Transcript` 表 | `InterviewRecord.raw_transcript` + `transcript_segments_json` |
| `AnalysisResult.per_question` | `InterviewQA` 表 |
| `analysis_json.qa_history` (mock) | `InterviewQA` 表 |
| `analysis_json.per_question` (upload) | `InterviewQA` 表 |
| `batch_evaluate()` | `InterviewAnalysisOrchestrator._analyze_questions_sliding()` |
| `parse-jd` 端点 | `POST /uploads/jd-ephemeral` |
| MockSetup 选简历 | `POST /uploads/resume-direct` 默认 + 可选 `GET /me/resumes` 资料库分支 |
