# Interview Copilot

Interview Copilot 是一个 AI 面试训练与复盘平台，包含模拟面试、录音分析、
简历/JD 检索、长期学习记忆、用户 Skill 和 MCP 工具。

项目采用一套共享核心、两个发行版本：

- **Interview Copilot Cloud**：面向普通用户的 Web 产品。用户可以选择回答
  LLM，配置自己的 API Key、Skill、远程 MCP 和音色；内部规划、后台模型、
  语音与 RAG 基础能力由运营方提供。
- **Interview Copilot Community**：面向 GitHub 和学习开发者的自部署版本。
  模型、接口、本地运行时和 stdio MCP 均可由部署者配置。

两个版本不是两套源码，也不是两个长期分支。产品差异由 `APP_EDITION` 和统一的
Edition Policy 决定，后端负责强制执行。

## 快速开始

环境要求：Python 3.11+、Node.js 20+、Docker。

```powershell
pwsh ./scripts/setup.ps1
```

或者：

```bash
bash ./scripts/setup.sh
```

手动选择配置模板：

```bash
cp .env.community.example .env
# 或
cp .env.cloud.example .env
```

启动服务：

```bash
uvicorn app.main:app --app-dir backend --reload --port 8080
cd frontend
npm run dev
```

浏览器访问 `http://localhost:5173`。

详细说明：

- [完整启动指南](getting-started.md)
- [双版本架构](../architecture/editions.md)
- [Cloud 部署](../deployment/cloud.md)
- [Community 部署](../deployment/community.md)
- [Agent 能力运行时](agent-capability-runtime.md)

## 用户与部署者边界

Cloud 用户可配置：

- 最终回答所用的 LLM 厂商、模型与个人 API Key
- 声音
- 声明式 Skill
- 远程 Streamable HTTP MCP

Cloud 运营方负责：

- Embedding、Reranker
- 语音识别与说话人分离
- 数据库、向量库、对象存储和任务队列
- `deepseek-v4-flash` 内部规划/后台模型及其平台密钥
- 配额、监控、备份与数据生命周期

Community 部署者可以修改上述所有能力，但本地进程能力仍需显式开启。
