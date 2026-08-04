# Interview Copilot

Interview Copilot 是一个 AI 面试训练与复盘平台，包含模拟面试、录音分析、
简历/JD 检索、长期学习记忆、用户 Skill 和 MCP 工具。

项目采用一套共享核心、两个发行版本：

- **Interview Copilot Cloud**：面向普通用户的托管 Web 产品。用户选择回答
  LLM、个人 API Key、Skill、远程 MCP 和音色；内部规划、后台模型、语音与
  RAG 基础能力由运营方提供。
- **Interview Copilot Community**：面向 GitHub、个人自部署和学习开发者。
  部署者可以更换模型与服务，并在可信环境中显式开启本地能力。

两个版本不是两套源码或两条长期分支。产品权限由 `APP_EDITION` 和统一的
Edition Policy 决定，后端负责最终强制执行。

## 快速开始

本地只保留两种受支持的运行方式，请在同一份代码中二选一。

### 宿主开发模式

要求 Python 3.11–3.13、Node.js 20+、Docker Compose v2，并提前激活独立
Python 环境。

```powershell
pwsh ./scripts/setup.ps1
.\scripts\start.ps1
```

```bash
bash ./scripts/setup.sh
bash ./scripts/start.sh
```

安装时选择 Community，浏览器打开 `http://localhost:5173`。

### 完整容器模式

```bash
cp .env.community.example .env
# 在 .env 中填写生成的 SECRET_KEY 和部署方模型密钥
docker compose --profile full up -d --wait
```

浏览器打开 `http://localhost`。此路径已内置数据库迁移，并等待依赖服务健康后
再启动 API 和 Worker。

详细说明：

- [完整启动指南](getting-started.md)
- [代码库结构与依赖方向](../architecture/codebase.md)
- [双版本架构](../architecture/editions.md)
- [Community 部署](../deployment/community.md)
- [Cloud 部署](../deployment/cloud.md)
- [Agent 能力运行时](agent-capability-runtime.md)
- [全产品与核心系统审查](../reports/full-product-and-systems-audit-2026-08-04.md)

## 用户与部署者边界

Cloud 用户可配置最终回答 LLM、个人 Key、音色、声明式 Skill 和远程
Streamable HTTP MCP。Cloud 运营方负责 Embedding、Reranker、语音识别、
说话人分离、数据库、对象存储、任务队列、内部 `deepseek-v4-flash` 模型、
配额、监控和数据生命周期。

Community 部署者可以替换上述服务，但 stdio MCP 和私网 MCP 等本地进程或
网络能力仍需显式开启。
