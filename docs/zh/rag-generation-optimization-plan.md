# RAG 生成优化执行文档

> 状态: 已确认
> 范围: 只覆盖 RAG 生成链路，即 Context 组织 -> Prompt 约束 -> 引用和溯源 -> 拒答策略 -> 答案校验。
> 用途: 本文沉淀当前源码基线、最终优化决策和可执行规格，作为后续交给 Claude/其他 Agent 执行的依据。

## 1. 当前源码基线

关键文件:

- `backend/app/services/chat/context_assembly_pipeline.py`: L1/L2 共用的 slot-based context assembly。
- `backend/app/conversation/chat_strategy.py`: L1 chat/RAG 生成策略。
- `backend/app/conversation/agent_strategy.py`: L2 ReAct agent 生成策略和工具循环。
- `backend/app/conversation/engine.py`: 负责 planner、retrieval、memory load、context assembly，并把 `StrategyContext` 交给具体策略。
- `backend/app/conversation/strategy.py`: `StrategyContext` / `StrategyResult` 数据结构。

当前优点:

- L1 和 L2 共用同一套 `ContextAssemblyPipeline`，上下文组织已经比较系统。
- context 使用 slot 顺序组织: system / record context / summary / recent turns / memory / retrieved context / current query。
- RAG chunks 已经独立放入 `[Retrieved Context]`，没有和 memory 混在同一个槽里。
- L2 agent 不自动注入 engine-side RAG，而是通过 `search_knowledge` 工具按需检索。
- prompt cache 友好: 稳定内容靠前，per-turn grounding 靠后。
- 已有 token budget 和裁剪逻辑。

当前主要问题:

- L1 RAG 系统 prompt 很薄，目前只有“Use retrieved knowledge as evidence and avoid inventing sources.”
- 没有明确要求模型引用 `[K#]`。
- 没有明确规定证据不足时如何部分回答或拒答。
- 没有明确禁止把 memory/session 内容当作知识库来源引用。
- 没有生成后引用校验。
- `StrategyContext` 中有 `knowledge_chunks` 和 `needs_knowledge_retrieval`，但缺少更细的 retrieval state，例如 retrieval_hit、planner_failed、sources。
- L1 direct prompt 和 L1 RAG prompt 的边界还可以更清晰: RAG 问答应有更强证据约束，direct chat 可更自然。

## 2. 五个环节执行规格

### 2.1 Context 组织

当前源码基线:

- Context 组织由公共 `ContextAssemblyPipeline` 完成。
- `[Retrieved Context]` 已经是专门槽位。
- 检索阶段提供 hydrated top-N chunks；context assembly 在 token budget 裁剪后的最终 chunks 上生成 `[K#]` 轻量来源头和最终 sources。

已确认方向:

- 公共 Context 组织总体保持，不做大改。
- 生成优化不重写 L1/L2 公共 context assembly。
- 本轮重点补 L1 RAG 链路的个性化生成规则。
- 检索阶段负责提供 hydrated provenance；context assembly 负责生成 `[K#]` 和最终 sources；生成阶段负责使用这些来源。

### 2.2 Prompt 约束

当前源码基线:

```text
RAG_SYSTEM_RULES = "You are Interview Copilot, a concise technical interview assistant.
Use retrieved knowledge as evidence and avoid inventing sources."
```

问题:

- 约束太泛，没有可执行格式。
- 没有说明不同 context slot 的可信边界。
- 没有说明引用要求。
- 没有说明证据不足处理。

最终规则:

- `[Retrieved Context]` 是唯一可引用的知识库证据。
- 对基于知识库证据的事实性结论，答案必须使用 `[K#]` 引用。
- Memory、Recent Turns、Record Context 只能帮助理解用户和对话，不能当作知识库来源引用。
- 如果 Retrieved Context 与记忆/对话内容冲突，知识库问答以 Retrieved Context 为准；无证据时说明资料不足。
- 回答风格保持中文、简洁、结构化、面试辅导导向。

已确认:

- L1 RAG 约束写入 `RAG_SYSTEM_RULES`，也就是 context renderer 的 system prompt slot。
- 不新增独立工程模块拆分 Prompt 约束、引用策略、拒答策略；这些主要由 L1 RAG system prompt 统一表达。
- 不做生成参数特化，继续正常使用当前用户选择的 LLM runtime。

最终 L1 RAG system prompt:

```text
You are Interview Copilot, a concise technical interview assistant.

Context rules:
- [Retrieved Context] is the only citable knowledge evidence.
- [Memory], [Recent Turns], and [Record Context] can help understand the user and conversation, but they are not citable knowledge sources.
- Use retrieved evidence only when it is relevant to the user's current question.
- Do not invent sources, document names, pages, or citation ids.

Answer rules:
- For factual claims based on retrieved knowledge, cite the supporting chunk with [K#].
- If multiple chunks support the same point, cite all relevant ids like [K1][K3].
- If the retrieved context is insufficient, say what is missing.
- If only part of the question is supported, answer that part and clearly mark the unsupported part.
- If no retrieved evidence is relevant, do not pretend it is supported.
- Never mention internal retrieval, planner failure, reranking, or system implementation details to the user.

Style:
- Answer in Chinese unless the user asks otherwise.
- Be concise, structured, and interview-oriented.
```

### 2.3 引用和溯源

当前源码基线:

- 当前 context 中只有 `[K1] [source score=...] text`。
- 答案没有强制引用。
- 前端可用 sources 结构还不完整，且当前源码没有端到端 sources 通道: engine 只把 `knowledge_result.chunks` 交给 context，sources 没有进入 `StrategyContext`、SSE、持久化和前端 UI。

