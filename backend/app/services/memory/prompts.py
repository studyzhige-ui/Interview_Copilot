"""LLM prompts for the v3 memory pipeline.

Two flavours:

* **Realtime extraction prompt** — fires after every chat turn. Hunts for
  STRONG SIGNALS only (user self-report of mastery, explicit cognitive
  breakthroughs, stable-habit declarations). Conservative by design: false
  negatives are fine, false positives pollute memory.

* **Dreaming prompt** — fires once per interview-record-cycle in the Celery
  worker. Sees a record's full debrief conversation + the current memory
  snapshot. Allowed to synthesise across multiple sessions.

Both prompts emit a single JSON array whose elements are routed by a ``target``
field to one of the three Memory write surfaces:

* ``ability_state``     — per-topic mastery (memory_ability_states): a structured
                          upsert (topic / skill_type / mastery_level / summary).
* ``user_profile``      — global identity/preferences doc (memory_documents): a
                          markdown line patch.
* ``learning_strategy`` — global answering/review/training-method doc
                          (memory_documents): a markdown line patch.

There is no ``knowledge`` or ``habit`` type — topic mastery is an ability state,
and habits fold into ``user_profile`` (behaviour traits) or ``learning_strategy``
(training methods).
"""

from __future__ import annotations


# ══════════════════════════════════════════════════════════════════════
# Realtime extraction prompt
# ══════════════════════════════════════════════════════════════════════
#
# Used by post_turn_maintenance after every chat turn. Should be CHEAP
# (no big context) and CONSERVATIVE (skip ambiguous signals; dreaming
# will catch those later with cross-session synthesis).

REALTIME_EXTRACTION_PROMPT = """你是面试辅助系统的实时记忆抽取助手。

你的任务：扫描下面这段最新对话（用户与 AI 之间），识别"**强信号**"——只有满足以下任一条件才提取：

1. **用户主动报告"已掌握 / 已完成 / 已养成"**
   例：「我把《Redis 设计与实现》前 6 章看完了」「我现在能独立推导快排了」

2. **明确的认知突破（用户用自己的话复述理解）**
   ⚠ 仅当用户**用自己的语言重述**所学时才算 —— AI 单方面解释、用户回"明白了"**不算**
   例：「噢所以 Redis 雪崩的根因是 TTL 集中失效，加抖动避免同时过期」

3. **用户明确确认困惑已解决**（"懂了 / 搞清楚了" + 具体内容）

4. **用户描述稳定的答题方法或练习习惯**
   ⚠ 必须是"已稳定 / 已内化"语气，不是"我打算"
   例：「我现在答 behavioral 题已经习惯先走 STAR 框架了」

## 不要提取（即使用户说"记一下"也不存）

- ❌ "我会试试" / "我打算" / "我决定" → 这是 TODO，不是 memory
- ❌ AI 提议方法、用户只回"好" → 没用过，不算
- ❌ 用户答错后 AI 解释、用户说"明白" → 单次解释不能证明掌握
- ❌ 情绪表达（紧张/沮丧/兴奋）→ 情绪不是 memory
- ❌ 任何能从 InterviewQA / InterviewRecord SQL 表查出来的事实（题目原文、答案原文、单题评分、面试官点评）

## 现有 memory 快照（避免重复）

### 用户画像 user_profile
{user_profile}

### 学习策略 learning_strategy
{learning_strategy}

### 能力状态索引（每行一个主题）
{ability_index}

## 输出格式

JSON 数组。每个元素带 `target` 字段，分三类：

```json
[
  {{
    "target": "ability_state",
    "topic": "Redis 缓存穿透",
    "skill_type": "knowledge_topic",
    "mastery_level": "improving",
    "summary": "理解了缓存穿透要用布隆过滤器或空值缓存兜底"
  }},
  {{
    "target": "learning_strategy",
    "op": "add",
    "section": "答题方法",
    "new_line": "- 先分析根因再给方案，已成默认答题习惯"
  }},
  {{
    "target": "user_profile",
    "op": "add",
    "new_line": "- 目标公司：字节跳动后端"
  }}
]
```

字段规则：
- `target` 必须是 "ability_state" / "user_profile" / "learning_strategy" 之一。
- **ability_state**（某个具体技术/能力主题的掌握情况）：
  - `topic` 必填，主题名（如 "Redis 缓存穿透"、"MySQL 索引"、"行为面试"）。
  - `skill_type` 必填，取值："knowledge_topic"（技术知识点）/ "system_design"（系统设计）/ "behavioral"（行为面试）/ "communication"（沟通表达）/ "project_deep_dive"（项目深挖）。
  - `mastery_level` 必填，取值："weak" / "improving" / "stable" / "strong"。
  - `summary` 必填，一句话描述用户当前状态和主要问题（**正向当前态**，不记历史错误）。
  - 同一主题已存在时，直接用最新状态覆盖（系统按 topic+skill_type upsert）。
- **user_profile / learning_strategy**（markdown 行补丁，沿用补丁协议）：
  - `op`："add" / "update" / "delete"。
  - `section`：可选 ## 小节名；`match_line`：update/delete 必填（须逐字符存在）；`new_line`：add/update 必填。
  - 路由：身份/偏好/目标/表达特点/稳定行为倾向 → user_profile；答题方法/复盘方法/训练节奏 → learning_strategy。

**有同义条目时优先 update / upsert，不要堆叠重复。**

如果这段对话**没有**任何强信号，输出空数组 `[]`。

## 当前对话内容

{conversation}

输出（仅 JSON，不要解释）：
"""


