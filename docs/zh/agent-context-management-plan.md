# Agent 上下文管理 — 改进方案（定稿）

> 临时工作文档，改造完成后删除，不维护英文版。
> **贯穿不变量**：所有 `tool_call` ↔ `tool_result` 用 `tool_call_id` 严格配对（不靠 FIFO 顺序）——多次调用同一工具，每个结果也能对应到那一次调用。

---

## 1. 目标与现状问题

**目标**：把上下文压缩重写成**一套统一的机制**——廉价预处理对齐 **Hermes**、全量摘要对齐 **Claude**——保证「单 query 内大量工具调用」和「多轮对话」两种情况下，最终都能给出对当前 query 的合理回答；且适配你们的技术栈（标准 OpenAI 兼容 API + **前缀缓存**，**无** Anthropic `cache_edits` 块缓存）。

**现状要修的问题**：
1. 实现散在多文件、三处分别调（`pre_llm_compact` / `is_at_blocking_limit` / `on_context_too_long`）。
2. Hermes/Claude 两套设计杂糅，注释堆术语、一半层级标 N/A；遗留 `AgentLoopContext` 类。
3. 没有真 LLM 摘要（autocompact 标 future、从未实现）。
4. 现有 3-pass 两个毛病：**Pass 2 摘要拿不到调用参数**（常 `query=?`、没信息量）、**Pass 1 去重只哈希前 200 字符**（开头相同的长结果误删、丢数据）。
5. token 计数不一致（阈值用真实 usage，内部估算却用 `chars/2.5`）。
6. `read_file` 硬截断 20k 字符、无分段——读不到后面。
7. 外层多轮用固定计数急压（6k/4/15 轮）：过早丢保真、不吃窗口、不随模型缩放。
8. 多维硬预算（步数 25 / 时间 180s），时间维度尤其武断。

---

## 1.5 现状审计修正（实现前对齐 · 2026-06-03）

对照现有代码做了一次完整审计，方案里若干"新增"其实**已存在**，据此修正（避免重复造轮子、确保删旧不删错）：

1. **Stage A 已完整实现**（`tool_result_storage.py`：`maybe_persist_result` / `enforce_turn_budget` / `resolve_threshold` / `generate_preview` / `_NEVER_PERSIST_TOOLS`，有充分单测）。**非新增**——只需**调常量**（单结果 30k→50k、聚合 100k→200k、预览 1500→2000 字节）+ 改预览文案 + Pass 2 跳过已落盘结果。
2. **落盘读不回是真 bug**：落盘文件在 `agent-results/{session}/{tool_call_id}.txt`，但 `read_file` 原本**无 `path` 参数**（只按 upload_id/purpose 查 DB），落盘内容不可恢复。→ **P1 已修**：`read_file` 加 `path`+`offset`/`limit`，并新增 `tool_result_storage.resolve_persisted_path()`（会话内路径约束，防穿越）。
3. **`terminal` 工具不存在**：Pass 2 该补的模板是 `read_file` / `write_file`，不是 `terminal`。
4. **基类 `QueryLoopCompactor` 的 JSON 安全 Pass 3 + token-预算保护尾零测试覆盖**：现有 14 个测试全测 `AgentLoopContext` 重写版（固定计数 + 原始硬截）。删遗留类时**必须补基类等价测试**，否则真正的生产路径失去覆盖。
5. **`get_autocompact_threshold` 名不副实**：现触发的是廉价 3-pass，**不是** LLM 摘要；真正的 L2 内层 LLM 摘要从未实现（仅占位注释）。落地需统一术语（廉价预处理阈值 vs autocompact 阈值）。
6. **窗口常量已对齐**（`context_window.py`：effective / blocking ✓；autocompact buffer 现为 13k，方案选 20k＝config 旋钮）→ **保留**该文件。
7. **`token_count` 已有 tiktoken 版**（`context_assembly_pipeline.count_tokens`）→ **P1 已做**：抽到 `context_manager.token_count` 单一实现，L1 改 re-export（删重复 tokenizer），`chars/2.5` 留待编译器重写时替换。
8. **反应式恢复现状只跑 3-pass**（非强制 autocompact），且 `has_attempted_reactive_compact` 每轮被 `reset_circuit_breaker` 重置（单发语义不严格）→ P3 修。
9. **`CompactionService` 触发方已确认**：`engine._fire_post_turn_maintenance` → `post_turn_maintenance_service.run` → `compaction.compact_if_needed`（后台任务，每轮成功后）→ 写 DB `session_state.summary`。并入 `compress()` 时从这里接。
10. **步数阀 25 / 时间预算 180s 仍生效**（`react_agent.AgentBudget`）→ P2 删时间、放宽步数到 80。