已确认:

- 检索阶段负责提供 hydrated top-N chunks；context assembly 负责在最终进入 context 的 chunks 上生成 `[K#]` 和 sources 数组。
- 生成阶段 prompt 要求答案使用 `[K#]`。
- 引用粒度为“有知识库依据的事实性结论就近引用”，不采用答案末尾统一列来源。
- 前端通过 sources 数组把 `[K#]` 映射到右侧边栏 source card。
- 边栏 source card 应能展示来源内容预览，并在可用时跳转到文档、页码、chunk 或外部链接。

端到端工程要求:

- `StrategyContext` 或等价结构必须携带最终 `sources`、`retrieval_hit`、`planner_failed`。
- `StrategyResult` 或 SSE payload 必须能把 sources 传给客户端；推荐新增 `sources` SSE 事件或把 sources 放在 `done` 事件中，二者择一即可。
- assistant message 必须持久化 sources，避免刷新历史会话后 `[K#]` 变成不可点击文本；本轮采用 `conversation_messages.content_blocks_json` 增加 `{"type":"sources","sources":[...]}` block，不新增数据库列。
- 前端需要新增 chat event 类型、消息 sources state、`[K#]` 行内解析和 source card 侧栏；这属于引用策略的必要外围工程，不是可选 UI polish。

### 2.4 拒答策略

当前源码基线:

- 检索无命中时 `[Retrieved Context]` 为空。
- 直接 prompt 只说 “If context is insufficient, say what is missing.”
- RAG prompt 没有明确拒答格式。

已确认:

- 拒答/部分回答主要由 L1 RAG system prompt 约束。
- 如果用户明确要求“根据我的知识库/资料”，但没有相关证据，应说明资料中证据不足。
- 如果只有部分问题有证据，回答有证据的部分并引用，未覆盖部分说明资料不足。
- 如果问题是一般技术概念，允许给出通用回答，但不能伪装成来自知识库。

### 2.5 答案校验

当前源码基线:

- 没有生成后引用校验。
- 没有检查答案中的 `[K#]` 是否存在。
- 没有检查是否引用了未进入 context 的来源。

已确认:

- 不使用 LLM 做二次审核，避免增加延迟和成本。
- 只做轻量正则校验:

```text
1. 从 sources 得到合法 refs: K1, K2, ...
2. 从 final_answer 提取 [K\d+]
3. 如果出现不存在的引用，记录 warning；答案文本保持原样，仅从 source card 映射中剔除该无效引用
4. 如果 retrieval_hit=true 但答案完全没有引用，记录 warning
```

校验边界:

- 正则校验只检查引用编号合法性和缺引用 warning，不判断语义是否 faithfully supported。
- 无效引用处理优先记录 warning 并从 source card 映射中剔除；不触发 LLM 重试。
- 如果 sources 通道为空，不应要求模型输出 `[K#]`，否则会生成不可解析引用。

## 3. 执行方向

本轮生成优化目标:

- 保持公共 ContextAssemblyPipeline 稳定。
- 重点重写 L1 RAG system prompt。
- 明确 `[Retrieved Context]` 是知识库证据；Memory/Recent Turns 只用于理解用户和对话，不作为知识库引用来源。
- 答案需要引用 `[K#]`。
- 证据不足时部分回答或说明不足，不编造来源。
- 增加轻量引用校验。
- 补齐 sources 从生成链路到 SSE、持久化和前端 source card 的通道。
- 不做生成参数特化。
- 不做 LLM 二次审核。
- L2 agent 生成规则本轮不修改，只在工具返回的知识结果中保留 source 信息。

## 4. 决策记录

| 日期 | 环节 | 决策 | 理由 | 状态 |
| --- | --- | --- | --- | --- |
| 2026-06-09 | Context 组织 | 保持公共 `ContextAssemblyPipeline` 稳定，不在生成优化阶段重写 L1/L2 共用 context assembly。 | 公共 context 工程已较成熟，生成优化重点应放在 L1 RAG 答案出口约束。 | 已确认 |
| 2026-06-09 | Prompt 约束 | 重写 L1 `RAG_SYSTEM_RULES`，放在 context renderer 的 system prompt slot；Prompt 统一表达证据使用、引用格式、拒答/部分回答和禁止暴露内部检索细节。 | Prompt 约束、引用策略和拒答策略本质上属于同一个答案生成约束，不需要拆成多个工程模块。 | 已确认 |
| 2026-06-09 | 生成参数 | 不做 RAG 专属 temperature / max_tokens 特化，继续正常使用当前用户选择的 LLM runtime。 | 正常模型配置已足够，额外参数层会增加复杂度且收益不明确。 | 已确认 |
| 2026-06-09 | 引用和溯源 | 检索阶段提供 hydrated top-N chunks；context assembly 在 token budget 裁剪后的最终 chunks 上生成 `[K#]` 和 sources 数组；生成 prompt 要求答案使用 `[K#]`；sources 必须进入 `StrategyContext/StrategyResult` 或等价结构，并通过 SSE、消息持久化、前端 source card 完成端到端映射。 | Prompt 负责引用表达，外围工程负责引用编号到真实文档/chunk/page 的映射和展示；当前源码会丢弃 sources，必须补数据通道，且编号必须在最终 context 上生成以避免错位。 | 已确认 |
| 2026-06-09 | 答案校验 | 不使用 LLM 二次审核；只做正则级轻量引用校验，检查答案中的 `[K#]` 是否存在于 sources，并记录缺引用或非法引用 warning。 | 二次审核会增加延迟和成本；本轮只需要防止不存在的引用和基础诊断。 | 已确认 |
