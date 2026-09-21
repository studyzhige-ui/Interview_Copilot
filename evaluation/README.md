# RAG evaluation

This directory validates the production path: parsing, cleaning, chunking,
embedding, PostgreSQL/pgvector exact dense + scoped BM25 retrieval, RRF, CrossEncoder reranking, evidence
gating, streaming generation, and citations. Gold annotations are never added
to retrieval requests.

## Scope

- The pinned semantic corpus contains official HTML, Markdown, PDF, and TXT
  documents with verified SHA-256 hashes.
- PDF is one required format, not the only format. Community uses Docling for
  supported structured documents and falls back to PyMuPDF for the whole PDF
  when Docling cannot complete it. LlamaParse is opt-in.
- Format-fidelity tests separately cover DOCX, PPTX, XLSX, CSV/TSV, JSON, code,
  image OCR, and legacy Office conversion.
- Community remains CPU-compatible, but maintainer quality and performance
  release campaigns use CUDA only.

## Dataset and qrels

`corpus_manifest.json` pins sources, licenses, and hashes. Positive rows in
`rag_dataset.jsonl` use atomic `evidence_groups`. Every phrase in one group must
occur in one chunk; separate groups may span chunks or documents. The scorer
maps the verbatim evidence onto the rebuilt index after ingestion. Retrieval
sees only the user question and production planner output, so these qrels are
labels, not leaked search hints.

Each atomic group is an AND requirement; `alternatives` are equivalent OR
representations of that same fact:

```json
{
  "source_files": ["one.html", "two.pdf"],
  "evidence_groups": [
    {
      "source_file": "one.html",
      "alternatives": [
        {"all_of": ["verbatim phrase A", "verbatim phrase B"]},
        {"all_of": ["equivalent verbatim passage"]}
      ]
    },
    {
      "source_file": "two.pdf",
      "alternatives": [{"all_of": ["verbatim phrase C"]}]
    }
  ]
}
```

Calibration/test splitting is group-aware and source-disjoint: translated
pairs, one source, and one multi-intent scenario cannot cross the boundary. An
independent agent builds the dataset; code only validates schema, balance,
source evidence, and leakage.

```powershell
python -m evaluation.download_corpus
python -m evaluation.validate_rag_dataset
```

Runtime corpus files live under `data/evaluation/corpus/`. Evaluation rebuilds
only isolated users and runs a second-user tenant canary.

## Fixed release profile

Structural parameters are frozen instead of repeatedly reselected:

```dotenv
RAG_CHUNK_TOKENS=384
RAG_CHUNK_OVERLAP=64
RAG_CANDIDATE_COUNT=20
RAG_FINAL_COUNT=3
```

Every parser output passes the same token-safe final splitter. The reranker has
a 512-token total input budget with space reserved for query and special
tokens. `RAG_MIN_SCORE` and the single-intent score margin remain calibrated on
the calibration split because CrossEncoder scores are model-specific, not
probabilities.

The CUDA release command verifies corpus hashes, freezes planner output,
rebuilds the fixed index once, warms it, calibrates the evidence gate, checks
tenant isolation, and opens the held-out split once:

```powershell
python -m evaluation.rag_release
```

It writes `data/evaluation/release/cuda.json`. Only a completed,
release-ready CUDA report can be supplied to generation evaluation.
Changing `--output` cannot reopen the same held-out campaign; the claim is
stored in a separate identity-keyed ledger before the held-out run starts.

## RAGAS: one live check, then one formal 50

The generator uses the platform model or a complete maintainer-only
`EVAL_GENERATOR_*` override. The judge must use a different model.

```dotenv
EVAL_GENERATOR_API_KEY=
EVAL_GENERATOR_API_BASE=
EVAL_GENERATOR_MODEL=
EVAL_JUDGE_API_KEY=
EVAL_JUDGE_API_BASE=
EVAL_JUDGE_MODEL=
EVAL_JUDGE_CONCURRENCY=4
```

```powershell
python -m evaluation.eval_runner --layer generation --ragas-profile check `
  --profile data/evaluation/release/cuda.json --report

python -m evaluation.eval_runner --layer generation --ragas-profile formal `
  --profile data/evaluation/release/cuda.json --report
```

Formal 50 means 50 pinned questions. Five RAGAS metrics are evaluated per
question, so provider request count is normally greater than 50. The formal run
requires a fresh successful live check and must reuse its first answer and five
metric checkpoints. Unknown post-request crash states stop by default instead
of automatically repeating a possibly paid call.

## Metric guide

- Candidate evidence-group recall measures first-stage coverage before
  reranking.
- Hit@3 reports whether at least one correct passage reaches the Top-3.
- MRR@3 rewards the first correct passage appearing early.
- nDCG@3 evaluates multi-evidence coverage and ordering.
- Evidence-group recall@3 measures the fraction of atomic evidence units in the
  Top-3; document recall measures expected source coverage.
- Context evidence precision measures useful, non-duplicate evidence among
  chunks sent to the generator.
- Hard-negative FPR measures context admitted when the corpus has no answer.
- RAGAS reports Faithfulness, Context Precision, Context Recall, Answer
  Relevancy, and Factual Correctness.
- TTFT is time to the first non-empty token. TPOT is average time per later
  output token; throughput is output tokens per second.

Measured values belong in the current release report and the latest
`docs/reports/rag-evaluation-*.md`, not duplicated here as a stale baseline.


## Consumption attribution after the owner migration

