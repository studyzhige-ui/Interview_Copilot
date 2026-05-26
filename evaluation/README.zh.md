# RAG 评测套件

Interview Copilot RAG 流水线的三层质量基准。之所以放在 `backend/tests/`
外面，是因为整套跑起来不便宜（Milvus + reranker + LLM 调用），而且依
赖外部状态（DeepSeek 余额、为 `eval_user_a` 建好索引的语料），不适合
每次 `pytest` 都触发。

| Layer | 评测内容 | LLM 成本 | 代码位置 |
|-------|---------|---------|---------|
| **L1 — 检索** | Milvus + BM25 + reranker 的命中率 / 精确率 / MRR / nDCG / 延迟 / 多租户隔离 | 无 | `runners.run_retrieval`、`test_retrieval_quality.py` |
| **L2 — 生成** | 端到端 RAG：检索 → DeepSeek 生成 → RAGAS v0.4.3 的 Faithfulness / ContextPrecision / ContextRecall / FactualCorrectness，外加幻觉拦截率 + 空答率 | 高（每行 1 次生成 + 4 次 RAGAS 评判 = 5 次 LLM 调用） | `runners.run_generation`、`test_generation_quality.py` |
| **L3 — Planner 路由** | `query_planner.plan_query` 的决策：知识检索触发率、dense_query 填充率、plan 失败率 | 每行 1 次 LLM 调用 | `runners.run_trajectory`、`test_planner_routing.py` |

## 快速开始

### CLI（详细输出，可选生成报告）

```bash
# 全部三层跑完整数据集 + 写报告
python -m evaluation.eval_runner --all --report

# 只跑 L1（不烧 LLM token，方便迭代）
python -m evaluation.eval_runner --layer retrieval

# 10 行小样冒烟测试
python -m evaluation.eval_runner --layer generation --limit 10 --report

# 固定 seed 的随机抽样（同一 seed → 同一批行）
python -m evaluation.eval_runner --layer generation --sample 20 --seed 42

# 详细进度日志
python -m evaluation.eval_runner --layer retrieval -v
```

### Pytest（CI 质量门）

```bash
# 全部三层
pytest evaluation/ -v -s

# 单层
pytest evaluation/test_retrieval_quality.py -v -s
pytest evaluation/test_generation_quality.py -v -s
pytest evaluation/test_planner_routing.py -v -s
```

每个测试文件读 session 级 fixture（`retrieval_metrics` / `generation_metrics`
/ `trajectory_metrics`），数据集**每层只完整跑一次**，无论这层声明了多
少个 assertion。CLI 和 pytest 调的是同一个 `runners.run_*` 函数 ——
没有重复逻辑。

## 质量阈值

每个 `test_*.py` 里的默认值是按一套健康 DeepSeek-V4 + 完整知识语料的部署
校准出来的。系统改进后请上调阈值；只有当厂商换型或基础设施变化合理拉低
基线时再下调。

| 测试 | 阈值 | 原因 |
|------|------|------|
| L1 Hit@3 | ≥ 0.80 | 多数 QA 查询应至少有一个相关 chunk 进 Top 3 |
| L1 MRR@5 | ≥ 0.60 | 第一条相关 chunk 通常排在前两位 |
| L1 Precision@3 | ≥ 0.50 | Top-3 中至少一半要扣题 |
| L1 P95 延迟 | < 2000 ms | 单机开发环境，同步 reranker |
| L1 隔离违规数 | = 0 | 安全硬底线 —— 绝不能跨用户串数据 |
| L2 Faithfulness | ≥ 0.70 | 答案要扎根于检索到的上下文 |
| L2 ContextPrecision | ≥ 0.60 | 检索到的 chunk 与参考答案相关 |
| L2 ContextRecall | ≥ 0.60 | 参考答案要被上下文覆盖 |
| L2 FactualCorrectness | ≥ 0.50 | RAGAS 核对答案与参考是否事实一致 |
| L2 幻觉拦截率 | ≤ 0.30 | 检索为空导致拒答的频率 |
| L2 空答率 | ≤ 0.10 | 生成大部分时候都要拿到结果 |
| L3 知识触发率 | ≥ 0.80 | 数据集全部为 QA 标签，planner 应触发 RAG |
| L3 dense_query 填充率 | ≥ 0.95 | 触发 RAG 时必须给出可用的 query 字符串 |
| L3 plan_query 失败率 | ≤ 0.02 | 容忍偶发厂商超时，超过就是系统性问题 |

## 模块布局

