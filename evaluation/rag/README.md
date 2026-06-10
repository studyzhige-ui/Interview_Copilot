# RAG evaluation subsystem (`evaluation/rag/`)

The new, layered RAG evaluation system from
`docs/zh/rag-evaluation-optimization-plan.md` (Phase D). It replaces the old
top-level `evaluation/` harness (frozen — kept as historical local code).

## Why this is version-controlled but the old harness isn't

The repo `.gitignore` ignores `evaluation/` because the old harness bundles a
`golden_dataset.jsonl` scraped from copyrighted PDFs. This subsystem's **code** is
tracked (a maintained subsystem, per the plan), via:

```gitignore
evaluation/*
!evaluation/rag/
evaluation/rag/datasets/      # gold JSONL embeds fixture content → stays local
```

So `evaluation/rag/**/*.py` is committed; `evaluation/rag/datasets/*.jsonl` and the
run reports under `data/evaluation/rag/reports/` (ignored via `data/`) are **not**.

## Layout

```
evaluation/rag/
  __init__.py     # puts backend/ on sys.path (runners import `app...`); dir constants
  schema.py       # gold-dataset dataclasses + JSONL loaders/validation; detail-row builder
  metrics.py      # pure metric functions (content_coverage, recall@k, ndcg, … ) — unit-tested
  cli.py          # `python -m evaluation.rag.cli` (planned)
  runners/        # planner / retrieval / citation / generation / ingestion (planned)
  report.py       # report.json + report.md + baseline diff (planned)
  tests/          # unit tests for the pure core — run separately from backend pytest
  datasets/       # gold JSONL (gitignored) — built from a dedicated eval user's fixtures
```

## Datasets (gold)

Four versioned files (schemas + validation in `schema.py`, full field tables in the
plan §3.1): `retrieval_gold.jsonl`, `planner_gold.jsonl`, `generation_gold.jsonl`,
`bad_cases.jsonl`. Gold data **must** come from a dedicated `eval_user`'s imported
fixture documents — never a developer's private KB — so `user_id` / tenant filter /
chunk ids are reproducible. `expected_chunk_ids` are hydrated `document_chunks.id`;
`expected_node_ids` (Milvus row ids) are diagnostic only. `expected_content` +
`min_content_coverage` (default 0.75) cover chunk-id drift after reingest.

## Running

```bash
# from the repo ROOT (so `evaluation.rag` resolves; backend/ is auto-added to path)
python -m pytest evaluation/rag/tests/ -q          # unit tests for the pure core
python -m evaluation.rag.cli --runner retrieval    # (planned) one runner
python -m evaluation.rag.cli --all --report        # (planned) full report
python -m evaluation.rag.cli --rebind-gold         # (planned) re-bind chunk ids after reingest
```

Common flags (planned): `--limit N`, `--sample N`, `--seed N`, `--with-ragas`,
`--report`, `--baseline <report_dir>`.

## Status (Phase D)

- **Done:** package scaffold; dataset + detail/trace `schema.py` (reusing the
  single `empty_reason` enum from `app.rag.retrieval_state`); pure `metrics.py`
  for all six metric families (retrieval / planner / generation / citation /
  ingestion / trace aggregation); unit tests for the pure core.
- **Remaining (need the live stack / real gold data, so they're follow-ups):**
  the five runners + `cli.py` + `report.py` + bad-case backflow; and building the
  real gold datasets, which requires importing fixture docs into Postgres + Milvus
  under a dedicated `eval_user` and reading back real `document_chunks.id`
  (`--rebind-gold`). Online `trace_id` emission stays out of scope here (offline
  runners stamp their own per-sample `trace_id`).
