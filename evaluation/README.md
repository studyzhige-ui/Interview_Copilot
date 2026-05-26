# RAG Evaluation Suite

Three-layer quality harness for the Interview Copilot RAG pipeline.
Lives outside `backend/tests/` because the runs are slow (Milvus +
reranker + LLM calls) and gated by external state (your DeepSeek
credit, the indexed corpus for `eval_user_a`), not the kind of thing
that should fire on every `pytest` invocation.

| Layer | What it scores | LLM cost | Where it lives |
|-------|---------------|----------|----------------|
| **L1 — retrieval** | Milvus + BM25 + reranker hit-rate / precision / MRR / nDCG / latency / multi-tenant isolation | None | `runners.run_retrieval`, `test_retrieval_quality.py` |
| **L2 — generation** | End-to-end RAG: retrieve → DeepSeek answer → RAGAS v0.4.3 Faithfulness / ContextPrecision / ContextRecall / FactualCorrectness, plus hallucination-gate + empty-answer rates | High (1 generate + 4 RAGAS LLM calls per row) | `runners.run_generation`, `test_generation_quality.py` |
| **L3 — planner routing** | `query_planner.plan_query` decisions: knowledge_retrieval trigger rate, dense_query population rate, plan failure rate | One LLM call per row | `runners.run_trajectory`, `test_planner_routing.py` |

## Quick start

### CLI (rich output, optional report)

```bash
# All three layers on the full dataset, write a report
python -m evaluation.eval_runner --all --report

# Just L1 (no LLM cost — cheap to iterate on)
python -m evaluation.eval_runner --layer retrieval

# Quick smoke test on 10 rows
python -m evaluation.eval_runner --layer generation --limit 10 --report

# Stable random sample (same seed → same rows)
python -m evaluation.eval_runner --layer generation --sample 20 --seed 42

# Verbose progress logs
python -m evaluation.eval_runner --layer retrieval -v
```

### Pytest (quality gates for CI)

```bash
# All three layers
pytest evaluation/ -v -s

# One layer
pytest evaluation/test_retrieval_quality.py -v -s
pytest evaluation/test_generation_quality.py -v -s
pytest evaluation/test_planner_routing.py -v -s
```

Each test file pulls from a session-scoped fixture (`retrieval_metrics`,
`generation_metrics`, `trajectory_metrics`) so the dataset is traversed
**exactly once per layer**, no matter how many assertions the file
declares. The CLI and the pytest layer call the same `runners.run_*`
functions — no duplicated logic.

## Quality thresholds

The defaults inside each `test_*.py` are calibrated against a healthy
DeepSeek-V4 deployment with a populated knowledge corpus. Tune them
upward as your system improves; lower them only when a vendor swap or
infrastructure change legitimately moves the floor.

| Test | Threshold | Why |
|------|-----------|-----|
| L1 Hit@3 | ≥ 0.80 | Most QA queries should land at least one relevant chunk in the top 3 |
| L1 MRR@5 | ≥ 0.60 | First relevant chunk usually ranks in the top 2 |
| L1 Precision@3 | ≥ 0.50 | Half the top-3 should be on-topic |
| L1 P95 latency | < 2000 ms | Single-user dev box, sync reranker |
| L1 isolation violations | = 0 | Hard security gate — never returns another user's data |
| L2 Faithfulness | ≥ 0.70 | Answers stay grounded in retrieved context |
| L2 ContextPrecision | ≥ 0.60 | Retrieved chunks are relevant to the reference |
| L2 ContextRecall | ≥ 0.60 | Reference answer is covered by the context |
| L2 FactualCorrectness | ≥ 0.50 | RAGAS verifies facts against the reference |
| L2 hallucination-gate rate | ≤ 0.30 | How often retrieval came back empty (refused answers) |
| L2 empty-answer rate | ≤ 0.10 | Generation succeeded most of the time |
| L3 knowledge trigger rate | ≥ 0.80 | All dataset rows are tagged as QA, so RAG should fire |
| L3 dense_query populated | ≥ 0.95 | When RAG fires, the planner must emit a usable query string |
| L3 plan_query failure rate | ≤ 0.02 | Allow occasional vendor timeouts; block anything systematic |

## Module layout