# ══════════════════════════════════════════════════════════════════════
# Dreaming prompt
# ══════════════════════════════════════════════════════════════════════
#
# Fired by the Celery dreaming worker once per (interview_record, dream).
# Sees the FULL record-period conversation + current snapshot. Allowed
# to synthesise across messages a single-turn extraction couldn't see.

DREAMING_PROMPT = """你是面试辅助系统的"夜间记忆整理助手"。

你的任务：综合 record `{record_id}` 期间用户的所有复盘对话 + 当前记忆快照，找出**真正稳定且新出现**的认知/方法/习惯，更新长期记忆。

## 核心原则

**记忆 = 用户认知 / 方法 / 习惯的当前快照**。不是事件日志，不是 QA 复述。

- 只记录**用户当前掌握的**正向状态，不要记历史错误
  ✅ ability_state summary："已理解 Redis 雪崩根因是 TTL 集中失效"
- 只记录**已稳定**的方法/习惯，不记一次性承诺
- **跨 session 综合**：用户在 session_A 说"AI 提议 X，下次试试"，session_B 说"这次用了 X，感觉稳"
  → 把对应能力 mastery 升级（improving → stable），或把方法写入 learning_strategy
- **困惑闭环**：用户先前"没搞懂 X"，后来探讨并表示懂了 → 写正向能力状态，**不记当初的疑惑**

## 不要记的

- ❌ 题目原文 / 单题评分 / 面试官点评 → SQL 表有，记 memory 是数据冗余
- ❌ 单次情绪表达 / TODO / 一次性承诺
- ❌ 还在"尝试中"的方法，仅凭一次对话就升为"已稳定掌握"

## 输入

### 当前 memory 快照

#### 用户画像 user_profile
{user_profile}

#### 学习策略 learning_strategy
{learning_strategy}

#### 能力状态索引（主题 | 掌握度 | 摘要）
{ability_index}

### Record 期间所有对话（按时间序）

{record_messages}

### Record 客观摘要（来自分析 pipeline，仅供背景，不要直接复述）

{record_debrief_summary}

## 输出格式

JSON 数组，元素带 `target` 字段（与实时抽取同一协议）：

```json
[
  {{
    "target": "ability_state",
    "topic": "Redis 缓存穿透",
    "skill_type": "knowledge_topic",
    "mastery_level": "stable",
    "summary": "多轮复盘后能稳定说清穿透/雪崩/击穿的区别与兜底方案"
  }},
  {{
    "target": "learning_strategy",
    "op": "update",
    "match_line": "- 尝试中：先分析根因后给方案",
    "new_line": "- 已内化：先分析根因后给方案（多次面试验证）"
  }}
]
```

字段规则与实时抽取相同：
- `target`：ability_state / user_profile / learning_strategy。
- ability_state：topic + skill_type(knowledge_topic/system_design/behavioral/communication/project_deep_dive) + mastery_level(weak/improving/stable/strong) + summary 全部必填。
- user_profile / learning_strategy：markdown 行补丁（op/section/match_line/new_line）。
- **退役能力条目**（仅 dreaming 有此权限）：当某条目明显过时——尤其是标注了
  「距上次证据 N 天」且 N 很大、内容已被新条目覆盖、或用户已不再涉及该方向——
  输出 `{{"target": "ability_state", "op": "archive", "topic": "...", "skill_type": "..."}}`
  将其归档。能力账本应该随用户成长呼吸，不是只增不减的清单。
- 对于「距上次证据」很久的 weak 条目：若本次记录提供了新证据，正常 upsert 刷新；
  若毫无新证据且已超过约 60 天，考虑 archive 或在 summary 里标注陈旧。

**优先 update / upsert，不要重复 add。** 没有强信号就输出 `[]`。

输出（仅 JSON，不要解释）：
"""


# ══════════════════════════════════════════════════════════════════════
# Memory-doc compaction rewrite (MEM-5)
# ══════════════════════════════════════════════════════════════════════
# Fired by the dreaming worker when a doc exceeds the size ceiling. Full
# before/after lands in the audit trail (change_type=compaction_rewrite),
# so an over-aggressive rewrite is revertible.

DOC_COMPACT_PROMPT = """[硬性约束] 全部输出使用简体中文。

下面是一位用户的「{doc_label}」记忆文档，它已经超过了大小上限（当前 {line_count} 行 / {char_count} 字符）。
请把它**压缩重写**为一份不超过 {max_lines} 行的精炼版本：

规则：
1. 保留所有仍然有效的事实与偏好；合并同义/重复的条目；删除明显过时或已被后文覆盖的内容。
2. 保持原有的 markdown 结构风格（## 小节 + 列表行）。
3. 不要发明原文没有的信息；不确定是否过时的内容保守保留。
4. 输出**只有重写后的文档全文**，不要任何解释。

═════════ 原文 ═════════
{body}

重写后的文档：
"""

__all__ = [
    "REALTIME_EXTRACTION_PROMPT",
    "DREAMING_PROMPT",
    "DOC_COMPACT_PROMPT",
]
