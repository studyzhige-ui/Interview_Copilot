# RAG 评估体系使用指南

## 概述

本评估框架对 Interview Copilot 的 RAG 系统进行三层分层评估：

| Layer | 评估范围 | 是否需要 LLM | 核心函数 |
|-------|---------|------------|---------|
| **L1 检索质量** | Milvus + BM25 + Reranker | ❌ | `query_knowledge_base()` |
| **L2 生成质量** | 端到端 RAG 答案 | ✅ DeepSeek V4 + RAGAS v0.4 | `knowledge_retriever.retrieve()` + LLM |
| **L3 Agent 轨迹** | Planner 路由 + 工具选择 | ✅ DeepSeek V4 | `plan_query()` |

## 环境要求

- Python 3.11+
- 已安装 `ragas >= 0.4.3`、`langchain-openai`、`datasets`
- 环境变量 `DEEPSEEK_API_KEY` 已配置
- Milvus 服务运行中
- PostgreSQL 数据库运行中

## 快速开始

### 1. 使用 CLI Runner

```bash
# 运行全部评估
python -m evaluation.eval_runner --all

# 只运行检索层（不消耗 LLM token）
python -m evaluation.eval_runner --layer retrieval

# 运行生成层，限制 5 条样本
python -m evaluation.eval_runner --layer generation --limit 5

# 生成报告
python -m evaluation.eval_runner --all --report
```

### 2. 使用 pytest

```bash
# 运行全部评估测试
pytest evaluation/ -v -s

# 只运行检索质量测试
pytest evaluation/test_retrieval_quality.py -v -s

# 只运行生成质量测试
pytest evaluation/test_generation_quality.py -v -s

# 只运行 Agent 轨迹测试
pytest evaluation/test_agent_trajectory.py -v -s
```

## 黄金数据集格式

数据集存放在 `evaluation/golden_dataset.jsonl`，每行一个 JSON 对象：

```json
{
  "id": "ret-001",
  "layer": "retrieval | generation | trajectory | all",
  "query": "用户查询",
  "user_id": "eval_user_a",
  "source_type": "interview_qa",
  "reference_answer": "参考答案（用于 RAGAS 评估）",
  "expected_keywords": ["关键词1", "关键词2"],
  "expected_plan": {
    "answer_mode": "knowledge_qa",
    "needs_knowledge_retrieval": true,
    "knowledge_sources": ["interview_qa"]
  },
  "tags": ["tag1", "tag2"]
}
```

### 字段说明

| 字段 | 必需 | 说明 |
|------|------|------|
| `id` | ✅ | 唯一标识符 |
| `layer` | ✅ | 适用的评估层级，`all` 表示所有层 |
| `query` | ✅ | 用户查询文本 |
| `user_id` | ❌ | 评估用户ID（默认 `eval_user_a`） |
| `source_type` | ❌ | 知识源类型过滤 |
| `reference_answer` | ❌ | 参考答案（L1/L2 使用） |
| `expected_keywords` | ❌ | 期望在检索结果中出现的关键词 |
| `expected_plan` | ❌ | 期望的 Planner 路由结果（L3 使用） |
| `tags` | ❌ | 标签，用于筛选和分组 |

## 评估指标

### L1 检索质量

- **Hit@3/5**: Top-K 检索命中率
- **MRR@5**: 平均倒数排名
- **Precision@3**: Top-3 精确率
- **Recall@3**: Top-3 召回率
- **nDCG@5**: 归一化折损累积增益
- **Latency P50/P95**: 检索延迟
- **Isolation Violations**: 跨租户数据泄漏次数

### L2 生成质量 (RAGAS v0.4.3)

- **Faithfulness**: 答案是否忠实于检索上下文
- **Context Precision**: 上下文与参考答案的精确匹配度
- **Context Recall**: 参考答案被上下文覆盖的程度
- **Answer Relevancy**: 答案与问题的相关性
- **Factual Correctness**: 事实正确性
- **Hallucination Gate Rate**: 幻觉拦截触发率
- **Empty Answer Rate**: 空答案率

### L3 Agent 轨迹

- **Routing Accuracy**: Planner 路由正确率
- **Knowledge Trigger Rate**: QA 查询触发知识检索的比率
- **Direct Chat Rate**: 闲聊查询使用 direct_chat 模式的比率

## 报告输出

报告保存在 `data/evaluation/reports/eval_<timestamp>/`：

```
eval_2026-05-03_001/
├── report.md              # 人类可读 Markdown 报告
├── report.json            # 完整机器可读结果
├── retrieval_details.json # L1 详情
├── generation_details.json # L2 详情
└── trajectory_details.json # L3 详情
```

## 扩展数据集

1. 编辑 `evaluation/golden_dataset.jsonl`，按格式添加新行
2. 设置正确的 `layer` 字段以控制哪一层使用该样本
3. 对于多租户隔离测试，使用不同的 `user_id`（如 `eval_user_b`）

## 注意事项

- L1 检索测试**不消耗 LLM token**，可以频繁运行
- L2/L3 评估需要 DeepSeek API 调用，注意 token 消耗
- RAGAS 评估本身也会消耗 LLM token（用于 Faithfulness/Recall 等判断）
- 建议先用 `--limit 5` 做小样本验证，再跑完整评估
