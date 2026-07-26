"""Lightweight post-generation citation check (generation plan §2.5).

Regex-only — NOT an LLM second pass. It answers two questions for trace/
observability:

  * does the answer cite any ``[K#]`` that isn't in the turn's sources?
    (invalid ref — the frontend simply won't resolve a source card for it;
    we never rewrite the answer text);
  * did a turn that retrieved evidence produce an answer with no citation
    at all? (missing-citation warning).

It deliberately does NOT judge whether a citation is *faithful* — only that
the ref id is structurally valid and present.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Matches [K1], [K12] — the citation tokens the model is asked to emit.
_CITATION_RE = re.compile(r"\[(K\d+)\]")


@dataclass
class CitationReport:
    cited_refs: list[str] = field(default_factory=list)  # refs found in the answer
    valid_refs: list[str] = field(default_factory=list)  # refs that exist in sources
    invalid_refs: list[str] = field(default_factory=list)  # cited but not in sources
    missing_citation: bool = False  # retrieval_hit but answer cited nothing

    @property
    def ok(self) -> bool:
        return not self.invalid_refs and not self.missing_citation


def validate_citations(
    answer: str,
    sources: list[dict],
    *,
    retrieval_hit: bool,
) -> CitationReport:
    """Check the answer's ``[K#]`` refs against ``sources`` and log warnings.

    ``retrieval_hit`` drives the missing-citation check: only a turn that
    actually surfaced evidence is expected to cite it.
    """
    source_refs = {s.get("ref") for s in sources if s.get("ref")}
    cited = _CITATION_RE.findall(answer or "")
    cited_unique = list(dict.fromkeys(cited))  # de-dupe, keep first-seen order

    invalid = [r for r in cited_unique if r not in source_refs]
    valid = [r for r in cited_unique if r in source_refs]
    missing = bool(retrieval_hit and source_refs and not valid)

    report = CitationReport(
        cited_refs=cited_unique,
        valid_refs=valid,
        invalid_refs=invalid,
        missing_citation=missing,
    )
    if invalid:
        logger.warning(
            "Citation check: answer references unknown sources %s (valid refs: %s)",
            invalid,
            sorted(source_refs),
        )
    if missing:
        logger.warning(
            "Citation check: retrieval hit with %d sources but the answer cited none.",
            len(source_refs),
        )
    return report


__all__ = ["CitationReport", "validate_citations"]
