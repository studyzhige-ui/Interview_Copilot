"""Citation protocol shared by generation, persistence, and evaluation."""

from __future__ import annotations

import re

from app.rag.domain.models import CitationReport

_CITATION_RE = re.compile(r"\[(K\d+)\]", re.IGNORECASE)


def validate_citations(
    answer: str,
    sources: list[dict],
    *,
    retrieval_hit: bool,
) -> CitationReport:
    source_refs = {str(source.get("ref")) for source in sources if source.get("ref")}
    cited = list(
        dict.fromkeys(value.upper() for value in _CITATION_RE.findall(answer or ""))
    )
    valid = [ref for ref in cited if ref in source_refs]
    invalid = [ref for ref in cited if ref not in source_refs]
    return CitationReport(
        cited_refs=cited,
        valid_refs=valid,
        invalid_refs=invalid,
        missing_citation=bool(retrieval_hit and source_refs and not valid),
    )


class CitationStreamGuard:
    """Remove impossible citation ids while preserving token-level streaming.

    Only a trailing partial marker (``[``, ``[K``, ``[K12``) is buffered
    across model chunks; ordinary prose is forwarded immediately.
    """

    def __init__(self, sources: list[dict]) -> None:
        self.valid_refs = {
            str(source.get("ref")) for source in sources if source.get("ref")
        }
        self.buffer = ""
        self.removed_refs: list[str] = []

    def _sanitize(self, text: str) -> str:
        def replace(match: re.Match[str]) -> str:
            ref = match.group(1).upper()
            if ref in self.valid_refs:
                return f"[{ref}]"
            self.removed_refs.append(ref)
            return ""

        return _CITATION_RE.sub(replace, text)

    def feed(self, delta: str) -> list[str]:
        self.buffer += delta or ""
        emit_until = len(self.buffer)
        open_index = self.buffer.rfind("[")
        if open_index >= 0:
            suffix = self.buffer[open_index:]
            if "]" not in suffix and re.fullmatch(r"\[[Kk]\d*|\[", suffix):
                emit_until = open_index
        ready, self.buffer = self.buffer[:emit_until], self.buffer[emit_until:]
        sanitized = self._sanitize(ready)
        return [sanitized] if sanitized else []

    def flush(self) -> str:
        value = self._sanitize(self.buffer)
        self.buffer = ""
        return value


__all__ = ["CitationStreamGuard", "validate_citations"]
