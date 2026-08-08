"""Structure-aware chunking behind one token-safe final gate."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from llama_index.core import Document
from llama_index.core.node_parser import (
    CodeSplitter as _LlamaCodeSplitter,
)
from llama_index.core.node_parser import (
    JSONNodeParser,
    MarkdownNodeParser,
    SentenceSplitter,
)

from app.rag.documents import CanonicalDocument, PageSpan
from app.rag.embedding_tokenizer import count_tokens
from app.rag.policy import current_rag_policy
from app.rag.retrieval_text import build_retrieval_text


# ── Splitter contract ────────────────────────────────────────────────────────


@runtime_checkable
class Splitter(Protocol):
    """A content-type chunking strategy. ``id`` / ``chunk_type`` are stamped as
    diagnostics; ``matches`` decides whether this strategy claims a document;
    ``split`` returns ``(nodes, qa_regex_hit)`` (qa_regex_hit only ever True for
    the sentence strategy's QA grouping — plan §4.4.3)."""

    id: str
    chunk_type: str

    def matches(self, content_kind: str) -> bool: ...

    def split(self, document: Document) -> tuple[list, bool]: ...


# ── Moved chunking helpers (verbatim from ingestion) ─────────────────────────


def _table_aware_nodes(document: Document, token_budget: int) -> list:
    """Group normalized, self-describing table records without splitting rows."""
    from llama_index.core.schema import TextNode

    lines = [ln for ln in (document.text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    nodes: list = []
    buf: list[str] = []
    for row in lines:
        candidate = "\n".join([*buf, row])
        if buf and count_tokens(candidate) > token_budget:
            nodes.append(
                TextNode(
                    text="\n".join(buf),
                    metadata=dict(document.metadata),
                )
            )
            buf = []
        buf.append(row)
    if buf:
        nodes.append(TextNode(text="\n".join(buf), metadata=dict(document.metadata)))
    return nodes


def _code_splitter(language: str) -> _LlamaCodeSplitter:
    """Build a CodeSplitter with an explicitly-constructed tree-sitter Parser.

    ``tree_sitter_language_pack.get_parser()`` returns the pack's own bundled
    Parser type, which fails LlamaIndex CodeSplitter's
    ``isinstance(_, tree_sitter.Parser)`` check. Building the Parser ourselves
    from the pack's Language + the pip ``tree_sitter`` satisfies it and keeps
    AST-aware code chunking working."""
    from tree_sitter import Parser
    from tree_sitter_language_pack import get_language

    parser = Parser(get_language(language))
    return _LlamaCodeSplitter(
        language=language,
        chunk_lines=40,
        chunk_lines_overlap=5,
        parser=parser,
    )


# Explicit Q/A prefix markers (plan §4.3 "最保守 QA 正则"). Anchored to line
# start (re.MULTILINE) so a mid-sentence "问题：" never matches; both half- and
# full-width colons. Longest alternative first only avoids a backtrack ("问题："
# also matches via "问" + backtrack on the colon) — clarity, not correctness.
_QA_Q_RE = re.compile(r"^[ \t]*(?:问题|问|Q)[:：]", re.MULTILINE)
_QA_A_RE = re.compile(r"^[ \t]*(?:答案|答|A)[:：]", re.MULTILINE)


def _qa_aware_nodes(document: Document) -> list | None:
    """Most-conservative QA-prefix grouping for PLAIN TEXT (plan §4.3, rule 2).

    A plain-text question bank using explicit ``Q:``/``A:`` (or ``问题：``/
    ``答案：``) prefixes would otherwise be cut between a question and its answer
    by ``SentenceSplitter``. ONLY when the text shows a real paired structure
    (≥2 question markers AND ≥1 answer marker) do we split at question
    boundaries so each Q-and-its-A stays in one chunk; the downstream oversize
    gate still re-splits any group that is too long. Returns ``None`` when
    there is no clear QA structure — the caller then falls back to the sentence
    splitter (never guesses, and structured parsers are never overridden since
    this only runs on the plain-text branch)."""
    from llama_index.core.schema import TextNode

    text = document.text or ""
    q_starts = [m.start() for m in _QA_Q_RE.finditer(text)]
    # A single question isn't a bank — require ≥2 questions (so an incidental
    # line-start "问题：" can't reshape a doc) AND ≥1 answer (a bare question
    # list is rule-3 "hint only", never a forced split).
    if len(q_starts) < 2 or not _QA_A_RE.search(text):
        return None

    spans: list[str] = []
    head = text[: q_starts[0]].strip()
    if head:  # preamble before the first question — keep it, drop nothing
        spans.append(head)
    for i, start in enumerate(q_starts):
        end = q_starts[i + 1] if i + 1 < len(q_starts) else len(text)
        # Each span begins at a marker match, so .strip() is always non-empty.
        spans.append(text[start:end].strip())
    return [TextNode(text=s, metadata=dict(document.metadata)) for s in spans]


# ── Strategies ───────────────────────────────────────────────────────────────


class TableSplitter:
    id = "table"
    chunk_type = "table"

    def matches(self, content_kind: str) -> bool:
        return content_kind == "table"

    def split(self, document: Document) -> tuple[list, bool]:
        return _table_aware_nodes(
            document, current_rag_policy().tokens.chunk_target
        ), False


class MarkdownSplitter:
    id = "markdown"
    chunk_type = "text"

    def matches(self, content_kind: str) -> bool:
        return content_kind == "markdown"

    def split(self, document: Document) -> tuple[list, bool]:
        return MarkdownNodeParser().get_nodes_from_documents([document]), False


class JsonSplitter:
    id = "json"
    chunk_type = "text"

    def matches(self, content_kind: str) -> bool:
        return content_kind == "json"

    def split(self, document: Document) -> tuple[list, bool]:
        return JSONNodeParser().get_nodes_from_documents([document]), False


# .c reuses the cpp grammar (existing behaviour).
_CODE_LANGS = {".py": "python", ".java": "java", ".cpp": "cpp", ".c": "cpp"}


class CodeSplitter:
    id = "code"
    chunk_type = "code"

    def matches(self, content_kind: str) -> bool:
        return content_kind == "code"

    def split(self, document: Document) -> tuple[list, bool]:
        from pathlib import Path

        ext = Path(document.metadata.get("file_name", "").lower()).suffix
        nodes = _code_splitter(_CODE_LANGS[ext]).get_nodes_from_documents([document])
        return nodes, False


class SentenceSplitterStrategy:
    """Default fallback (matches everything): most-conservative QA-prefix
    grouping when the text is a paired Q/A bank, else recursive sentence split."""

    id = "sentence"
    chunk_type = "text"

    def matches(self, content_kind: str) -> bool:
        return True  # catch-all floor

    def split(self, document: Document) -> tuple[list, bool]:
        qa_nodes = _qa_aware_nodes(document)
        if qa_nodes is not None:
            return qa_nodes, True
        budget = current_rag_policy().tokens
        splitter = SentenceSplitter(
            chunk_size=budget.chunk_target,
            chunk_overlap=budget.chunk_overlap,
        )
        return splitter.get_nodes_from_documents([document]), False


# Order matters: the first matching strategy wins; SentenceSplitterStrategy is
# the catch-all floor (matches() is always True), so the list is never empty.
SPLITTERS: list[Splitter] = [
    TableSplitter(),
    MarkdownSplitter(),
    JsonSplitter(),
    CodeSplitter(),
    SentenceSplitterStrategy(),
]


def select_splitter(content_kind: str) -> Splitter:
    """Pick the chunking strategy for a document (first match; sentence floor)."""
    for splitter in SPLITTERS:
        if splitter.matches(content_kind):
            return splitter
    return SPLITTERS[-1]


_MD_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)")


def _heading_annotations(node, splitter_id: str) -> tuple[list[str], str | None]:
    if splitter_id != "markdown":
        return [], None
    metadata = getattr(node, "metadata", None) or {}
    heading_path = [
        value for value in str(metadata.get("header_path") or "").split("/") if value
    ]
    first_line = node.get_content().lstrip().split("\n", 1)[0]
    match = _MD_HEADER_RE.match(first_line)
    return heading_path, match.group(1).strip() if match else None


def _node_start(node, source: str, cursor: int) -> int:
    canonical_start = (getattr(node, "metadata", None) or {}).get("_canonical_start")
    if isinstance(canonical_start, int) and canonical_start >= 0:
        return canonical_start
    start = getattr(node, "start_char_idx", None)
    if isinstance(start, int) and start >= 0:
        return start
    text = node.get_content().strip()
    found = source.find(text, cursor)
    if found < 0:
        found = source.find(text)
    return max(found, cursor)


def _page_range(
    spans: list[PageSpan],
    start: int,
    end: int,
) -> tuple[int | None, int | None]:
    pages = [
        span.page for span in spans if start < span.char_end and end > span.char_start
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def _largest_fitting_end(text: str, start: int, limit: int) -> int:
    low, high = start + 1, len(text)
    best = low
    while low <= high:
        middle = (low + high) // 2
        if count_tokens(text[start:middle]) <= limit:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    if best < len(text):
        floor = start + max(1, (best - start) * 3 // 4)
        matches = list(re.finditer(r"\n\n|\n|[。！？.!?]\s+|\s+", text[floor:best]))
        if matches:
            best = floor + matches[-1].end()
    return best


def _overlap_start(text: str, start: int, end: int, overlap: int) -> int:
    if overlap <= 0:
        return end
    low, high = start, end
    best = end
    while low <= high:
        middle = (low + high) // 2
        if count_tokens(text[middle:end]) <= overlap:
            best = middle
            high = middle - 1
        else:
            low = middle + 1
    return best if best > start else end


def _split_to_budget(node, *, limit: int, overlap: int) -> list:
    text = node.get_content()
    if count_tokens(text) <= limit:
        return [node]
    from llama_index.core.schema import TextNode

    nodes: list[TextNode] = []
    start = 0
    while start < len(text):
        end = _largest_fitting_end(text, start, limit)
        piece = text[start:end].strip()
        if piece:
            nodes.append(TextNode(text=piece, metadata=dict(node.metadata)))
        if end >= len(text):
            break
        next_start = _overlap_start(text, start, end, min(overlap, limit // 4))
        start = next_start if next_start > start else end
    return nodes


def chunk_document(
    canonical: CanonicalDocument,
    *,
    metadata: dict,
    document_title: str | None = None,
) -> list:
    """Split every supported format through one token-budgeted final gate."""
    document = Document(text=canonical.text, metadata=metadata)
    splitter = select_splitter(canonical.content_kind)
    primary_nodes, qa_regex_hit = splitter.split(document)
    policy = current_rag_policy().tokens

    nodes: list = []
    primary_cursor = 0
    for primary in primary_nodes:
        primary_start = _node_start(primary, canonical.text, primary_cursor)
        primary_cursor = max(primary_cursor, primary_start + len(primary.get_content()))
        heading_path, section_title = _heading_annotations(primary, splitter.id)
        prefix = build_retrieval_text(
            "",
            document_title=document_title,
            section_title=section_title,
            heading_path=heading_path,
        )
        content_limit = max(32, policy.passage_limit - count_tokens(prefix))
        split_nodes = _split_to_budget(
            primary,
            limit=min(policy.chunk_target, content_limit),
            overlap=policy.chunk_overlap,
        )
        local_cursor = 0
        primary_text = primary.get_content()
        for node in split_nodes:
            local_start = _node_start(node, primary_text, local_cursor)
            local_cursor = max(local_cursor, local_start + len(node.get_content()))
            node.metadata["_canonical_start"] = primary_start + local_start
            node.metadata["heading_path"] = heading_path or None
            node.metadata["section_title"] = section_title
            nodes.append(node)

    cursor = 0
    profile = {
        "chunk_target": policy.chunk_target,
        "chunk_overlap": policy.chunk_overlap,
        "passage_limit": policy.passage_limit,
        "tokenizer": "embedding",
        "qa_regex_hit": qa_regex_hit,
    }
    for node in nodes:
        text = node.get_content()
        start = _node_start(node, canonical.text, cursor)
        end = start + len(text)
        cursor = max(cursor, end)
        page_start, page_end = _page_range(canonical.page_spans, start, end)
        node.metadata.update(metadata)
        node.metadata["token_count"] = count_tokens(text)
        node.metadata["splitter_id"] = splitter.id
        node.metadata["chunk_type"] = splitter.chunk_type
        node.metadata["splitter_profile"] = profile
        node.metadata["cleaning_profile"] = canonical.cleaning_profile
        node.metadata["parser_id"] = canonical.parser_id
        node.metadata["parser_profile"] = canonical.parser_profile
        node.metadata["ocr_used"] = canonical.ocr_used
        if page_start is not None:
            node.metadata["page_start"] = page_start
            node.metadata["page_end"] = page_end

        retrieval_text = build_retrieval_text(
            text,
            document_title=document_title,
            section_title=node.metadata.get("section_title"),
            heading_path=node.metadata.get("heading_path"),
        )
        if count_tokens(retrieval_text) > policy.passage_limit:
            raise ValueError("chunk exceeds the configured reranker passage budget")
    return nodes


__all__ = ["chunk_document", "select_splitter"]