---

## 2. 核心架构：一个 `compress()`，内外统一

**一条完整消息流（含工具历史，落库）+ 一个压缩边界**（= 现有 `compaction_cursor` + `session_state.summary`）。`compress()` 同时服务两个增长来源——单 query 内工具往返、跨 query 多轮对话——只看"总 token 是否逼近窗口"，不分来源。原 `CompactionService`（外层固定计数急压）**并入 `compress()`**，不再是独立机制。

- **Web 应用现实**：每个 query 从 DB 重建消息流；"边界 + 摘要"是跨请求的**持久化桥**（这是和常驻 CLI 的 Claude 唯一的架构差异，且你们已有 `compaction_cursor`/`session_state.summary` 两个字段）。
- **设计取向**：**Phase 1 廉价预处理对齐 Hermes**（它为标准 API + 前缀缓存而生，正合你们约束）；**autocompact 对齐 Claude 全量压缩**（撞窗口一次彻底压成摘要 + 极少尾，前缀大幅缩短、重新缓存）。

---

## 3. 窗口预算（统一基准）

```
effective       = window − min(max_output_tokens, 20_000)   # ✓ Claude 确认
compress() 触发  = total ≥ effective − 20_000                # ⚠ 我们选的 20k；Claude 是 13k
blocking_limit  = effective − 3_000                         # ✓ Claude 确认
```
- **源码核对**：`effective`（输出预留 20k）和 `blocking`（−3k，`MANUAL_COMPACT_BUFFER_TOKENS`）是 Claude 确认值。**autocompact 触发的 buffer，Claude 是 `effective−13_000`**（`AUTOCOMPACT_BUFFER_TOKENS`）；我们选 20k（更保守、早 7k 压），是 config 旋钮，可回调到 13k。
- 触发是**绝对 token 余量**（不是百分比）——余量要能装下"下一个工具结果 + 摘要生成本身"。
- **token 计数**：优先用 API 真实 `usage.prompt_tokens`；调用前/内部估算用 **tiktoken**（抽 `token_count()` 公共工具，删 `chars/2.5`）。

---

## 4. 三道防线（总览）

```
工具执行时(每个结果产出):
   Stage A — 单结果 >50k 字符 → 落盘 + 2KB 预览 + 文件路径(用 Read 分段读回)   ← 按大小, 不动历史

每次调 LLM 前 compress(messages):                  ← 撞 effective−20k 才动
   ① 防抖: 最近 2 次各省 <10% → 跳过(可压的都压完了)
   ② Phase 1 廉价预处理 (零 LLM, 只动"旧"内容, 可短路):
        去重(全哈希) + 旧结果换有信息量摘要(带 args) + 旧参数 JSON 安全截断 + 配对修复
        → 降到阈值下: 直接返回, 不调 LLM
   ③ Phase 3 autocompact (LLM, Claude 全量压缩):
        整段对话 → 一条结构化摘要 + 留最近 1–3 条 → 走编排器重建
   ④ 仍 ≥ effective−3k: Blocking → 转"基于已有结果作答"
```

**核心理念：廉价级联**——能廉价削就别花钱、能保结构就别全局糊。

---

## 5. Stage A — 工具结果落盘（执行时，按大小）

**针对单条超大结果**，在结果**一产生时**就处理（不等它变旧），防止一条就撑爆窗口。

```
单结果 size(content):
   ≤ 50_000 字符        → 原样保留
   > 50_000 字符        → 落盘存全文 + 上下文留 2KB 预览 + 文件路径
单消息内 tool_result 之和 > 200_000 字符(并行工具) → 挑最大的几条落盘
```
- 预览格式：`<persisted-output>\nOutput too large (N). Full output saved to: PATH\n\nPreview (first 2KB):\n...\n</persisted-output>`
- **读回**：模型用 §6 已分段化的 **Read 工具**（offset/limit）读回，**不新增取回工具**。
- **Read 工具自身永不落盘**（落盘再读会循环）——保留在 `_NEVER_PERSIST_TOOLS`。
- **可恢复**：落盘是无损的，全文在存储里、随时按路径读回（区别于 Phase 1/3 的有损摘要）。
- 常量来自 Claude 源码：`DEFAULT_MAX_RESULT_SIZE_CHARS=50_000`、`MAX_TOOL_RESULTS_PER_MESSAGE_CHARS=200_000`、`PREVIEW_SIZE_BYTES=2_000`、`BYTES_PER_TOKEN=4`。
- **代码位置/现状**：`tool_result_storage` **已完整实现** Stage A 三层（见 §1.5）；P2 只调常量 + 文案。读回已在 P1 接通（`read_file` 的 `path` + `resolve_persisted_path`）。

