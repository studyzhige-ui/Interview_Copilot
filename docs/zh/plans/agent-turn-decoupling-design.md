# AGT-1 设计文档：Turn 执行与连接解耦（事件缓冲 + 断线续播）

> 2026-07-07 · Phase 7 (6b) 交付物。与 [agent-context-management-plan.md](../agent-context-management-plan.md) 合流：
> 该计划负责"turn 内部的上下文形态"，本文负责"turn 的执行与传输形态"。两者共享同一个终点：
> **一个 harness、一条追加式 transcript、一个与连接解耦的 turn 执行器**。

## 1. 问题（为什么值得单独做）

当前形态：`POST /chat/{id}/stream` 的 SSE 连接**就是** turn 的执行体。
`ConversationEngine.submit_message()` 在请求协程里跑完全程，事件直接 yield 给响应流。

由此产生的缺陷（原审查 P0-1）：

| 症状 | 根因 |
|---|---|
| 断线 = turn 蒸发 | SSE 断开 → `GeneratorExit` → 循环中止；`_persist_turn` 虽已尽量前移，但执行本身死了 |
| 副作用不一致 | `save_memory` / `task_create` / `write_file` 在断开前已落库，但对应的 assistant 消息没有——transcript 与副作用脱节 |
| 刷新看不到进行中的 turn | 事件只存在于那条 TCP 连接里，没有任何缓冲介质 |
| 无法做 turn 排队/限流 | 执行体绑定在 HTTP 请求上，后端没有独立的 turn 生命周期可管理 |

Phase 0-7 已经把**能在现有形态下修的都修了**（用户消息先落库、finally 保底、
live==replay 事件不变式、degraded 标记）。剩下的断线蒸发问题在"连接=执行体"的
形态下**不可修**，只能换形态。

## 2. 目标形态

```
POST /chat/{id}/turns            ← 提交 turn（立即返回 turn_id）
        │
        ▼
   TurnExecutor（后台任务，进程内 asyncio.Task 起步）
        │  逐事件写入
        ▼
   Redis Stream  chat:events:{turn_id}     （XADD，TTL 1h）
        │                    ▲
        │  XREAD BLOCK       │ Last-Event-ID = stream 游标
        ▼                    │
GET /chat/{id}/turns/{turn_id}/events      ← SSE 只是订阅者，可重连
```

核心不变式：

1. **执行与连接解耦**：TurnExecutor 的生命周期与任何 HTTP 连接无关。断线不影响执行；
   执行完成后事件仍在 Stream 里等着被读。
2. **事件即事实**：所有会进 persisted blocks 的内容必须先成为 Stream 里的事件
   （Phase 7 已在流层建立此不变式，这里把它落到介质上）。
3. **续播协议**：客户端带 `Last-Event-ID`（= Redis Stream entry id）重连，
   服务端从该游标 `XREAD`。刷新页面 = 从 0 重放 + 转 live，与重连是同一条代码路径。
4. **持久化前移**：用户消息在 turn 提交时（executor 启动前）落库；assistant 消息在
   executor 的 `finally` 里落库（无论成败），degraded/partial 语义沿用现状。

## 3. 分步实施（每步独立可交付、可回退）

### Step 1 — 事件缓冲（S/M，~1 天）
- `TurnEventBuffer`：`XADD chat:events:{turn_id}`，字段 = 现有 `HarnessEvent.to_dict()`。
- streaming 端点改为"边执行边 XADD 边 yield"（双写）。此步不改执行形态，
  只为事件建立持久介质；断线时事件仍完整落在 Stream 里。
- `EXPIRE` 1 小时；turn 完成时写入终态哨兵事件（`done`/`error`）。

### Step 2 — 续播端点（S，~半天）
- `GET /chat/{session}/turns/{turn_id}/events`：从 `Last-Event-ID`（缺省 0）XREAD BLOCK。
- 前端 `streamChatSSE` 记录最后 entry id；`onerror` 自动带游标重连（EventSource 原生
  语义，或 fetch-reader 手动实现）。
- 验收：kill 网络 3 秒再恢复，transcript 无缝续上，与不断线逐字节一致。

### Step 3 — 执行体后台化（M，~1-2 天）
- `POST .../turns` 返回 `turn_id`，`asyncio.create_task(executor.run(...))`
  （持引用防 GC——同 MDL-4 教训）；SSE 端点纯订阅。
- 进程重启的丢失窗口：turn 开始时在 conversations 上记 `active_turn_id`；
  startup 扫描发现孤儿 turn → 写终态 error 事件（"服务重启，本轮中断"）——
  与 Phase 1 的僵尸清扫同一哲学。
- **不引入 Celery**：turn 是交互式低延迟工作负载，进程内 Task 足够；
  跨进程执行属于"量级变化后再说"（对齐明确不做清单的精神）。

### Step 4 — 前端 turn 生命周期（S/M，~1 天）
- 发送 = 提交 turn + 订阅事件两步；`useChatStream` 的 runtime 增加 `turnId`。
- 刷新页面时：transcript 载入后若 `active_turn_id` 存在 → 自动订阅续播。

## 4. L1/L2 合并评估（顺带结论）

**结论：合并值得做，但不在本计划内，放在 turn 解耦之后。**

- Phase 0 已让 agent mode 跳过 planner；Phase 7 已让 mode 入库。剩余差异只在
  strategy 内部（工具循环 vs 单次补全）。
- 中间态（成本最低）：planner 输出 `needs_tools` 布尔 → 引擎自动选 strategy，
  用户的 AGENT pill 从"手动开关"降级为"偏好提示"。这一步不依赖 turn 解耦，
  可作为独立 S 项排入后续。
- 完全合并（单循环，chat=零工具的 agent turn）依赖 turn 解耦后的执行器抽象，
  否则 L1 的低延迟路径会被 L2 的循环开销拖累。顺序必须是：解耦 → 单循环。

## 5. 与 agent-context-management-plan 的接缝

- 该计划的 compaction 改造（Claude-aligned）假设"消息逐条追加"——正是 Step 3
  之后的自然形态；两计划共享 `transcript_service` 的追加式写入接口。
- 本文的事件缓冲**不承担**上下文重建职责：重建永远从 persisted blocks 来
  （Stream 只是传输缓冲，1h TTL 说明了这一点）。

## 6. 工作量与风险

| 步骤 | 工作量 | 主要风险 | 回退 |
|---|---|---|---|
| 1 事件缓冲 | S/M | Redis 不可用时降级直连（保持现状路径） | 移除 XADD 双写 |
| 2 续播 | S | 游标语义错误导致重复渲染 | 前端按 entry id 去重 |
| 3 后台化 | M | 进程重启孤儿 turn | startup 清扫 + 终态事件 |
| 4 前端 | S/M | 双步提交的竞态 | turn 提交幂等键 |

总计 ~4-5 天。建议独立分支实施，Step 1+2 可先行合并（纯增益、零行为变化）。
