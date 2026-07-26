# Interview Copilot 项目收口报告

日期：2026-07-26
工作分支：`feat/rag-optimization`

## 1. 收口结论

项目现在采用“一套产品核心、两个发行版本”的边界：

| 能力 | Interview Copilot Cloud | Interview Copilot Community |
|---|---|---|
| 交付形态 | 托管 Web 产品 | GitHub 自部署与学习项目 |
| 用户可选 LLM、个人 Key、模型角色 | 支持 | 支持 |
| 用户 Skill | 支持 | 支持 |
| 用户远程 MCP | 支持 | 支持 |
| stdio MCP | 禁止 | 部署者显式开启 |
| 自定义 LLM Endpoint/Header | 禁止 | 支持 |
| Embedding、Reranker、ASR、说话人分离 | 平台托管 | 部署者任选本地或远程 |
| TTS 音色 | 用户选择 | 用户选择 |

`APP_EDITION` 只决定产品权限，不决定模型必须部署在哪里。Community
可以全部使用远程 API；Cloud 的运营方也可以在自己的基础设施中托管模型。

## 2. Edition Policy

版本规则集中在 `backend/app/core/edition.py`，后端通过
`GET /api/v1/capabilities/edition` 暴露只读策略给前端。

后端负责最终授权：

- Cloud 拒绝保存自定义 LLM Endpoint、组织 ID 和请求头；
- Cloud 无论环境变量如何配置都拒绝 stdio MCP；
- Community 的 stdio 仍需 `MCP_ALLOW_STDIO=true`；
- 模型运行时会忽略 Cloud 中数据库残留的旧连接覆盖，不能通过绕过前端生效；
- 前端只根据公开策略显示选项，不自行复制版本判断。

## 3. Skill、MCP 与运行时隔离

能力状态按生命周期分层：

| 层级 | 实现 |
|---|---|
| 用户级 | `user_skills`、`user_mcp_servers`，密钥加密、启停独立 |
| 用户 + Server | `MCPManager[(user_id, server_id)]`，连接和工具缓存按 revision 重建 |
| 会话级 | `conversation_capability_states` 保存发现记录、权限和工具历史 |
| Turn 级 | `conversation_turns` 保存能力快照、已加载 Schema 和预算 |
| Tool Call | `agent_tool_calls` 保存参数、超时、取消、结果、错误和耗时 |

进程级 `ToolRegistry` 只注册应用内置工具。用户 Skill/MCP 从不写入全局
注册表；每个 Turn 使用独立的 `TurnToolCatalog`。Skill 正文和 MCP Schema
均延迟加载，减少提示词体积与不必要的权限暴露。

MCP 还具备：

- Streamable HTTP 与 Community 可选 stdio；
- 默认阻止私网目标，私网访问需部署者显式授权；
- 配置更新、禁用和删除后精确关闭对应用户连接；
- 同一 Client 串行请求、空闲回收、调用超时与取消；
- 工具名称命名空间，避免与内置工具或其他 Server 冲突。

## 4. 长任务正确性

长任务不再依赖浏览器连接存活：

- 请求先创建持久化 `ConversationTurn`，后台 Worker 原子领取；
- SSE 只订阅事件，刷新或断线后可重新连接；
- `owner_id + heartbeat_at` 构成执行租约，失去所有权的 Worker 不能提交终态；
- 取消会传播到当前工具调用并写入审计；
- 过期 Turn 由回收器幂等关闭并生成可见错误消息；
- Session Task 支持依赖图、循环检测、验收条件、证据和验证状态；
- Agent Checkpoint 保存摘要、当前任务和精确下一步；
- 新 Turn 会读取未完成任务、Checkpoint 和近期工具审计，继续跨 Turn 工作；
- 大工具结果落盘并在上下文中保留预览，避免静默截断。

这套机制保证的是“可观察、可恢复、可验证”，而不是承诺任意外部操作都能
自动成功。外部服务失败仍会形成明确失败状态，并保留重试所需证据。

## 5. 模型与依赖边界

依赖统一由 `pyproject.toml` 管理，不再维护相互引用的 requirements 文件：

- 基础依赖：Cloud/核心运行时；
- `community`：本地模型、OCR、WhisperX、Pyannote；
- `dev`：测试、静态分析与评测；
- Community 开发环境直接组合 `.[community,dev]`，没有额外中间文件。