---

## 6. `compress()` —— Phase 1 廉价预处理 + Phase 3 全量摘要

```python
async def compress(messages, budget) -> list[dict]:
    if anti_thrash.should_skip():                         # 防抖
        return messages
    messages = sanitize_tool_pairs(messages)
    if token_count(messages) < effective - 20_000:
        return messages                                   # 没撞阈值, 不动

    messages = cheap_prepass(messages)                    # Phase 1 (零 LLM)
    if token_count(messages) < effective - 20_000:
        return sanitize_tool_pairs(messages)              # 短路: 廉价就够了, 不调 LLM

    if circuit_breaker.ok():
        messages = await autocompact(messages)            # Phase 3 (LLM, Claude 全量)
        if token_count(messages) >= effective - 20_000:
            circuit_breaker.fail()

    if token_count(messages) >= effective - 3_000:        # Blocking
        raise ContextExhausted
    return sanitize_tool_pairs(messages)
```

### 6.1 Phase 1 — 廉价预处理（按 Hermes 重写，零 LLM，可短路）

**只动"保护尾部之前"的旧内容**；最近 ~5 条 tool_result 保持完整（agent 正在用）。三遍 + 配对修复，全在副本上做：

| Pass | 针对 | 做什么 |
|------|------|--------|
| **Pass 1 去重** | 重复结果 | 哈希**完整 content**（非前200字符），相同的只留最新，旧的换占位 |
| **Pass 2 摘要旧输出** | 旧的工具**结果** | 换成一行有信息量摘要，**query/命令/路径从 args 取**（建 `tool_call_id→(name,args)` 索引） |
| **Pass 3 截断旧输入** | 旧的工具**调用参数** | 超长参数 JSON 安全缩短（解析→缩长 string 值/数组留前3→序列化，**保证合法 JSON**） |
| 配对修复 | 孤儿 | 按 `tool_call_id` 删无 call 的 result、给无 result 的 call 补桩 |

**重写要点（修现有两个毛病）**：
- Pass 2 **传 args**（现有 `_summarize_tool_result(name, content)` 拿不到 args → 没信息量）。模板保留并改造现有的 `search_knowledge`/`search_jobs`/`read_interview_history`/`web_search`/`read_url`（改成从 args 取 query），补 `read_file`/`terminal`/`write_file`。
- Pass 1 **哈希完整 content**（现有只哈希前 200 字符 → 误删丢数据）。
- Pass 2 **跳过 Stage A 已落盘的结果**（认 `<persisted-output>` 标记），**保留其文件路径**——否则 agent 没法重读。
- Pass 3 的 JSON 安全截断、配对修复，现有实现 OK，沿用。

**短路**：跑完若已降到阈值下 → 不进 Phase 3（省一次 LLM）。

> **三个 pass 的含义**：Pass 1 删完全重复的；Pass 2 压旧的**工具输出**；Pass 3 压旧的**工具输入**（像 `write_file(content=50KB)` 这种大输入）。Pass 3 必须 JSON 安全——参数是被严格校验的 JSON，按字节硬截会切出坏 JSON → provider 400 → 会话死循环重发。

### 6.2 Phase 3 — autocompact（Claude 式全量压缩，LLM）

