# Interview Copilot (Agent + RAG Backend)

This is the backend service for **Interview Copilot**, a powerful AI-driven interview assistant powered by **FastAPI**, **DeepSeek**, **LlamaIndex**, **Faster-Whisper**, and **ChromaDB**.

## 🌟 核心特性 (Features)

- **Audio Transcription**: 搭载工业级开源引擎 `Faster-Whisper`，实现离线、高精度的音频转录。
- **RAG Knowledge Base**: 利用 `ChromaDB` 与高维嵌入模型 `BAAI/bge-small-zh-v1.5` 构建本地记忆库。支持通过 `source_type` 元数据进行数据隔离（技术题库、个人回忆严格解耦）。
- **Agent System**: 搭载了具有动态思考及函数调用能力的 `LlamaIndex ReAct Agent`。它能智能分析对话意图，自动请求并整合知识库片段，给你无可挑剔的回答。
- **Memory Ingestion**: 支持热插拔式的记忆写入！无论是 PDF 简历导入，还是面试失败后的痛点总结，一键持久化为 Agent 长线神经记忆。

## 📦 环境安装 (Installation)

1. 克隆代码仓库：
   ```bash
   git clone <repo-url>
   cd Interview_Copilot
   ```

2. 推荐使用 Anaconda 或 Python 内置虚拟环境隔离依赖：
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows 下
   pip install -r requirements.txt
   ```

3. 环境变量配置：
   请复制仓库提供的模板，并填写您必要的秘钥信息：
   ```bash
   cp .env.example .env
   ```
   *确保您在 `.env` 中正确填写了 `DEEPSEEK_API_KEY`。*

## 🚀 启动与测试 (Running the Server)

进入后端目录，通过 Uvicorn 启动热重载：

```bash
cd backend
uvicorn app.main:app --reload --port 8080
```

服务启动后，系统将依次回显 DB 建表、LLM 配置加载 和 Whisper 引擎显存挂载情况。
成功后，请直接访问由 FastAPI 自动生成的交互式接口与测试文档：

> **Swagger UI Docs:** [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs)