```
evaluation/
  README.md                     ← this file
  runners.py                    ← core async runners (load_dataset, run_retrieval, …, prepare_runtime)
  eval_runner.py                ← thin CLI around runners.py
  conftest.py                   ← session fixtures: dataset + per-layer metric dicts
  test_retrieval_quality.py     ← L1 quality gates
  test_generation_quality.py    ← L2 quality gates
  test_planner_routing.py       ← L3 quality gates
  metrics.py                    ← pure ranking / latency math (Hit@K, nDCG, percentile…)
  llm_factory.py                ← DeepSeek LLM builders for both the generator and the RAGAS judge
  report.py                     ← JSON + Markdown report writer (CLI-only)
  golden_dataset.jsonl          ← 835 rows of curated QA pairs
```

## Golden dataset format

Each line is one JSON object:

```json
{
  "id": "all-001",
  "layer": "all",
  "query": "请解释大模型微调的原理？",
  "reference_answer": "微调的本质是参数高效迁移…",
  "user_id": "eval_user_a",
  "source_type": "interview_qa",
  "tags": ["knowledge", "qa"],
  "source_file": "<original PDF>"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `id` | ✓ | Unique row id |
| `layer` | ✓ | `retrieval` / `generation` / `trajectory` / `all` |
| `query` | ✓ | User question |
| `reference_answer` | optional | Required for L2 RAGAS scoring; L1 falls back to using the query itself |
| `user_id` | optional | Defaults to `eval_user_a` |
| `source_type` | optional | Restrict L1 retrieval to one corpus tag |
| `tags` | optional | Free-form labels for filtering |
| `source_file` | optional | Provenance, not used by any runner |

The bundled dataset is 735 retrieval-only rows + 100 `layer=all` rows
(which feed all three layers). Add new rows by appending to the file
— they're picked up automatically.

## Prerequisites

- Python 3.11+
- `ragas>=0.4.3`, `langchain-openai`, `datasets` (already in repo `requirements.txt`)
- `DEEPSEEK_API_KEY` set in `.env`
- Postgres + Milvus + Redis up (`docker compose up -d`)
- Knowledge corpus indexed for `eval_user_a` (run any ingestion script
  that writes to that user_id, or override `user_id` per dataset row)

The reranker model downloads on first run (~1 GB BGE checkpoint) and
caches under `data/cache/huggingface/`. Subsequent runs warm in
seconds.

## Reports

`--report` writes a timestamped directory under
`data/evaluation/reports/eval_<YYYY-MM-DD_HHMMSS>/`:

```
report.md                  ← human-readable Markdown summary
report.json                ← machine-readable full results
retrieval_details.json     ← L1 per-row breakdown (when --layer retrieval ran)
generation_details.json    ← L2 per-row breakdown (with per_sample_details)
trajectory_details.json    ← L3 per-row breakdown
```

The Markdown report renders one section per layer, with a metric
table and any latency sub-tables (`Latency`, `Retrieval Latency`,
`TTFB`, `End-to-End QA Latency`).

## Cost notes

- **L1 is free** of LLM tokens — iterate freely.
- **L2 burns DeepSeek tokens** at roughly `(1 + 4) × dataset_rows × ~2k
  input chars`. The full 100-row generation layer is ~5 USD-cents on
  DeepSeek's pricing; bigger corpora scale linearly. Start with
  `--limit 5` to verify the chain works, then scale up.
- **L3 is one cheap LLM call per row** — the planner uses ≤1 k tokens
  per query. Cheap to run frequently.

## Notes on what changed

The pre-P10 version of this folder had two persistent bugs:

1. `test_agent_trajectory.py` and the L3 branch of `eval_runner.py`
   imported `app.agent.planner.plan_query` — a path that has never
   existed in the live tree. The real planner lives at
   `app.conversation.query_planner.plan_query`, and its `QueryPlan`
   shape changed during the planner-merge refactor (`answer_mode`,
   `knowledge_sources`, `standalone_query` were dropped).
2. `test_generation_quality.py` called
   `knowledge_retriever.retrieve(source_types=[...])` — plural, but
   the actual signature is `source_type=` singular, so the call would
   `TypeError` immediately.

The current files fix both, share runners between CLI and pytest, and
asserts aggregate-level metrics on the L3 planner (the per-row
`expected_plan` comparison was never useful — the dataset never had
that field populated for any of its 835 rows).