- **触发**：Phase 1 短路后仍 `≥ effective − 20_000`。
- **做什么**：把**整段对话**（上次摘要 + 自上次边界以来的全部轮次，经 Phase 1 预处理后）喂给便宜模型（`agent_fast_llm`）压成**一条结构化摘要**，历史替换为 `[摘要] + 最近 1–3 条原始消息`（**必须含最近 user 消息**，否则当前任务被摘走、agent 卡住）。系统提示/工具清单不在压缩范围。**不保护大尾、不只摘中间**——除最近 1–3 条外全进摘要。
- **摘要模板（9 段）**：Primary Request/Intent · Key Concepts · Files · Errors & Fixes · Problem Solving · All User Messages · Pending Tasks · Current Work · Next Step。
- **迭代更新**：有上次摘要就在其上增量更新（保留旧的、加新进展）→ 多次压缩信息不丢。
- **摘要大小**：≤20k 输出预算、由模型决定（无下限）。
- **"仅供参考"前缀** + 结尾 `--- END OF CONTEXT SUMMARY ---`（防模型把摘要里旧任务当新输入；并声明 MEMORY/USER 永远权威）。
- **脱敏**（序列化前 + 产出后各 redact 一次）；**失败兜底**（辅助模型挂→回退主模型→仍失败冷却 + 插静态 fallback，绝不静默丢）；**熔断**（连续 3 次失败停止重试）。
- **压完必重编排**（见 §7）。

### 6.3 错误处理（反应式恢复）+ Blocking + 防抖

`compress()` 是**主动**压缩（覆盖 99%）。但 token 估算可能失准、或上下文实在压不下——必须有**反应式恢复**（对齐 Claude `query.ts` 的多级恢复，**不是**简单"用现有结果作答"）：

**反应式恢复（LLM 调用真报 context 超限时）**：
```
调 LLM → provider 报 context 超限("maximum context length", 400/413):
   1. 先"扣住"错误、不立即抛(withhold)
   2. 强制 autocompact(尾砍到最小 1 条) → 重试这次调用
   3. 单发护栏 has_attempted_reactive_compact: 每次溢出只"压+重试"一次
   4. 熔断: 连续 3 次失败 → 放弃(Claude 教训: 曾有会话连失 50+ 次、每天浪费 ~25 万次调用)
   5. 重试期间绝不跑 stop-hook / 注入(否则 错误→hook→重试→错误 死亡螺旋)
   6. 仍失败 → 抛明确可操作错误、干净退出(不静默丢历史/硬作答):
        "上下文已尽力压缩仍超限，请缩小目标范围或开新会话"
```
- **检测**：匹配各 provider 的超限错误串/状态码（解析 `"N tokens > M maximum"` 抽实际/上限）。
- **错误分型**：纯 token 超限走上面；单条超大输入（Stage A 落盘后仍超）给"开新会话/缩小范围"提示。

**主动 Blocking**（`effective − 3_000`）：仅用于**退化情况**——连 `[摘要 + 最后一条]` 都装不下时，直接抛上面那条明确错误（这种调用必败，省一次 API）。

**防抖（anti-thrashing）**：记每次 `compress()` 省了几 %，**连续 2 次各省 <10% → 跳过**，防无效空转。

> 原则：**绝不在溢出时静默丢历史或硬作答**。要么恢复重试（单发 + 熔断防螺旋），要么给用户明确出口。

### 6.4 为什么先廉价再 LLM（动机）

1. **省钱**：Phase 1 零 LLM；削够了就不调摘要。深 agent 大头是旧工具结果，Phase 1 常能直接搞定。
2. **省延迟**：Phase 1 微秒级；LLM 摘要要等几秒、卡住循环。
3. **保真**：Phase 1 外科手术式、保结构（留"调了什么、什么参数、结果概况"）；LLM 摘要全局有损（揉成散文、丢结构）。能精准削就别全局糊。
4. **更便宜的摘要**：Phase 1 先削小输入 → 真要 LLM 摘要时，那次调用输入也更少。

---

## 7. 压缩后重编排 + 消息排序

压缩（Phase 1/3）不自己手拼 messages，而是产出"压缩后内容"，**交回与 `execute()` 初始化同一个组装函数 `rebuild_messages()` 重建**——保证组装逻辑只有一处、缓存前缀顺序不破。

**消息顺序（按稳定性排，缓存最优）**：
```
[system: SYSTEM_PROMPT]          绝对稳定 ┐
[system: 工具清单 manifest]       绝对稳定 ┤ 追加式稳定前缀
[system: 压缩摘要]                半稳(撞窗口才变) ┤ → 跨轮整段命中前缀缓存
[逐字最近对话轮]                  追加式(只在尾部加新轮) ┘
[grounding(记忆+RAG) 注入在 query 前]  不稳(每轮变) ← 放尾部, 只它+query 不缓存
[user: 当前 query]
```
- **关键**：把每轮都变的 grounding 挪到稳定历史**之后、紧贴 query**，则 `[系统][摘要][逐字历史]` 全是追加式稳定前缀、跨轮命中缓存——**懒压缩不会更贵**。

