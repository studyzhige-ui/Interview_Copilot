# Quality audit of the withdrawn 400-question draft

Status: **failed editorial review**. The source snapshot is usable as research
material, but the automatically assembled question set is not a benchmark.

## Confirmed defects

1. **Question construction:** rule-based subject/verb templates produced vague
   prompts such as “what does the document state about …” and malformed
   questions whose subject was only part of a sentence.
2. **Answer construction:** some exact text spans start or end mid-thought, so
   positional matching and SHA-256 verification alone did not establish a
   complete answer. Examples in the first draft included a Promise answer
   ending with a colon and a React answer beginning with “let you”.
3. **Long-span construction:** the generator combined far-apart facts without
   checking that the parts form one meaningful professional task. Example:
   a Food Safety Law question joined general producer duties to a provision on
   State Council regulatory structure.
4. **Repetition:** 148 compound questions reused facts from the 252 single-fact
   questions, sometimes in several near-identical combinations. The count of
   400 therefore overstates independent coverage.
5. **Review status:** there has been no line-by-line professional review of all
   400 records, and no clinical or legal expert adjudication. The old delivery
   should not have been presented as satisfying the user's quality requirement.

## Acceptance gate for the rebuild

Each retained question must have a specific, natural prompt; a concise answer
that addresses every requested part; exact original-source evidence; a checked
source scope and date; a distinct test purpose; and a recorded editorial
decision. Multi-source and long-span items must require the selected evidence
for one coherent task. Near duplicates must be removed before counting toward
400. Medical and legal items require specialist review before being called
domain-certified gold.

The existing `questions.candidate.jsonl`, preview, BEIR export, and ZIP are
withdrawn drafts. Passing the structural validator does not override this
editorial failure.
