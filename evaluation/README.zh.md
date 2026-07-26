# RAG 评测

这套可选评测会调用生产代码中的规划器、混合检索和回答链路。它不属于默认后端
测试，因为运行时依赖外部服务、已索引的评测语料；生成与规划评测还会产生 LLM
费用。

| 层级 | 范围 | 需要外部 LLM |
|---|---|---|
| `retrieval` | 召回率、精确率、MRR、nDCG、延迟、租户隔离 | 否 |
| `generation` | 基于 RAGAS 的回答忠实度和完整性 | 是 |
| `trajectory` | 规划器是否检索、查询是否正确构造 | 是 |

## 准备

安装开发依赖：

```bash
pip install -e ".[dev]"
```

用 `golden_dataset.example.jsonl` 作为格式模板，建立属于项目自己的 JSONL
数据集。真实的 `golden_dataset.jsonl` 默认不纳入 Git，因为其中可能包含私有
或受版权约束的材料。

在 `.env` 配置任意 OpenAI-compatible 评测模型：

```dotenv
EVAL_LLM_API_KEY=...
EVAL_LLM_API_BASE=https://api.deepseek.com
EVAL_LLM_MODEL=deepseek-chat
```

运行前需启动 Postgres、Milvus、Redis，并为数据集中的评测用户预先索引对应语料。

## 运行

```bash
# 只测检索，不消耗评测模型 Token
python -m evaluation.eval_runner --layer retrieval --limit 20

# 全部层级并生成报告
python -m evaluation.eval_runner --all --report

# 显式指定数据集
python -m evaluation.eval_runner --layer retrieval \
  --dataset evaluation/golden_dataset.example.jsonl

# 质量门禁测试（慢，依赖外部状态）
pytest evaluation/ -v -s
```

`--sample N --seed N` 可生成可复现抽样。报告写入
`data/evaluation/reports/`，属于运行数据，不提交到仓库。

每行数据包含 `id`、`layer`、`query` 等字段；`layer` 支持
`retrieval`、`generation`、`trajectory` 或 `all`。质量阈值和断言放在
`test_*_quality.py` 中，应按所选语料和评测模型校准，不应通过随意降低阈值掩盖
回归。