---

## 8. 全统一持久化（D1）

```
DB: 完整消息流(含 tool_use/tool_result) + compact_boundary(=compaction_cursor) + summary + 落盘引用记录
   │ LOAD          从 DB 重建: [边界前→summary] + [边界后→逐字全量(含工具历史)]
   ▼ ORCHESTRATE   按 §7 顺序装配
   ▼ compress()    撞阈值才压(§6); autocompact 推进 cursor + 持久化 summary
   ▼ RUN           L1 单次调用 / L2 ReAct 循环(循环内每次调 LLM 前也走 compress())
   ▼ PERSIST       完整消息流 + 落盘引用 写回 DB
```

**改动**：
- `transcript_service` 存**完整工具历史**（含 tool_use/tool_result），不只最终答案 blocks。
- 新增**落盘引用记录**（哪些结果落盘 + 预览串），下次 byte-identical 重放 → 保前缀缓存（类比 Claude 的 `ContentReplacementState`）。
- **autocompact 内外是同一个机制、同一份摘要**：装配时（外层，load 的多轮历史太大）与循环中（内层，运行上下文太大）都是同一个 autocompact，把全部上下文**迭代压成一份** `session_state.summary`，经 `[Context Summary]` 槽渲染。区别只在触发时机。
- `session_state.summary + compaction_cursor` 复用为 autocompact 的边界 + 摘要；`CompactionService` 触发从固定计数改为窗口压力、**被 autocompact 取代**（不再是独立的 6 段摘要器；6 段 vs 9 段是伪问题——只有一份摘要、一个模板）。
- **recent_turns 共用**：L1 = user/assistant 文本；agent 链路 = 同样的对话 + 额外的 tool_call/tool_result 消息（D1 的"全量工具历史落库"就是持久化 agent 这部分）。
- **代价**：DB 存量增大（被压缩兜底）；前端聊天记录渲染要能处理完整工具往返（或保留最终答案 blocks 供展示）。这些归 P3。

---

## 9. L2 去掉 RAG（F6）

- **L2 agent**：`engine._prepare` **不再做 RAG 检索注入**；agent 用 `search_knowledge` 工具按需本地检索。
- **L1 聊天保留** `_prepare` 里的 RAG（单次、无工具）。
- 好处：① 简化；② agent 自主检索；③ **grounding 更稳**（RAG 本是 grounding 里每轮变的部分，去掉后稳定前缀更长、更易命中缓存）。

---

## 10. 防死循环（替换多维硬预算）

Claude 默认无硬上限，靠"模型自己产出无工具调用的回复"自然结束。但压缩做好后"上下文天花板"这个天然刹车失效（旧结果被压、永远到不了 blocking），所以保留显式守卫：

- **删除时间预算**（最武断）。
- **步数改宽松安全阀**（~80 迭代），只兜病态跑飞。
- **重复调用软提醒**：同工具名 + 同参数（JSON 归一化后相同）连续调用，**3 次/6 次注入提醒**（不硬退出，让模型自己判断换思路/换参；翻页/换词本就参数不同、不触发）。
- **autocompact 熔断**（连续 3 次失败）+ **compress 防抖**（连续 2 次省<10% 跳过）。

---

## 11. 清理项

- 删 Snip、独立 Microcompact、Collapse（`collapseReadSearch`=前端 UI 折叠、`CONTEXT_COLLAPSE`=实验性，均不做）。
- 删 `AgentLoopContext` 遗留类 + Hermes/Claude 杂烩注释。
- **代码标识符不带版本后缀**（`v1`/`v3` 等）。

---

## 12. 参数总表

