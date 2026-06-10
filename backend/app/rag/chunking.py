"""Chunk stage (Phase E4) — content-type Splitter strategies + a registry.

``ingestion.get_optimal_nodes`` selects a Splitter by content type, the strategy
produces the primary nodes, then the shared oversize gate + annotation run back
in ingestion. This replaces the previous if/elif branch.

There is deliberately NO HTML strategy: the parse stage emits Markdown for HTML
(``HtmlParser``/Docling), so HTML flows through the markdown strategy; a stray
plain-text HTML (lightweight fallback failure) falls to the sentence strategy.
Feeding tag-stripped text to HTMLNodeParser yields zero nodes — silent loss.
"""
from __future__ import annotations

import os
import re
from typing import Protocol, runtime_checkable

from llama_index.core import Document
from llama_index.core.node_parser import (
    CodeSplitter as _LlamaCodeSplitter,
    JSONNodeParser,
    MarkdownNodeParser,
    SentenceSplitter,
)

# BGE-M3 推荐 chunk 在 512 tokens 内以获得最佳 embedding 语义密度。
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64


# ── Splitter contract ────────────────────────────────────────────────────────


@runtime_checkable
class Splitter(Protocol):
    """A content-type chunking strategy. ``id`` / ``chunk_type`` are stamped as
    diagnostics; ``matches`` decides whether this strategy claims a document;
    ``split`` returns ``(nodes, qa_regex_hit)`` (qa_regex_hit only ever True for
    the sentence strategy's QA grouping — plan §4.4.3)."""

    id: str
    chunk_type: str

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool: ...

    def split(self, document: Document) -> tuple[list, bool]: ...


# ── Moved chunking helpers (verbatim from ingestion) ─────────────────────────


def _table_aware_nodes(document: Document, char_budget: int) -> list:
    """Split CSV/XLSX-extracted text into row-group chunks, repeating the
    header in each chunk so a single retrieved chunk stays self-describing."""
    from llama_index.core.schema import TextNode

    lines = [ln for ln in (document.text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0]
    body = lines[1:] or [header]
    nodes: list = []
    buf: list[str] = []
    size = len(header)
    for row in body:
        if buf and size + len(row) > char_budget:
            nodes.append(TextNode(text=header + "\n" + "\n".join(buf), metadata=dict(document.metadata)))
            buf, size = [], len(header)
        buf.append(row)
        size += len(row) + 1
    if buf:
        nodes.append(TextNode(text=header + "\n" + "\n".join(buf), metadata=dict(document.metadata)))
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
        language=language, chunk_lines=40, chunk_lines_overlap=5, parser=parser,
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

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool:
        return file_name.endswith((".csv", ".tsv", ".xlsx", ".xls"))

    def split(self, document: Document) -> tuple[list, bool]:
        # CHUNK_SIZE*2 is a CHARACTER budget here (rows are short); the doubling
        # is a rough token→char allowance, not a token count. The oversize gate
        # back in ingestion re-splits by real tokens, so this only sets row-group
        # granularity. Don't "fix" this to a token count.
        return _table_aware_nodes(document, CHUNK_SIZE * 2), False


class MarkdownSplitter:
    id = "markdown"
    chunk_type = "text"

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool:
        return (
            is_markdown_parsed
            or file_name.endswith((".md", ".markdown"))
            or source_kind == "improved_qa"  # saved QA content_text is Markdown
        )

    def split(self, document: Document) -> tuple[list, bool]:
        return MarkdownNodeParser().get_nodes_from_documents([document]), False


class JsonSplitter:
    id = "json"
    chunk_type = "text"

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool:
        return file_name.endswith(".json")

    def split(self, document: Document) -> tuple[list, bool]:
        return JSONNodeParser().get_nodes_from_documents([document]), False


# .c reuses the cpp grammar (existing behaviour).
_CODE_LANGS = {".py": "python", ".java": "java", ".cpp": "cpp", ".c": "cpp"}


class CodeSplitter:
    id = "code"
    chunk_type = "code"

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool:
        return os.path.splitext(file_name)[1] in _CODE_LANGS

    def split(self, document: Document) -> tuple[list, bool]:
        ext = os.path.splitext(document.metadata.get("file_name", "").lower())[1]
        nodes = _code_splitter(_CODE_LANGS[ext]).get_nodes_from_documents([document])
        return nodes, False


class SentenceSplitterStrategy:
    """Default fallback (matches everything): most-conservative QA-prefix
    grouping when the text is a paired Q/A bank, else recursive sentence split."""

    id = "sentence"
    chunk_type = "text"

    def matches(self, file_name: str, source_kind: str, is_markdown_parsed: bool) -> bool:
        return True  # catch-all floor

    def split(self, document: Document) -> tuple[list, bool]:
        qa_nodes = _qa_aware_nodes(document)
        if qa_nodes is not None:
            return qa_nodes, True
        splitter = SentenceSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
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


def select_splitter(file_name: str, source_kind: str, is_markdown_parsed: bool) -> Splitter:
    """Pick the chunking strategy for a document (first match; sentence floor)."""
    for splitter in SPLITTERS:
        if splitter.matches(file_name, source_kind, is_markdown_parsed):
            return splitter
    return SPLITTERS[-1]