Cloud 的语音模型和本地 RAG 模型依赖采用延迟导入。冷启动边界测试会阻断
Torch、WhisperX、Docling、Sentence Transformers 等 Community 包，并验证
Cloud 的 API、远程 Embedding、远程 Reranker 与远程 ASR 工厂仍可导入和构造。

环境模板只保留：

- `.env.cloud.example`
- `.env.community.example`

安装脚本会先识别 Edition，再选择对应依赖，Cloud 开发者不再被迫安装数 GB
本地模型栈。Docker Compose 直接读取 `.env`，不再维护第二套 Docker 环境文件。

## 6. 前端收口

- 新增 Agent 能力页面，用户可以导入/编辑/启停 Skill；
- 用户可以配置、测试、启停和删除自己的 MCP Server；
- 会话内可以覆盖 Skill、MCP Server 与内置工具权限；
- 模型设置页面按 Edition 隐藏或显示高级连接项；
- Cloud 只展示 LLM 用户配置，托管基础模型职责有明确说明；
- 模拟面试新增音色选择并保存浏览器偏好；
- 设计交付原型目录已删除，实际主题迁入 `src/styles/tokens.css`；
- 字体只保留覆盖 100–900 字重的 Inter Variable Font，删除重复静态字体。

## 7. RAG 与评测

现行 RAG 保留混合检索、统一重排、引用校验、文档原子写入、索引一致性检查、
清洗、解析回退和可观测空结果原因。

评测只保留一套可运行实现：

- retrieval、generation、trajectory 三层；
- 评测 LLM 改为任意 OpenAI-compatible 配置；
- 代码与示例 Schema 纳入 Community；
- 私有/受版权约束的黄金数据集和源文档继续忽略；
- 删除了只有 Schema/指标、Runner/CLI 一直未实现的重复 `evaluation/rag`
  骨架。

## 8. 删除的历史内容

- 旧 `.env.example` 与 `.env.example.lite`；
- 重复、相互嵌套的旧依赖清单与独立 Docker 环境模板；
- 9 份已经完成或失效的历史计划文档；
- 旧前端设计交付说明、演示 HTML/JSX、未使用 Logo；
- 重复静态字体；
- 旧模型注册表及其失效测试；
- 无消费者的配置字段与旧模型变量兼容逻辑；
- 重复工具审计表及对应迁移；
- 未完成的第二套 RAG 评测骨架。

仍保留的兼容逻辑只服务于真实数据升级或 API 数据读取，例如数据库迁移和已有
记录的读取兼容；没有为了“看起来干净”破坏可升级性。

## 9. 文档与部署

根 README、中文说明、入门文档和 Edition 部署文档已经改写为现行行为。
根 `docker-compose.yml` 明确属于 Community 完整栈；Cloud 使用核心镜像依赖，
生产拓扑由运营方提供。

Cloud 真正上线仍需要代码仓库之外的运营能力：

- 域名、TLS、网关、CDN 与水平扩容；
- 托管数据库、对象存储、队列、向量库和模型服务；
- 配额、计费/成本监控、告警、备份恢复；
- 数据保留、导出、删除、隐私协议和服务条款；
- 发布流水线与回滚策略。

这些不应伪装成本地 Docker Compose 的一部分。

## 10. 分支与验证

当前分支比 `main` 多 88 个已提交变更；现存远程备份分支没有当前分支之外的
独有提交，因此没有遗漏另一条仍需合并的功能线。

最终验证项目包括：

- 后端完整 pytest；
- Ruff 全仓 Python 检查；
- Python compileall；
- Alembic 单一 Head 与迁移测试；
- 两份 Edition 环境模板解析；
- Community Docker Compose 配置解析；
- 前端 TypeScript、ESLint（零 warning）、Vitest 与生产构建；
- Cloud 无 Community ML 包的冷启动边界测试；
- Git diff whitespace 检查。

最终结果：

- 后端：`999 passed, 5 skipped`；唯一 warning 来自 LangSmith 第三方包的弃用提示；
- 前端：7 个测试文件、34 个测试全部通过；
- Python：362 个文件通过 Ruff format check，Ruff lint 零错误；
- TypeScript、ESLint 零 warning、Vite production build 全部通过；
- Alembic：`0049_turn_ownership` 为唯一 Head；
- Cloud 轻依赖冷启动边界测试通过；
- 两份环境模板、PowerShell/Bash 安装脚本、YAML、Community Compose 与
  Git whitespace 检查全部通过。
