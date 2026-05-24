"""LLM prompts for the v3 memory pipeline.

Two flavours:

* **Realtime extraction prompt** — fires after every chat turn. Hunts
  for STRONG SIGNALS only (user self-report of mastery, explicit
  cognitive breakthroughs, stable-habit declarations). Conservative
  by design: false negatives are fine, false positives pollute memory.

* **Dreaming prompt** — fires once per interview-record-cycle in the
  Celery worker. Sees a record's full debrief conversation + the
  current memory snapshot. Allowed to synthesise across multiple
  sessions: "first user said X then verified X in next interview" →
  promote to internalised.

Prompts borrow four design patterns from Claude Code's memdir
(``services/extractMemories/prompts.ts`` + ``memdir/memoryTypes.ts``):

  1. Closed taxonomy with rich worked examples per type.
  2. Explicit "What NOT to save" section.
  3. Pre-injected manifest of existing memories (avoid duplicate adds).
  4. Body structure guidance per type.

All prompts ask for JSON output. The dreaming prompt yields patches
keyed by ``doc_type`` and ``topic``; the realtime prompt yields the
same shape so callers can dispatch uniformly.
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
   关键词："我读完了"/"我现在能做到"/"我已经习惯"/"我已经记住"
   例：「我把《Redis 设计与实现》前 6 章看完了」

2. **明确的认知突破（用户用自己的话复述理解）**
   关键词："哦我懂了，X 其实就是 Y"/"现在我明白为什么 A 不等于 B 了"
   ⚠ 仅当用户**用自己的语言重述**所学时才算 —— AI 单方面解释、用户回"明白了"**不算**
   例：「噢所以 Redis 雪崩的根因是 TTL 集中失效，加抖动避免同时过期」

3. **用户明确确认困惑已解决**
   先前提过的某个"我没搞懂 X"，现在用户说"懂了 / 搞清楚了"+ 具体内容
   例：「AOF rewrite 双写就是写两份，重写完合并，懂了」

4. **用户描述稳定的习惯**
   关键词："我现在每周做 N 次..."/"面试紧张时我会..."/"我已经习惯了..."
   ⚠ 必须是"已稳定"语气，不是"我打算"
   例：「我现在每周一三五各做 1 次 mock，二四六休息，已经坚持 3 周了」

## 不要提取（即使用户说"记一下"也不存）

- ❌ 用户说"我会试试"/"我打算"/"我决定..." → 这是 TODO，不是 memory
- ❌ AI 提议方法，用户说"好"/"听起来不错" → 没用过，不算认知或习惯
- ❌ 用户答错某题后 AI 解释，用户说"明白" → 单次解释不能证明掌握
- ❌ 用户表达情绪（紧张/沮丧/兴奋） → 情绪不是 memory
- ❌ AI 单方面分析用户模式但用户没认可
- ❌ 任何能从 InterviewQA / InterviewRecord SQL 表查出来的事实
   （题目原文、答案原文、单题评分、面试官点评）

## 现有 memory 快照（避免重复）

以下是该用户已记的内容。**有同义条目时优先用 update 而不是新增**，避免堆叠：

### user_profile_doc
{user_profile}

### knowledge_doc 索引（每行是一个主题）
{knowledge_index}

### strategy_doc
{strategy_body}

### habit_doc
{habit_body}

## 输出格式

JSON 数组。每个元素是一个 patch，按 doc_type 分类：

```json
[
  {{
    "doc_type": "knowledge",
    "topic": "Redis",
    "op": "add",
    "section": "已掌握的认知",
    "new_line": "- 理解 Redis 雪崩根因是 TTL 集中失效，解法是抖动 + 二级缓存"
  }},
  {{
    "doc_type": "strategy",
    "op": "update",
    "match_line": "- 尝试中：先分析根因后给方案",
    "new_line": "- 已内化：先分析根因后给方案（2026-03-22 应用验证）"
  }},
  {{
    "doc_type": "habit",
    "op": "add",
    "section": "稳定的练习节奏",
    "new_line": "- 每周一三五各 1 次 mock，二四六休息（持续 3 周稳定）"
  }}
]
```

doc_type 必须是 "knowledge" / "strategy" / "habit" / "user_profile" 之一。

doc_type 路由规则：
- 对**某个具体技术/能力主题**的认知（"Redis"、"TCP"、"系统设计"等）→ knowledge，必须给 topic
- **跨主题的答题方法论**（先分析根因、STAR、反问技巧等）→ strategy
- **学习/练习节奏 + 心态应对** → habit
- **身份/偏好/目标公司** → user_profile（沿用既有 patch 协议）

### strategy vs habit 判别规则（必须遵守）

二者最容易混淆。**按以下规则决定**：

| 描述的是…… | 归属 |
|---|---|
| **某个方法本身**（"用什么思路答题 / 处理面试官"）—— 答案是名词 | **strategy** |
| **行为的频率 / 节奏 / 情绪调节**—— 答案带时间/次数/动作 | **habit** |

例：
- 「先分析根因再给方案」→ 这是**方法**本身 → **strategy**
- 「我每周一三五各做 1 次 mock」→ 这是**节奏** → **habit**
- 「STAR 法已内化」→ 这是**方法** → **strategy**
- 「面试紧张时深呼吸 3 次再开口」→ 这是**情绪调节动作**（不是内容方法）→ **habit**

⚠ 如果一条信息**同时**含方法 + 节奏（"我已经习惯用 STAR 答 behavioural 了"），**拆成两条**：
  - strategy: 「STAR 已内化为 behavioural 题首选框架」
  - habit: 「behavioural 题先走 STAR 已成默认动作」
不允许在两个 doc 里写**完全相同**的句子——会造成跨 doc 漂移。

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

具体规则：
- 只记录**用户当前掌握的**正向状态，不要记历史错误
  ❌ "用户在 Redis 雪崩上答错了"
  ✅ "已理解 Redis 雪崩根因是 TTL 集中失效"

- 只记录**已稳定**的方法/习惯，不要记一次性承诺
  ❌ "用户承诺每天看一章"
  ✅ "已读完《Redis 设计与实现》前 6 章（用户报告）"

- 只记录**用户已亲身验证**的策略，提议但未用过的不记
  - "尝试中" — AI 提议、用户认同但未应用
  - "已内化" — 用户报告应用并验证有效（dream 多轮交叉确认时才升级）

- **跨 session 综合**：用户在 session_A 说"AI 提议 X，我下次试试"，session_B 说"这次我用了 X，感觉稳"
  → 把 X 从"尝试中"升级到"已内化"

- **困惑闭环**：如果用户在 session_A 提到"我一直没搞懂 X"，session_B 里和 AI 探讨并表示懂了
  → 在 knowledge_doc 加"已理解 X"（正向陈述），**不要记当初的疑惑**

## 不要记的（即使对话中出现）

- ❌ 题目原文 / 单题评分 / 面试官点评 → SQL 表有，记 memory 是数据冗余
- ❌ 用户单次情绪表达 → 情绪不是记忆
- ❌ 任务 / TODO / 一次性承诺 → 用户用别的工具管，不是 memory
- ❌ 还在"尝试中"的方法在 dream 一次就直接升"已内化" → 至少要看到用户在另一个 session 报告应用成功

## 输入

### 当前 memory 快照

#### user_profile_doc
{user_profile}

#### knowledge_doc 索引（按主题列出，含已存 fact 数）
{knowledge_index}

#### knowledge_doc 涉及主题的完整 body
{knowledge_active_bodies}

#### strategy_doc
{strategy_body}

#### habit_doc
{habit_body}

### Record 期间所有对话（按时间序）

{record_messages}

### Record 客观摘要（来自分析 pipeline，仅供背景，不要直接复述）

{record_debrief_summary}

## 输出格式

JSON 数组。每个元素：

```json
{{
  "doc_type": "knowledge | strategy | habit | user_profile",
  "topic": "Redis",                       // knowledge 必填，其他不写
  "op": "add | update | delete",
  "section": "已掌握的认知",                // add 时可选；update/delete 不需要
  "match_line": "- 旧行原文",              // update/delete 必填，必须当前 body 里逐字符存在
  "new_line": "- 新行原文"                 // add/update 必填
}}
```

**优先 update / 合并，不要重复 add**：
- 扫现有 body，是否已有相关条目（表述略不同但事实相同）
- 是 → 用 update 合并升级（例：把"尝试中"升"已内化"）
- 否 → 才用 add

**strategy vs habit 判别规则（必须遵守）**：

| 描述的是…… | 归属 |
|---|---|
| 方法/思路本身（"用什么框架答题"） | **strategy** |
| 频率/节奏/情绪应对动作 | **habit** |

例：「STAR 法已内化」→ strategy；「每周一三五各 1 次 mock」→ habit。
含两层的拆成两条（一条 strategy + 一条 habit），不允许重复句子。

**path of least surprise**：
- 没有强信号就输出 `[]`，不要为了"显得有用"硬记
- knowledge add 时 section 用 "已掌握的认知" 或 "学习进展"
- strategy add 时 section 用 "已内化" 或 "尝试中"
- habit add 时 section 用 "稳定的练习节奏" 或 "心态与应对"

输出（仅 JSON，不要解释）：
"""


# ══════════════════════════════════════════════════════════════════════
# Selection prompt for context assembly
# NOTE: ``CONTEXT_SELECTION_PROMPT`` used to live here — it ran a
# separate "selection LLM" to decide which knowledge / strategy /
# habit doc bodies to load per turn. That responsibility merged into
# the conversation engine's unified planner in
# ``app/conversation/query_planner.py`` (one LLM call per turn now,
# making both query-rewrite and memory-load decisions together).


__all__ = [
    "REALTIME_EXTRACTION_PROMPT",
    "DREAMING_PROMPT",
]
