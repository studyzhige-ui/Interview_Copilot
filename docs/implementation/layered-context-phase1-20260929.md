# 上下文分层压缩：第一阶段（2026-09-29）

## 范围与根因

在现有 Codex 衍生的消息准入、原版摘要模板、检查点版本与执行代次隔离之上，加入供应商无关的工具聚合缩减和最近交互保留。没有复制 Claude Code 内部模块，没有引入后台 session memory 或专用缓存编辑协议。

原路径仅限制单条工具结果，仍可能被多个中型结果挤满。仓库旧 `tool_result_storage.enforce_turn_budget` 虽存在，但当前策略没有调用；本次不恢复独立字符预算路径，在共享上下文层按 token 预算处理。原压缩只保留真实用户片段和最后摘要，最近助手回答与工具链依赖有损摘要。工具读取原本只支持当前 Turn，无法用裸 call ID 恢复旧轮次结果。

## 当前执行流程

1. 原始工具结果持久化不变。模型投影及 transcript 工具块携带来源 Turn；旧 transcript 可由 `ConversationTurn.assistant_message_seq` 恢复来源。无法确定来源的历史不伪造引用。
2. `admit` 对已知来源的大工具结果生成预览与引用。分页读工具保持内联，仍受原单条 token 上限约束，避免读到的页面再次引用自己。
3. Chat/Agent 发送前，`reduce_tool_results` 按助手调用批次计算工具结果聚合预算，优先替换较大的结果；累积历史超预算时从最旧批次替换，保护最新批次。预览必须确实节省 token，已替换内容不重复生成。
4. 仍到压缩阈值时，仅将较早前缀送给当前选择模型生成摘要。预算允许时优先保留最近整轮对话；长单轮任务保留近期完整助手步骤及工具结果，既不拆工具配对，也不截断尾部文本。旧摘要进入新摘要输入，不混入近期尾部。
5. 模型投影排列为摘要、最近消息；Agent 恢复精确当前任务、本轮材料和最新运行状态。保留的当前任务不会重复注入或移到工具结果之后。
6. 发布前核算系统、工具 schema、摘要、近期历史和恢复材料的完整请求。摘要未完整结束、必要内容仍超限或检查点过期时不发布。尾部已经排除在摘要输入外，失败时不能再偷偷删除尾部。
7. 轻量缩减也写检查点。轮内检查点记录已摄入的 call ID（包括保留原文的结果），恢复时不重复展开。结果引用和元数据序列化保存，不依赖进程全局状态。

## 配置与诊断

| 配置 | 默认 token 数 | 行为 |
| --- | ---: | --- |
| `CONTEXT_TOOL_OUTPUT_TOKENS` | 10000 | 原单条准入限制 |
| `CONTEXT_TOOL_BATCH_TOKENS` | 16000 | 单批工具结果目标上限，最多占可用输入的 1/4 |
| `CONTEXT_TOOL_HISTORY_TOKENS` | 24000 | 累积工具结果目标上限，最多占可用输入的 1/3 |
| `CONTEXT_TOOL_PREVIEW_TOKENS` | 256 | 引用内预览正文预算，不含读取说明 |
| `CONTEXT_RECENT_TOKENS` | 8000 | 最近完整交互保留上限；还受模型预算、摘要输出和必需材料预留约束 |

工具预算是缩减目标。最新分页结果、无来源的旧记录及引用本身可能使目标无法完全达到；随后由共享摘要与完整请求硬上限处理，不能为满足软预算删除唯一证据。

`context_report.compaction.tool_reduction` 记录替换身份、前后估算、节省量和有效预算。完整压缩使用 `strategy=prefix_summary_recent_tail`，并报告保留消息数、保留 token、最终请求估算与临时摘要输入裁剪数。单条 `admit` 的既有处理不计入后续聚合缩减节省量。

## 可恢复引用

`read_file(tool_call_id=..., source_turn_id=..., offset=..., limit=...)` 可跨 Turn 分页读取，但数据库查询仍同时限制 `session_id` 和 `user_id`。省略 `source_turn_id` 仍只读取当前 Turn，不扩大旧调用的权限。持久化正文保留，预览不是完整结构化结果，也不构成业务事实或授权。

## 验证与限制

相关回归命令：

```powershell
python -m pytest backend/tests/test_conversation backend/tests/test_agent_runtime/test_runtime_core.py backend/tests/test_agent_runtime/test_tool_call_executor.py backend/tests/test_services/chat/test_context_pipeline.py -q --disable-warnings
```

新增测试覆盖中型结果聚合、累计旧结果缩减、最新分页保护、引用幂等重放、前缀与近期尾部分离、完整并行工具批次、工具 schema 与运行状态预算、连续压缩、共享及轮内检查点、原始内容不变、过期写入拒绝、旧 transcript 来源恢复、跨轮精确分页与用户/会话隔离。

本次回归结果：158 passed；新增 16 项分层行为测试。修改代码通过 Ruff 检查，`git diff --check` 通过。

这是本地确定性行为验证；摘要模型调用使用 mock。未进行真实模型质量、缓存命中或延迟成本对比；不声明摘要不会遗忘。原有超窗兜底仍可能裁剪临时摘要输入，诊断保留 `trimmed_input_groups`。没有可靠来源的旧检查点消息继续依赖摘要或历史检索；不为了补来源而猜测 call ID。无需数据库迁移；运行中的服务加载新代码需要按正常部署流程重启。
