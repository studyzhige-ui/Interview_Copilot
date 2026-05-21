"""Backward-compatibility shim — the legacy multi-row recall path.

This module used to expose ``MemoryRetrievalService`` with vector
recall + lexical fusion over the ``memory_items`` table. That path is
retired in v3; all reads now go through
:mod:`app.services.memory.v3_context_loader`.

We keep ``MemoryRetrievalService.load_user_profile`` as a thin
adapter onto ``user_profile_doc_service`` so any remaining caller that
asks for ``list[dict]`` shape keeps working. New code should call
``user_profile_doc_service.load_as_lines`` (or
``v3_context_loader.load_universal``) directly.

The rest of the old interface (``recall_relevant`` / ``get_memory_index``
/ ``delete_memory``) is removed — those methods read/wrote the
retired ``memory_items`` table and have no place in the v3 architecture.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class MemoryRetrievalService:
    """Slim adapter onto v3 services. Preserved only to keep
    ``memory_retrieval_service.load_user_profile(user_id)`` calls
    compiling during the migration window."""

    def load_user_profile(self, user_id: str) -> list[dict]:
        """Return the user's profile as a list of fact entries.

        Source of truth is ``users.user_profile_doc`` (a single
        markdown blob). We split it into one dict per line so any
        legacy renderer that iterates ``profile`` continues to work.
        """
        from app.services.memory.user_profile_doc_service import load_as_lines

        return [
            {
                "id": f"profile_line_{idx}",
                "type": "user_profile",
                "description": line.lstrip("- ").strip(),
                "content": line.lstrip("- ").strip(),
                "normalized_key": "",
            }
            for idx, line in enumerate(load_as_lines(user_id))
        ]


memory_retrieval_service = MemoryRetrievalService()


__all__ = ["MemoryRetrievalService", "memory_retrieval_service"]