```
evaluation/
  README.md                     ← 英文版
  README.zh.md                  ← 本文件
  runners.py                    ← 核心异步 runner（load_dataset、run_retrieval、…、prepare_runtime）
  eval_runner.py                ← 包在 runners.py 外面的薄 CLI
  conftest.py                   ← session 级 fixture：数据集 + 每层 metric dict
  test_retrieval_quality.py     ← L1 质量门
  test_generation_quality.py    ← L2 质量门
  test_planner_routing.py       ← L3 质量门
  metrics.py                    ← 纯 ranking / 延迟数学（Hit@K、nDCG、percentile…）
  llm_factory.py                ← 生成器和 RAGAS 评判用的 DeepSeek LLM 构造工厂
  report.py                     ← JSON + Markdown 报告写出（仅 CLI 用）
  golden_dataset.jsonl          ← 835 行精选 QA pair
```

## 黄金数据集格式

每行一个 JSON 对象：

```json
{
  "id": "all-001",
  "layer": "all",
  "query": "请解释大模型微调的原理？",
  "reference_answer": "微调的本质是参数高效迁移…",
  "user_id": "eval_user_a",
  "source_type": "interview_qa",
  "tags": ["knowledge", "qa"],
  "source_file": "<原始 PDF>"
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✓ | 行唯一 id |
| `layer` | ✓ | `retrieval` / `generation` / `trajectory` / `all` |
| `query` | ✓ | 用户问题 |
| `reference_answer` | 可选 | L2 RAGAS 评分必需；L1 缺省时退化为用 query 自己当参考 |
| `user_id` | 可选 | 默认 `eval_user_a` |
| `source_type` | 可选 | 把 L1 检索限定到某一个语料 tag |
| `tags` | 可选 | 自由标签，用于筛选 |
| `source_file` | 可选 | 出处溯源，runner 不读 |

自带的数据集是 735 行仅 retrieval + 100 行 `layer=all`（这 100 行三层都
吃）。新增行直接 append 到文件即可 —— runner 自动识别。

## 前置条件

- Python 3.11+
- `ragas>=0.4.3`、`langchain-openai`、`datasets`（已在 `requirements.txt` 里）
- `.env` 配置好 `DEEPSEEK_API_KEY`
- Postgres + Milvus + Redis 正常运行（`docker compose up -d`）
- 给 `eval_user_a` 索引了知识语料（跑任何写入这个 user_id 的 ingestion
  脚本，或按需在每行覆盖 `user_id`）

Reranker 模型首次跑会下载（~1 GB 的 BGE checkpoint），缓存在
`data/cache/huggingface/` 下。后续跑只需几秒预热。

## 报告

`--report` 在 `data/evaluation/reports/eval_<YYYY-MM-DD_HHMMSS>/` 下写出
带时间戳的目录：

```
report.md                  ← 人类可读的 Markdown 总览
report.json                ← 机器可读的完整结果
retrieval_details.json     ← L1 每行明细（--layer retrieval 跑过时）
generation_details.json    ← L2 每行明细（含 per_sample_details）
trajectory_details.json    ← L3 每行明细
```

Markdown 报告按层渲染，每层一个 metric 表格 + 若干延迟子表（`Latency`、
`Retrieval Latency`、`TTFB`、`End-to-End QA Latency`）。

## 成本提示

- **L1 不烧 LLM token** —— 可以频繁迭代。
- **L2 烧 DeepSeek token** ，大致是 `(1 + 4) × 数据行数 × ~2k 输入字符`。
  跑完 100 行生成层在 DeepSeek 当前定价下大约 5 美分；语料更大就线性
  放大。先用 `--limit 5` 验证链路通了，再放量。
- **L3 每行一次便宜的 LLM 调用** —— planner 每次 ≤ 1k token，可以高频跑。

## 这次重构改了什么

P10 之前 evaluation/ 有两个长期 bug：

1. `test_agent_trajectory.py` 和 `eval_runner.py` 的 L3 分支都 import
   `app.agent.planner.plan_query` —— 这条路径**在代码里从来没存在过**。
   真的 planner 在 `app.conversation.query_planner.plan_query`，而且
   planner-merge 重构之后它的 `QueryPlan` 形态也变了（`answer_mode`、
   `knowledge_sources`、`standalone_query` 都被砍了）。
2. `test_generation_quality.py` 调
   `knowledge_retriever.retrieve(source_types=[...])` —— 复数，但真实
   签名是 `source_type=` 单数，第一行就 TypeError。

现在的文件两个 bug 都修了；CLI 和 pytest 共享 runner；L3 改成在 planner
上断言聚合层面的指标（旧的 per-row `expected_plan` 比对没价值 —— 数据
集 835 行里**一行都没有**这个字段）。
