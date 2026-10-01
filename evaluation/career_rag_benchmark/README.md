# Occupational-profile auxiliary candidate set

This collection is independent of `evaluation/rag_dataset.jsonl` and its runner.
It tests retrieval over real occupational descriptions and task lists. It is
**not** the main professional-knowledge RAG benchmark. It contains no official
programming, agent, legal or medical knowledge questions. The source snapshot
is required to reproduce evidence locations.

## Standard

There is no single official RAG dataset standard. This collection follows the
official [TREC qrels convention](https://trec.nist.gov/data/qrels_eng/) for
relevance judgments and the [BEIR corpus/query/qrels interchange format](https://github.com/beir-cellar/beir/wiki/Load-your-custom-dataset).
Answer assessment is a separate layer: every item records an answer, an exact
source span, expected answerability, source language, task type, split group,
and review state. The qrels do **not** assert that a relevant passage alone
guarantees a correct generated answer.

The source files are downloaded from the [O*NET 31.0 database](https://www.onetcenter.org/database.html)
and [中国就业网职业画像](https://chinajob.mohrss.gov.cn/zbzl/zdhd/hlwzyzd/zyhx/index.shtml).
These are real source records; no invented résumé, employer, candidate or case
materials are included. The China site is run by 中国就业培训技术指导中心. O*NET is
distributed under its [database license](https://www.onetcenter.org/license_db.html).
This collection includes modified selections from the O*NET 31.0 Database by
the U.S. Department of Labor, Employment and Training Administration, used
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). USDOL/ETA has
not approved, endorsed, or tested this collection. The generated corpus adds
occupation titles and `Task:` labels to verbatim O*NET descriptions and task
statements; questions and answers are our annotations.

## Candidate data card

The current snapshot has **418** questions across **32** occupations:
209 Chinese questions about 12 Chinese original pages and 209 English questions
about 20 English O*NET occupational records. It has 246 dev, 95 calibration,
and 77 test candidates. There are 253 task, 119 profile-field, 20 definition,
12 occupation-code, and 14 two-document comparison questions. All 418 are
single-turn, fully answerable candidates. The Chinese profiles are concentrated in service,
logistics, care, food and skilled trades; English O*NET records add software,
health, law, finance, engineering, education, design and management.

## Build

```powershell
python -m evaluation.career_rag_benchmark.build
python -m evaluation.career_rag_benchmark.validate
```

`build` downloads original CSV and HTML under
`data/evaluation/career_rag_benchmark/raw/`, writes their SHA-256 hashes to
`sources.jsonl`, and creates `corpus.jsonl`, `queries.jsonl`, `answers.jsonl`,
and BEIR-style `qrels/{dev,calibration,test}.tsv` in the same runtime directory.
The original source files are kept separate from labels. Index only `raw/` or
`corpus.jsonl`; never index `answers.jsonl` or `qrels/`.

The initial questions have `review_status=programmatic_candidate`. Exact span,
hash, uniqueness, and leakage checks establish provenance but cannot establish
that every question is natural, every answer is complete, or every alternate
evidence passage has been found. Human source and semantic review is required
before calling a split a gold release. The current occupational data tests
profile and task retrieval. It does not yet cover personal résumés, JD matching,
multi-turn references, partial answers, or safety behavior; those require real,
properly licensed and de-identified materials and separate annotation.

## Record contract

- `corpus.jsonl`: BEIR `_id`, `title`, `text`, plus source ID and language.
- `queries.jsonl`: BEIR `_id`, `text`, plus source language, profession, group,
  and split. No answers or evidence are present.
- `answers.jsonl`: private labels with exact `answer` and source span
  (`start`, `end`) in the corpus record. Offsets are Unicode code points.
- `qrels/*.tsv`: `query-id`, `corpus-id`, `score`; score 1 means the occupation
  record contains answer evidence. A comparison has two relevant records.
  No score 0 judgments are implied for unjudged documents.
- `sources.jsonl`: original URL, snapshot SHA-256, filename and source language.

Split groups are whole occupations, never individual questions. The language
balance is checked over both question and source language.
