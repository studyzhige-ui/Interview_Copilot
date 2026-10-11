# 主线收敛（2026-10-11）

当前分支 `codex/mainline-convergence` 以集成版本 `c980b22` 为基础，保留 BGE、统一
`retrieval_entries`、HNSW 以及已迁入的上下文、工具执行、文件资产和自动化功能。
原目录成果迁入关系保存在 [集成记录](local-work-integration-20261001.json)。

## 恢复点

- 原目录第一轮清理：`codex/cleanup-round1` / `8d6ef1f`。
- 集成基线：`codex/checkpoint-integrated-base-20261011` / `c980b22`。
- 本次删除冗余前：`codex/checkpoint-before-design-cleanup-20261011` / `5c498a7`。
- 检查点保存 Git 源码；业务 `.env`、模型、语料和数据库保持原状。

## 保留的主线与删除的旁路

资料命令 → 共享入库 → 规范文档/分块 → `retrieval_entries`。
Chat、Agent、诊断和产品评测直接调用 `rag/application/service.py`，由它执行
BGE dense + BM25 → RRF → BGE 重排 → 证据筛选 → 原文补全与引用。
删除原服务转发层与第二个 pipeline 单例；规划失败状态在成功和失败结果中都保留。
精确/HNSW 共用数据、权限和流程；HNSW 只由运维脚本准备，不在请求中建索引。

聊天统一走原生模型适配器，删除旧 LlamaIndex 流式分支。事件定义归属
`conversation/events.py`，上下文序列化归属 `core/context_messages.py`，删除转导出层。
删除退役语音链路的窗口拼接、说话人匹配，以及无调用者的预算包装、私有辅助函数、
预签名上传/下载接口和专用配置；文件上传继续使用文件资产 capability 与不可覆盖写入。
用量页面统一调用 `/usage`，删除废弃的 `/workspace/model-usage` 和前端别名。
移除未使用的知识文档轮询函数及旧类型；资料库保留现有查询刷新逻辑。

Agent 策略、工具批次、恢复状态以及回合持久状态、异步执行监督各有实际职责，保留其边界。
文档解析回退、模型提供者适配与离线 MTRAG 基准有独立用途，不作为旧实现删除。
本次不新建审计框架，移除上一轮重复的审计/验证 JSON，历史版本仍可从检查点读取。

## 验证

- RAG、聊天、事件、存储与架构定向回归：233 passed、1 skipped。
- Linux 完整后端：2414 passed、5 skipped、0 failed，556 秒；按 CI 排除独立浏览器测试。
  使用一次性 PostgreSQL/pgvector、Redis 和 FFmpeg，覆盖真实迁移、HNSW 与音频解码。
- 全量快照后的最后几项旧别名/用量入口删除，在最终源码上补测用量、工作台、存储和架构：
  122 passed。前端最终源码：93 个文件、381 项测试通过，类型检查和 Lint 通过。
- Ruff 检查、914 个 Python 文件格式检查、编译、共享协议快照、Compose 配置与差异检查通过。
- 5 项跳过：下载语料、真实本地 embedding/reranker、可选 aiortc、2 项真实 S3 HTTP；
  未将离线回归当作真实模型质量或外部服务验收。业务数据库未迁移，远端未发布。
