# Agent 能力运行时分层

Skill 与 MCP 的配置属于用户，但运行时状态不能注册到进程级工具表。产品策略先确定能力上限，运行时状态再按寿命分层：

| 层级 | 持有内容 | 生命周期 / 存储 |
|---|---|---|
| Edition/部署级 | Cloud/Community 允许的传输、连接覆盖和托管能力 | `EditionPolicy` + 环境配置 |
| 用户级 | Skill/MCP 配置、加密密钥、启停状态 | `user_skills`、`user_mcp_servers` |
| 用户 + Server 级 | MCP Client、工具定义缓存、连接状态 | `MCPManager[(user_id, server_id)]`；配置 revision 变化时关闭并重建 |
| 会话级 | 已发现 Skill、权限覆盖、最近工具选择历史 | `conversation_capability_states` |
| Turn 级 | 冻结的内置/MCP/Skill 清单、权限快照、延迟 Schema、用量观测 | `conversation_turns` 的三个 JSON 字段 |
| Tool Call 级 | 参数、超时、取消、状态、结果与耗时 | `agent_tool_calls` |

## 关键约束

- 有效能力是 Edition、部署可用性、用户启用、会话授权和 Turn 快照的交集；下层不能越过上层策略。
- 全局 `ToolRegistry` 只保存应用内置工具。每个 turn 从中创建不可变 `ToolRegistryView`，用户能力不会写入全局表。
- MCP Runtime 按 `(user_id, server_id)` 隔离，并由单独 worker 串行操作同一 Client。更新、禁用、删除或调用取消会精确关闭对应连接。
- 会话权限默认继承用户级启用状态；`deny` 会在下一个 turn 的快照中移除对应 Skill 或 MCP Server。已有 turn 不受中途配置变化影响。
- Skill 正文和 MCP Schema 都是延迟加载：Skill 列表只读取元数据；MCP 工具先发现名称，`tool_search` 后才把完整 Schema 加入本 turn。
- 前端停止按钮会调用服务端取消接口。任务取消沿 asyncio 任务传播到当前 Tool Call；MCP 调用取消时连接会关闭，审计状态写为 `cancelled`。
- 后台 turn 由独立 `turns` Worker 原子领取，`owner_id + heartbeat_at` 构成执行租约；Web API 只创建任务和转发事件。终态提交必须仍持有该租约，过期任务由周期性 stale 回收器幂等关闭。

## 数据库升级

运行 `alembic upgrade head`。当前发行基线会一次性创建会话能力状态、工具调用审计、不可变 turn 快照，以及 turn owner/heartbeat 租约字段。