| 参数 | 值 | 备注 |
|------|----|----|
| `effective` | `window − min(max_output, 20_000)` | |
| `compress()` 触发 | `total ≥ effective − 20_000` | |
| `blocking_limit` | `effective − 3_000` | |
| Stage A 单结果落盘 | **>50_000 字符** | `DEFAULT_MAX_RESULT_SIZE_CHARS` |
| Stage A 单消息聚合 | **>200_000 字符** | 并行工具 |
| 预览大小 | **2_000 字节** | |
| 字符↔token | **4 字符/token** | |
| Phase 1 保护近期工具结果 | 最近 ~5 条不摘要 | |
| Phase 3 保留尾 | **仅最近 1–3 条**（含最近 user 消息） | Claude 全量压缩 |
| autocompact 摘要大小 | **≤20_000 token 输出预算**，由模型决定 | 无下限 |
| autocompact 摘要章节 | **9 段** | |
| autocompact 熔断 | 连续 **3** 次失败 | |
| compress 防抖 | 连续 **2** 次各省 <10% 跳过 | |
| 反应式恢复 | context 超限错误 → 强制压缩重试 **1** 次（单发 + 熔断3 + 重试期不跑 hook） | Claude query.ts |
| 重复调用软提醒 | **3 / 6** 次 | 不硬退出 |
| 硬安全阀（步数） | **80** 迭代 | |
| 时间预算 | **删除** | |
| `read_file` 分段 | offset/limit，默认 limit 20_000 字符 | 落盘结果也用它读回 |
| token 计数 | 真实 usage + tiktoken | 删 `chars/2.5` |

---

## 13. 落地步骤（分阶段，可单独验证）

**P1 — 归拢 + 地基（不碰摘要逻辑，风险最低）**
1. ✅ 新建 `context_manager.py`：`token_count()`（tiktoken，**单一实现**；L1 `count_tokens` 改 re-export，删重复 tokenizer）。`compress()` 骨架随 P1.5 落。
2. `_estimate_message_tokens` 的 `chars/2.5` 全换成 `token_count`（并入 P1.4 的 `context_compactor` 重写，受审查 agent 监督）。
3. ✅ **`read_file` 分段 + 落盘读回**：加 `offset`/`limit` + `has_more`/`next_offset`（修硬截断 bug）；加 `path` 参数 + `tool_result_storage.resolve_persisted_path()`（会话内约束）让 Stage A 落盘结果可读回。
4. 删 `AgentLoopContext` 遗留类 + 杂烩注释 → **必须同步迁移 14 个测试并补基类覆盖**（见 §1.5#4）。
5. `agent_strategy.py` 三处散调收口为 `compress()` 单入口；抽 `rebuild_messages()`，`execute()` 改用它。
6. **L2 去 RAG**：`_prepare` 在 agent 模式跳过 RAG 注入；`search_knowledge` 工具已确认存在（`tools/knowledge.py:55`）。
> 验：功能不变 + `read_file` 能续读 + 全测试绿。（P1.1/P1.3 已完成并通过测试。）

**P2 — Stage A + Phase 1 + 防死循环 + 防抖**
1. **Stage A（已存在，只调参）**：`tool_result_storage` 常量 30k→50k、100k→200k、预览 1500→2000 字节 + 对齐预览文案；落盘读回已在 P1 接通。Pass 2 跳过已落盘结果（保路径）归 P2.2。
2. **Phase 1**（按 Hermes 重写）：`_cheap_prepass` = 去重(全哈希) + 摘要旧结果(传 args、跳过已落盘) + JSON 安全截参 + 配对修复；可短路。
3. **防死循环**：删时间预算、步数阀 80、重复调用软提醒 3/6。
4. **防抖**：连续 2 次省<10% 跳过。
> 验：大结果落盘可分段读回 + 重复调用有提醒 + Phase 1 摘要带 query/路径。

**P3 — autocompact + 全统一持久化**
1. **autocompact**：token 整段摘要 + 留最近 1–3 + 迭代更新 + 仅供参考前缀 + 脱敏 + 失败兜底回退 + 熔断；压完走 `rebuild_messages()` 重编排。
2. **反应式错误恢复**（§6.3）：捕获 provider 的 context-超限错误 → 强制 autocompact 重试 1 次（`has_attempted` 单发 + 熔断 3 + 重试期不跑任何 hook）→ 仍失败抛明确错误、干净退出；主动 Blocking 仅兜"连最小上下文都装不下"。
3. **全统一持久化（D1）**：`transcript_service` 存完整工具历史 + 落盘引用记录；`CompactionService` 并入 `compress()`；`session_state.summary + compaction_cursor` 作边界+摘要。
4. 外层引擎 `LOAD → ORCHESTRATE → compress → RUN → PERSIST`（§8）。
> 验：深 query / 长多轮不溢出且能正常作答；前端能渲染含工具历史的记录。
