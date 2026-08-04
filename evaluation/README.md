# RAG evaluation

The optional evaluation suite exercises the production planner, hybrid
retriever and answer pipeline. It is intentionally outside the default backend
test run because it needs external services, an indexed evaluation corpus and,
for generation/planner scoring, a paid LLM.

The suite has three layers:

| Layer | Scope | External LLM |
|---|---|---|
| `retrieval` | source hit, passage hit/precision/MRR/nDCG, latency and tenant isolation | No |
| `generation` | grounded answer quality through RAGAS | Yes |
| `trajectory` | planner retrieval decisions and query construction | Yes |

## Prepare

Install the evaluation dependencies. Add `dev` when you also want to run the
pytest quality gates:

```bash
pip install -e ".[evaluation]"
pip install -e ".[dev,evaluation]"
```

Create a project-owned JSONL dataset. The repository includes
`golden_dataset.example.jsonl`; the real `golden_dataset.jsonl` is intentionally
ignored because evaluation content may contain private or licensed source
material.

Configure an OpenAI-compatible evaluator in your shell or local `.env`. These
variables intentionally do not appear in the ordinary Community/Cloud
templates because evaluation is an explicit developer workflow:

```dotenv
EVAL_LLM_API_KEY=...
EVAL_LLM_API_BASE=https://api.deepseek.com
EVAL_LLM_MODEL=deepseek-v4-pro
```

Postgres, Milvus and Redis must be running. If the private dataset's
`source_file` values point to local corpus files, prepare the isolated
evaluation tenant through the production parser/chunker/indexer:

```bash
python -m evaluation.prepare_corpus --reset
```

## Run

```bash
# Retrieval only (no evaluator tokens)
python -m evaluation.eval_runner --layer retrieval --limit 20

# All layers with a report
python -m evaluation.eval_runner --all --report

# Use an explicit dataset
python -m evaluation.eval_runner --layer retrieval \
  --dataset evaluation/golden_dataset.example.jsonl

# Quality-gate tests (slow and external-state dependent)
pytest evaluation/ -v -s

# Automated mock-interview quality gate
python -m evaluation.mock_interview_eval
```

Use `--sample N --seed N` for a reproducible sample. Reports are written under
`data/evaluation/reports/`, which is runtime data and is not committed.

## Dataset

Each line is a JSON object:

```json
{
  "id": "retrieval-001",
  "layer": "retrieval",
  "query": "Why isolate MCP tools by user?",
  "reference_answer": "Per-user isolation prevents capability leakage.",
  "user_id": "eval_user_a",
  "source_type": "interview_qa",
  "tags": ["agent", "security"],
  "source_file": "project-owned-fixture"
}
```

Retrieval rows should include `relevant_document_ids`, or a `source_file` that
maps to the deterministic document id created by `prepare_corpus`. A passage is
relevant only when its source is correct and its text is semantically relevant;
low-threshold answer overlap alone is not a gold label.

`layer` accepts `retrieval`, `generation`, `trajectory`, or `all`. Thresholds
live beside their assertions in `test_*_quality.py`; calibrate them for the
chosen corpus and evaluator rather than weakening them to hide regressions.

## Historical baseline (2026-07-27, invalidated)

The isolated `eval_user_a` run used five real PDFs, 902 chunks and 835
retrieval questions:

- Hit@3 / Recall@3: `0.9461`
- Precision@3: `0.7549`
- MRR@5: `0.9293`
- nDCG@5: `0.9399`
- P95 latency: `512.36 ms`
- tenant-isolation violations: `0`

The RAG figures above used the former relevance rule: loose lexical overlap
against `reference_answer`; Recall@3 was effectively the same binary measure
as Hit@3. They do not prove correct-source retrieval and must not be used as a
release claim. Since 2026-08-04 the suite requires correct source plus semantic
relevance, so a newly prepared isolated corpus must produce the next baseline.

All eight fixed mock-interview scenarios historically passed, with a `4.9/5`
mean judge score and 100% safety and grounding pass rates. Stage-budget and
prompt changes also require a rerun. Model judging remains an automated
regression signal, not a substitute for human interview-experience evaluation.
