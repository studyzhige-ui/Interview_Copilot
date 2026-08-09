"""Coverage-aware evidence allocation into the answer prompt budget."""

from __future__ import annotations

import json
from typing import Any

from app.core.tokens import token_count, truncate_to_tokens
from app.rag.domain.models import GroundingBundle, RetrievalResult
from app.rag.grounding.evidence import missing_terms_by_intent


class GroundingBuilder:
    @staticmethod
    def _coverage_first(result: RetrievalResult) -> list[dict[str, Any]]:
        ordered: list[dict[str, Any]] = []
        selected_ids: set[str] = set()
        for intent in result.intents:
            candidate = next(
                (
                    chunk
                    for chunk in result.chunks
                    if intent.intent_id in chunk.get("intent_ids", [])
                ),
                None,
            )
            if candidate is not None:
                node_id = str(candidate.get("node_id") or "")
                if node_id not in selected_ids:
                    ordered.append(candidate)
                    selected_ids.add(node_id)
        ordered.extend(
            chunk
            for chunk in result.chunks
            if str(chunk.get("node_id") or "") not in selected_ids
        )
        return ordered

    @staticmethod
    def _header(ref: str, chunk: dict[str, Any]) -> str:
        attributes = [f"ref={ref}"]
        for name, key in (
            ("title", "document_title"),
            ("section", "section_title"),
        ):
            value = chunk.get(key)
            if value:
                attributes.append(
                    f"{name}={json.dumps(str(value), ensure_ascii=False)}"
                )
        page_start, page_end = chunk.get("page_start"), chunk.get("page_end")
        if page_start is not None:
            attributes.append(
                f"page={page_start}-{page_end}"
                if page_end is not None and page_end != page_start
                else f"page={page_start}"
            )
        if chunk.get("chunk_index") is not None:
            attributes.append(f"chunk={chunk['chunk_index']}")
        if chunk.get("score") is not None:
            attributes.append(f"score={float(chunk['score']):.3f}")
        return f"[{ref}] <source {' '.join(attributes)}>"

    @staticmethod
    def _source(
        ref: str,
        chunk: dict[str, Any],
        rendered_text: str,
        *,
        truncated: bool,
    ) -> dict[str, Any]:
        source = {
            "ref": ref,
            "chunk_id": chunk.get("chunk_id"),
            "node_id": chunk.get("node_id"),
            "document_id": chunk.get("document_id"),
            "document_title": chunk.get("document_title"),
            "file_name": chunk.get("file_name"),
            "category": chunk.get("category"),
            "source_kind": chunk.get("source_kind"),
            "page_start": chunk.get("page_start"),
            "page_end": chunk.get("page_end"),
            "section_title": chunk.get("section_title"),
            "heading_path": chunk.get("heading_path"),
            "chunk_index": chunk.get("chunk_index"),
            "score": chunk.get("score"),
            "score_source": chunk.get("score_source"),
            "intent_ids": list(chunk.get("intent_ids", [])),
            "text_preview": rendered_text[:200],
        }
        if truncated:
            source["truncated"] = True
        return source

    def build(self, result: RetrievalResult, *, token_budget: int) -> GroundingBundle:
        if not result.chunks or token_budget <= 0:
            return GroundingBundle(
                supported=not result.intents,
                missing_intent_ids=[intent.intent_id for intent in result.intents],
            )

        included: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        parts: list[str] = []
        for chunk in self._coverage_first(result):
            text = str(chunk.get("text") or "").strip()
            if not text:
                continue
            ref = f"K{len(sources) + 1}"
            header = self._header(ref, chunk)
            existing = "\n\n".join(parts)
            separator = "\n\n" if parts else ""
            remaining = token_budget - token_count(existing + separator)
            prefix = f"{header}\n<untrusted_evidence>\n"
            suffix = "\n</untrusted_evidence>"
            overhead = token_count(prefix + suffix)
            if overhead >= remaining and not included:
                # Preserve a usable first citation even under a deliberately
                # tiny budget; provenance remains in the side-channel source.
                prefix = f"[{ref}]\n<evidence>\n"
                suffix = "\n</evidence>"
                overhead = token_count(prefix + suffix)
            if overhead >= remaining:
                break
            text_tokens = token_count(text)
            truncated = text_tokens > remaining - overhead
            if truncated:
                text = truncate_to_tokens(text, remaining - overhead)
                text_tokens = token_count(text)
            rendered = f"{prefix}{text}{suffix}"
            proposed = existing + separator + rendered
            while text and token_count(proposed) > token_budget:
                text = truncate_to_tokens(text, max(0, token_count(text) - 1))
                rendered = f"{prefix}{text}{suffix}"
                proposed = existing + separator + rendered
            if not text:
                break
            copied = {**chunk, "text": text}
            included.append(copied)
            sources.append(self._source(ref, copied, text, truncated=truncated))
            parts.append(rendered)

        covered = list(
            dict.fromkeys(
                intent_id
                for chunk in included
                for intent_id in chunk.get("intent_ids", [])
            )
        )
        missing_intents = [
            intent.intent_id
            for intent in result.intents
            if intent.intent_id not in covered
        ]
        missing_terms = missing_terms_by_intent(result.intents, included)
        context_text = "\n\n".join(parts)
        return GroundingBundle(
            context_text=context_text,
            included_chunks=included,
            sources=sources,
            covered_intent_ids=covered,
            missing_intent_ids=missing_intents,
            missing_terms=missing_terms,
            supported=not missing_intents and not missing_terms,
            token_count=token_count(context_text),
        )


grounding_builder = GroundingBuilder()


__all__ = ["GroundingBuilder", "grounding_builder"]
