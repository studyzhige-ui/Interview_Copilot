"""Canonical token counter for the context path.

Owns the single tokenization implementation shared by both layers: the L1
chat pipeline (`context_assembly_pipeline.count_tokens` re-exports this) and
the L2 agent loop. (The voice/analysis subsystem still rolls its own; that
consolidation is tracked separately.)

Intentionally dependency-light — it imports only ``tiktoken`` and the
standard library — so it can be imported from any layer (L1
``services.chat`` or L2 ``agent_runtime``) without creating an import cycle.

Message assembly is NOT here: both L1 and L2 build their prompt through the
shared ``ContextAssemblyPipeline`` / ``SLOT_ORDER`` (L2 just supplies a
different system-prompt slot that includes the tool manifest).
"""

try:
    import tiktoken

    _tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001 - tiktoken is optional at boot / offline
    _tokenizer = None


def token_count(text: str) -> int:
    """Return the token count of *text* using the cl100k_base tokenizer.

    Falls back to a byte heuristic (``utf-8 bytes // 3``) when tiktoken is
    unavailable, matching the prior pipeline behavior so token budgets stay
    consistent across boots with and without tiktoken installed.
    """
    if not text:
        return 0
    if _tokenizer is None:
        return len(text.encode("utf-8")) // 3
    return len(_tokenizer.encode(text))