Production ingestion, retrieval, reindex and user-model boundaries use the same
account ledger as the application. Supply/create the intended isolated evaluation
account; account IDs are obtained from canonical records, not guessed from vector
metadata. `EVAL_USAGE_USER` selects the optional production embedding account
(default `eval_user_a`). Its rate card/quotas apply, so missing owners or exhausted
budgets fail rather than silently using an unmetered deployment credential.
The independent Ragas generator/judge retains separate evaluation credentials,
checkpoints and cost data; do not present those as per-user application invoices.

`memory_lifecycle_eval` runs its internal production model wrapper under a
synthetic local account and retains `<report-stem>.usage.sqlite` beside its output.
It does not read production users. Keep this file (especially unresolved receipts)
when examining interrupted runs; deleting it is not evidence of a refund. Mock
interview evaluation uses its explicit `--user` account. Operator reindex and
library ingestion derive the authenticated/stored numeric document owner.

No live benchmark was run simply by implementing or importing these boundaries.

## Mock-interview evaluation: strict campaign boundary

The model-backed mock evaluation is separate from the PostgreSQL/Celery/browser
recovery suite. Dataset disconnect markers are observations only; they do not
prove a connection or process was interrupted. No learning-effect claim follows
from a synthetic conversation's score.

First run the read-only, credential-free preflight:

```bash
python evaluation/mock_interview_eval.py --plan-only
python evaluation/mock_interview_eval.py --mode turn --case self-intro-to-project --plan-only
```

Every selected dataset is validated before model resolution: duplicate IDs,
unknown fields, coerced booleans, bad stages and selected empty sections fail.
Unselected sections are `not_run`, not 100% success. Default input/trajectory
fixtures are unchanged. The finite call bound covers planning, the existing
single malformed-output repair, and judging; `--max-model-calls` limits the whole
campaign, irrespective of account count or lack of a monetary cap.

Only after preflight, and with an existing dedicated test account, run:

```bash
python evaluation/mock_interview_eval.py --mode turn --case self-intro-to-project \
  --user eval_user_a --output data/evaluation/mock/example-new-run.json
```

This second command calls real models. Planning and generation use one resolved
production primary model, including its account ledger. The judge now uses the
same `EVAL_JUDGE_API_KEY`, `EVAL_JUDGE_API_BASE`, `EVAL_JUDGE_MODEL` resolution as
RAG (all three or none), falling back to the existing DeepSeek judge configuration.
`EVAL_GENERATOR_*` still configures the separate RAG generator, not the production
mock interview. One-provider judging is not independent ground truth.

Reports use schema version 3 and the explicit `score10-v1` unit. Each selected section must finish with samples;
the gate recomputes results from strict per-item scores and checks, rather than
trusting stored totals. Scores use the shared 0–10 scale (at most one decimal place) with a nonempty reason:
99, `"5"`, 8.25, booleans, missing dimensions and extra fields are not repaired into
high scores. JSON numeric 5 and 5.0 are the same valid ten-point score. All judge
pass-rate aggregations use 8/10, not a leftover 4/5 cutoff. Old five-point reports
are retained as history and rejected by the new gate; they are not silently regraded. Duplicate JSON keys and nonfinite numbers are invalid. Generation
and judge latency are recorded separately.

The report records sample/source hashes and actual model settings, and is
atomically checkpointed after each case. A separate append-only call journal is
flushed before each attempt, contains hashes rather than source text, and covers
the judge as well as the production generator. Unknown transport outcomes stop;
there is no automatic re-run or resume. Existing report/journal files are never
overwritten. Reports can contain private prompts/results and must not be uploaded
as public CI artifacts. CI's `mock-preflight.json` has fixture identities and hashes
only and makes no model call. A preflight result is not a quality score.

Official contracts checked for this change: [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/).


## Shared assessment and source correction (local refactor patch)

`app.core.scoring` defines the one 0–10 grade unit used by product and eval code.
`interview-answer-10-v2` is a separate rubric: it specifies which criteria were
measured, not a different numerical unit. Per-question totals are calculated from
explicit criterion weights, and ability dimensions require direct answer quotes.
A quote match validates provenance only, not the truth of a model's judgment.
No coding-execution ability is inferred from an API/Python keyword. Unmeasured
dimensions are null, not zero; confidence is uncalibrated/null, not a fabricated
probability derived from question count. The proposed rubric still needs blinded
human calibration and real-model evaluation.

Question and answer edits are explicit, versioned commands. The UI preserves the
submitted draft when the response is uncertain; a read-only reconciliation checks
server state before any user-approved retry. Source corrections archive the old
report, clear dependent grades and signals, and mark published improved answers
as stale. A new explicit analysis is required. Review generation and source QA
identities prevent a prior task from publishing over a corrected answer. This
is not a claim of global exactly-once external requests or a tested GPU pipeline.

Three purpose contracts share the same execution core: `full`,
`project_deep_dive` and `focused_practice`. The last does not require uploading a
resume or JD. Existing records without a purpose remain the historical full
interview. The current model-backed fixture campaign covers the full-interview
path; deterministic tests cover the other two purposes. Do not claim live
quality coverage for them from the old full-interview fixture results.

Source correction PostgreSQL tests live in
`backend/tests/test_db/test_review_corrections_postgres.py`. They use the existing
required-PG fixture in CI. A skip in an environment without PostgreSQL is not a
pass. New migration rollback is allowed only before nonreconstructable new
versions/history are stored; export and migrate explicitly afterwards.
