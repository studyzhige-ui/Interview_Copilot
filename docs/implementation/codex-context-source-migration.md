# Codex 上下文机制迁移（2026-09-16）

## 目标与源码基线

本次替换普通 Chat 和 Agent 的上下文生命周期，不再把旧“摘要＋游标＋轮内工具白名单缩减”称为完整迁移。

固定上游版本：[openai/codex 83dc7d11](https://github.com/openai/codex/tree/83dc7d11e873f43533dc898d50fae71cf4d55dc5)。这是基于公开源码的 Python 实现迁移，不是运行 Rust Codex，也不是复制 OpenAI 服务端。

原版 `prompt.md`、`summary_prefix.md` 已直接接入运行时，没有改写成中文标题或 JSON 格式。源码与运行时副本均附 Apache-2.0 LICENSE、NOTICE，并用测试校验副本一致。

## 根因与结构性修改

| 原来的断点 | 新实现 |
| --- | --- |
| 跨轮只保存 summary/cursor；轮内仅把部分工具结果换成指针 | `context_window` 统一消息准入、压缩与 replacement history；两条执行路径使用同一压缩函数 |
| 将 Memory、RAG、运行状态和用户要求拼成一个 user 文本 | `_context.kind/id` 区分真实用户意图、检索材料、记忆、运行状态、摘要与工具结果；元数据不进入 provider wire |
| 压缩由内部 worker 使用另一个 prompt/JSON 协议执行 | 使用本次选择的主模型、当前系统规则和原版 handoff prompt；只接受完整结束的压缩输出 |
| 只靠数据库游标推断摘要之后的历史 | 保存完整替换历史，恢复时重放原始 transcript 尾部；`through_seq` 是已摄入原始记录的位置，不是摘要语义 |
| 修改早先用户消息来更新任务计划 | 当前任务原文保持不变，变化的运行状态追加为上下文消息；压缩后重新注入当前材料与任务状态 |
| 普通 worker 中断恢复缺少工具尾部重放 | 从同一 Turn 的持久化工具记录补回完成项；已被压缩覆盖的 call ID 不重复注入；等待确认仍沿原执行身份恢复 |

## 与上游对应

| Codex 源码 | 产品实现 |
| --- | --- |
| `core/src/context_manager/history.rs`：消息准入、工具输出截断、模型投影 | `conversation/context_window.py::admit`；类型元数据；原始工具记录不变 |
| `core/src/compact.rs`：同模型本地压缩、原始 prompt、真实用户保留、摘要最后放置 | `context_window.py::compact/replacement_history`；最多 20,000 tokens 用户历史；小窗口进一步限额 |
| `compact.rs`：超窗时移除最早项及对应工具结果重试 | `remove_oldest_group`；只裁剪临时压缩输入，未成功时不替换活跃历史 |
| `history/src/lib.rs` 的 `CompactedItem.replacement_history` | `ContextCheckpoint.state.messages`，包含类型与稳定身份；保存版本与窗口身份 |
| `session/rollout_reconstruction.rs`：检查点后重放 | `context_store`＋原始消息尾部＋当前 Turn 工具尾部；数据库版本和执行代次隔离 |
| `session/context_window.rs`：总量或扣除稳定前缀的阈值 | `RequestBudget.should_compact`，完整请求硬上限独立生效 |
| 稳定前缀与供应商缓存支持 | 系统规则、排序后的 schemas、历史位于动态上下文之前；现有 native Anthropic 缓存断点与 OpenAI-compatible 缓存 usage 保留 |

## 完整流程

1. 验证会话归属、读取产品运行状态；Chat 规划检索，Agent 按任务调用工具检索。
2. 从检查点恢复消息；补入检查点后的原始对话。旧会话首次使用时从完整原始记录重建，旧 summary/cursor 不再限制可见历史。
3. 按当前任务召回 Memory、获取 RAG/附件、读取明确引用的业务对象和指导规则。它们是独立上下文材料，不提升为系统指令。
4. 按实际模型窗口、输出预留、安全余量和完整工具 schemas 计费估算。工具输出统一在准入时限制，保留头尾与显式截断说明。
5. 达到阈值时进行压缩；生成真实用户片段＋最后的 handoff summary。跨轮压缩后注入本轮材料；轮内压缩还保留精确当前任务并重新注入最新运行状态。
6. 短事务校验检查点版本和 Turn dispatch generation，成功才发布 replacement history。失败、取消、长度截断、过期写入都不使原始记录丢失。
7. 最终编译再核算。必要时整项移除可选记忆、缩减 RAG 并同步引用卡片；用户要求和必要状态不能容纳时明确报容量错误。
8. Provider adapter 转换协议、移除内部元数据并执行最终容量校验；Agent 用实际 usage 校准后续估算。
9. 回答完成后先写原始 transcript，再写上下文投影。两次写入之间宕机，下次从原始尾部恢复，最多重复展开，不会丢原始对话。

## 持久化与入口

- Alembic `0045` 新增 `context_checkpoints`，不删除原会话、消息、工具结果、记忆或业务数据。
- 空 scope 保存已完成对话；Turn scope 保存轮内压缩检查点。版本每次发布递增，window ID 在替换窗口时变化。
- 原 summary/cursor 列保留作历史兼容数据，但不再驱动生产上下文或检索规划；旧 worker summarizer 和提交摘要的方法已移除。
- `GET /api/v1/chat/sessions/{id}/context`：本人会话的版本、类型和压缩诊断，不返回私有上下文正文。
- `POST /api/v1/chat/sessions/{id}/context/compact`：手动压缩，仅空闲会话；与自动压缩共用主模型和事务路径。目前是 API 入口，未新增前端按钮。
- `CONTEXT_TOOL_OUTPUT_TOKENS=10000`；`CONTEXT_AUTO_COMPACT_TOKEN_LIMIT=0` 使用模型预算默认阈值；`CONTEXT_AUTO_COMPACT_SCOPE=total|body_after_prefix`。

## 验证与边界

- 行为测试：准入不改原始结果、成对裁剪、用户意图分类、摘要位置、原版模板、未完整结束不发布、过期检查点拒绝、旧游标不隐藏历史、运行状态重注入、普通中断工具重放、API 归属和空闲限制、缓存前缀、硬上限。
- PostgreSQL：从迁移基线升级到 head，两个独立连接竞争同一检查点仅一个成功，原始消息完整保留。
- 真实 DeepSeek V4 Pro：两次压缩＋序列化恢复后的继续回答，六项合成约束检查全部通过。证据：`data/logs/codex-context-live-eval.json`。
- 最终回归 **177 passed，1 deselected**，记录于 `data/logs/codex-context-migration-tests.xml`。之前的 Tavily 不可用时回退行为与测试预期冲突，单独排除，不归为此次通过项。
- 本地数据库已升级 `0045`，API、turns worker、jobs worker 已重启；`/api/v1/health/ready` 返回 ready，database/redis 均正常。启动日志：`data/logs/backend-20260916-131030.log`。

不能据此声称与 Codex 所有实现细节完全相同：

- 本产品使用自己的 Memory/RAG/任务/确认机制作为数据源；没有移植 Codex 的 shell、MCP、guardian、rollback/fork 产品功能。
- 当前支持的是公开本地 compaction 路径，没有实现 OpenAI 私有远程压缩服务或 encrypted compaction item。
- 模型窗口预算保留本产品的显式输出预留与安全余量，默认自动阈值取窗口 90% 和可用输入 90% 的较小值；没有照搬 Codex 单一有效窗口百分比。
- tokenizer 是估算，实际 usage 用于校准；不能保证所有供应商的 token 计算或缓存命中率一致。
- 摘要是有损投影，合成验证不是所有长期任务都不会遗忘的证明；事实、授权、工具执行结果仍由原始数据库记录负责。
- 进程在模型输出后、业务持久化前中断时，恢复保证的是已持久化消息与工具记录，无法恢复尚未写入的流式文本。
