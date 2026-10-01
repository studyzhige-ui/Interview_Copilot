# Professional knowledge RAG corpus

> **Release withdrawn (2026-09-23).** The 400 automatically assembled Q&A
> records do not meet the requested high-quality dataset standard. They remain
> here only as an auditable draft. Do not use them as a benchmark or gold set.
> See [the quality audit](QUALITY_AUDIT.md).

This is the **primary** collection for the rebuilt benchmark. It is separate
from the existing local RAG data and from the occupational-profile auxiliary
set. Every accepted source must be an actual downloaded original from its
publisher, with a SHA-256 snapshot and extracted text. A search-result snippet
or a generated summary is never an eligible source document.

## Acquired sources

`sources.seed.json` lists **42** publisher pages or PDFs, **21 English and 21
Chinese**. All 42 have been downloaded, extracted, and SHA-256 locked. They
span 23 topic domains and 31 publisher labels. See [the source catalog](SOURCES.md)
for every original URL and [the frozen manifest](manifest.lock.jsonl) for hashes.

The downloaded topics include:

| Area | Original publishers |
|---|---|
| Programming, frontend and data | Python, React, Vue.js, Git, MDN, pandas, scikit-learn |
| Database, networking and DevOps | PostgreSQL, IETF RFC 9110, Docker, Kubernetes |
| Agents and RAG | LangChain, MCP specification, Alibaba Cloud Model Studio |
| Security and privacy | NIST, OWASP, FTC, Chinese Personal Information Protection Law |
| Law, HR and education | Chinese Labor Contract Law, Civil Code, Patent Law, Teachers Law, education discipline rule |
| Medicine, nursing and pharmacy | WHO, National Health Commission, US National Library of Medicine |
| Food, manufacturing, accounting and e-commerce | WHO, Chinese Food Safety Law, MIIT, Ministry of Finance, E-Commerce Law |
| Accessibility and finance | W3C, SEC Investor.gov |

```powershell
python -m evaluation.professional_rag_benchmark.acquire
python -m evaluation.professional_rag_benchmark.verify
```

The command stores original files under
`data/evaluation/professional_rag_benchmark/raw/`, extracted UTF-8 text under
`text/`, and one hash-locked record per successful source in `manifest.jsonl`.
It records any failures in `failures.json`. These runtime files are not part of
the repository; do not treat a URL in the seed list as proof that a document
was downloaded.

## Question candidate dataset

[`questions.candidate.jsonl`](questions.candidate.jsonl) now contains **400**
extractive, source-grounded question and answer candidates. Chinese and English
each have 200 items. The type counts are 252 single-fact, 84 long-span within
one source, 48 two-source/two-intent, and 16 long-span across two sources (three
evidence units). There are 564 exact evidence spans across all 42 original
documents. Each record includes its source IDs, frozen text hash, character
offsets, exact quote, answerability label, intent count, and a source-disjoint
split: 134 dev, 134 calibration, 132 holdout candidates. "Long span" here means
that two evidence spans in one document are separated by at least 800 extracted
characters. The open holdout candidate is **not** a sealed test set.

Answers are directly drawn from the frozen source text, with only whitespace
and PDF page-header cleanup. Questions combine manually anchored facts and
rule-based fact extraction. The generator rejected malformed drafts during
development, but **programmatic checks do not establish that every question is
natural, unambiguous or complete**. Some extractive answers reproduce source
wording rather than synthesizing all relevant context. Every item is explicitly
marked `programmatic_candidate`; independent domain review is still required
before any item may be called gold, especially for medical and legal content.
The [readable preview](QUESTIONS_400.md) supports that review.

```powershell
python -m evaluation.professional_rag_benchmark.build_questions
python -m evaluation.professional_rag_benchmark.validate_questions
python -m evaluation.professional_rag_benchmark.export_beir
```

The candidate JSONL is independent of any existing local RAG implementation.
The source documents and extracted text are the only evidence basis.
`export_beir` writes 42 corpus documents, 400 queries, and 464 document-level
relevance rows as BEIR-style `corpus.jsonl`, `queries.jsonl`, and split-specific
`qrels/*.tsv` under the runtime data directory. Exact passage evidence remains
in the main question JSONL; a relevant document label does not imply that its
entire text supports every answer claim. The format follows the [BEIR custom
dataset specification](https://github.com/beir-cellar/beir/wiki/Load-your-custom-dataset).
These qrels currently contain positive source labels only. They are not a
complete set of independently judged relevant and nonrelevant documents; as
the [TREC guidance](https://trec.nist.gov/data/reljudge_eng.html) notes,
evaluation requires matching judgments and document collection.

Regenerate the human-readable review file after rebuilding questions:

```powershell
python -m evaluation.professional_rag_benchmark.export_preview
```

## Gold acceptance rule

The primary question set will be released only after each question has:

1. a concrete professional knowledge task and source scope;
2. a reference answer with atomic required facts;
3. exact supporting span(s) in the frozen original text;
4. a checked answerability and expected behavior label;
5. source-disjoint, paraphrase-disjoint split assignment; and
6. semantic review for accuracy, completeness and natural wording.

The 400 question records are **candidates, not a reviewed gold release**. The
occupational auxiliary questions are excluded from these counts. The original
HTML includes occasional site navigation, and third-party reuse rights must be
checked before public redistribution. The files are an internal research
snapshot.
