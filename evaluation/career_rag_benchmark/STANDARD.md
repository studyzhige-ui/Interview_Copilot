# Independent RAG benchmark contract

No organization publishes a universal, mandatory RAG dataset standard. This
contract combines established public interfaces without claiming that any one
of them certifies an answer as correct:

1. Retrieval interchange uses [BEIR corpus, queries and qrels](https://github.com/beir-cellar/beir/wiki/Load-your-custom-dataset).
2. Relevance labels follow the [TREC qrels principle](https://trec.nist.gov/data/qrels_eng/): a judged document ID and relevance score, with unjudged documents left unknown.
3. Generation evaluation keeps question, retrieved contexts, response and
   reference distinct, consistent with [Ragas evaluation samples](https://docs.ragas.io/en/latest/references/evaluation_schema/).

## Required layers for a gold release

| Layer | Required information | Gate |
|---|---|---|
| Original source | URL, publisher, exact file, content hash, license/use note, acquisition date | File can be re-downloaded or retained under an allowed license; hash verified |
| Corpus | Stable document ID, original language, title, canonical text, parser version | Every answer span maps to the original source and survives parsing |
| Query | Question, optional dialogue history, occupation, task type, source scope, answerability | No answer/evidence text is exposed to the RAG system |
| Retrieval label | Relevant document or passage ID and grade | Independently checked; alternate relevant evidence not assumed absent |
| Answer label | Atomic required claims, exact supporting spans, acceptable answer, prohibited claims | Human semantic review of completeness and support |
| Behavior label | Full answer, partial answer, clarify, or abstain; permission scope | Human review, including why the behavior is expected |
| Split | Dev, calibration, sealed test; occupation/case and paraphrase group | No group or source leakage across splits |
| Review | Author, reviewer, adjudication status, disputed items | Gold requires independent review and resolution |

Gold status requires the gates above. A mechanically valid candidate is not a
gold sample. Release reports must show per-language and per-occupation counts,
answerability distribution, multi-document and multi-turn counts, and the
number of excluded or disputed items. A public test repeatedly used for
optimization becomes a regression set, so a future release needs a fresh sealed
test group.

## Scoring boundary

Retrieval scores (Recall@k, nDCG@k, complete evidence coverage) use qrels or
span labels. Answer scores check claim coverage, factual support and cited
evidence. Behavior scores check correct partial answering, clarification,
abstention and access control. A single aggregate score must not hide failures
in safety, permissions, or a profession with few samples. Human reviewers
calibrate any model judge on a stratified subset and inspect disagreements.

The current `programmatic_candidate` set provides source-grounded, single-turn,
fully answerable occupation questions, including 14 two-document comparisons. The other
required layers above are specified but not yet populated, and therefore the
current set must not be presented as the complete gold release.
