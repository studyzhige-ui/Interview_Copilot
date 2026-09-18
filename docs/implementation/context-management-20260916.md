> 历史阶段记录：本文件描述的 summary/cursor 与工具白名单缩减方案，已由 [Codex 上下文迁移](./codex-context-source-migration.md) 替换。当前架构以新文档为准。

# 上下文管理重构记录（2026-09-16）

## 结果

完成 Chat/Agent 主链路的上下文边界加固：路由输入、记忆/RAG 组装、消息编译、窗口预算、工具循环、长历史压缩、并发发布、恢复及诊断。保留现有记忆迁移和业务改动；未清理目录、删除原始历史或提交 Git。

完整流程及 Codex 固定版本源码映射见 [架构说明](../architecture/context-management-lifecycle.md)。这是基于现有 owner 的适配，不是复制 OpenAI 专用压缩协议。

## 已确认根因与修复

| 已确认问题 | 对应修复 |
|---|---|
| Chat 文本预算检查后重建消息，Agent 初始投影未把完整工具清单纳入同一预算 | 共享 RequestBudget/request_tokens，最终消息 compiler 加入 schemas，provider dispatch 前守卫 |
| Assembly、reducer 使用不同安全余量及输出保留规则 | 从同一配置与本次输出额度计算，不再套用 20k 输出上限或固定 13k 预压缩余量 |
| 摘要失败/保护尾部超大后直接移除旧消息 | 仅在成功发布摘要后移除其覆盖的投影，必要上下文不适配时显式停止 |
| 整段旧历史一次性送入 worker，未依据 worker 窗口分批 | 按完整对话单元限额分批，摘要串联，完整成功后才发布；超时/空值/超长摘要不提交 |
| summary/cursor 无旧值校验，迟到写入可能覆盖新摘要 | 行锁下校验 expected_cursor + expected_summary，原子发布；真实 PostgreSQL 并发验证 |
| 结构化引用和显式指导被按 token 切断 | 必需结构完整保留；可选记忆整块退出，RAG 沿原 builder 重新构建证据与引用 |
| 活跃工具结果尚未消费也可被归档 | 记录成功模型步骤已消费的结果；新结果保护；归档提供可回读 identity |
| 工具缺失结果追加到消息末尾，可能越过下一用户请求 | 在原调用批次内补“状态未知”；孤立/重复/迟到结果不拼接进其他调用 |
| 规划器只看 cursor 后近期消息，压缩后指代可能失联 | 明确传入低权威历史摘要，并为 router 独立控制窗口、输出和超时 |
| 缺少 final context 诊断 | 完成 metrics 记录预算、slot hash、裁减、摘要状态/边界、来源引用与 schema 名称；不记录正文 |

## 验证证据

- 相关扩展回归 **173 passed，1 deselected**。覆盖全部 conversation 测试（除下述已知无关测试）、context pipeline、Turn executor、runtime reducer、provider adapter、RAG grounding/retrieval、memory lifecycle、personalization API、真实 PostgreSQL 并发。
- 最后加入压缩状态遥测后，受影响的 compiler/pipeline/planner 测试 **47 passed**。
- XML：`data/logs/context-management-tests-20260916.xml`。
- 真实模型：`deepseek/deepseek-v4-flash`，合成数据两次压缩后续答；6 项检查全部通过。最新薪资更正、上海限制、B 岗位、薪资未知、未经确认不可投递及非空摘要均保留。
- 模型结果：`data/logs/context-lifecycle-eval-20260916.json`；脚本 `evaluation/context_lifecycle_eval.py --live --output <path>`。仅合成数据，不读取用户私有对话，不执行业务写操作。
- 新增单测验证：整块记忆裁减、工具 schema 计量、摘要失败不丢历史、分批失败不提交、陈旧摘要拒绝发布、未消费结果保护、工具结果按原位置配对、超长摘要拒绝、超预算不发网络请求、planner 压缩后指代。
- Ruff 检查通过；无新增数据库迁移。

### 已知无关失败

`test_tavily_tool_reports_deployment_connector_unavailable_at_call_time` 期望未配置 Tavily 时返回 connector_unavailable，但现有、未被本次修改的 `tools/web.py` 会走搜索 fallback。第一次扩展回归为 170 passed / 1 failed。没有为了本次上下文测试修改该搜索策略，也未把它计入通过数量；后续明确排除此项。

## 实际限制

1. 摘要有损，合成模型评测证明特定场景能延续，不证明任意会话永不遗忘。
2. 对超大的单个不可分割历史单元或必要输入选择保留数据、停止调用；没有通过截断约束掩盖容量不足。
3. 当前 Turn 只对已消费只读结果引用化，不新增第二个活跃语义摘要 owner。
4. Provider-neutral token 估算较保守；未实测所有 provider 的多模态计量，也未声称缓存命中率提升。
5. 原有业务 ContextPackage 与通用 AssembledContext 保持分工，不把此次边界加固宣称为全部产品模块/数据库的重写。

## 运行

更改涉及 API 和 turns worker，两个进程都需要加载新代码；仅刷新页面不够。前端没有本次必须重新构建的变更。原始消息、Memory、RAG 索引与业务状态均保留。

本地已在确认没有 pending/running Turn、两个 worker 的 active task 都为 0 后重启后端。2026-09-16 12:37，API、jobs worker、turns worker 均 ready，`/api/v1/health/ready` 返回 ready，database/redis 均 ok。启动日志：`data/logs/backend-20260916-123720.log`。本次没有启动此前已关闭的前端进程。
