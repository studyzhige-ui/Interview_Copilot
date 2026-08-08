"""Embedding-model token counting for ingestion (plan §4.3 / §4.5.2).

Chunk ``token_count``, oversize detection and pre-embedding length protection
must use the EMBEDDING model's tokenizer — NOT the cl100k LLM-prompt
tokenizer in ``app.core.tokens`` (that one sizes the answer
prompt budget; mixing the two was the bug §4.3 calls out).

Only the local HF embedding ships a local tokenizer. Remote providers
(openai / openai_compat) and offline/missing-model cases fall back to a
conservative char-based estimate with a one-time warning (plan §4.5.2). The
estimate deliberately over-counts a little so the oversize gate stays safe.
"""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Tri-state cache: None = not loaded yet; False = unavailable (use estimate);
# otherwise the HF tokenizer instance.
_tokenizer: Any = None
_lock = Lock()
_warned_estimate = False


def _load_tokenizer() -> Any:
    """Load the LOCAL embedding model's tokenizer, or return None when there
    isn't one (remote provider / model not downloaded / load error). Never
    triggers a network download — only an already-cached snapshot is used."""
    from app.rag.embedding_registry import resolve_embedding

    cfg = resolve_embedding()
    if cfg.provider.kind != "local_huggingface":
        return None
    try:
        from transformers import AutoTokenizer

        from app.core.hf_runtime import resolve_local_snapshot

        path = resolve_local_snapshot(cfg.model)
        if not path:
            return None
        return AutoTokenizer.from_pretrained(path)
    except Exception as exc:  # noqa: BLE001 — any load failure → estimate
        logger.warning("Embedding tokenizer load failed (%s); using estimate.", exc)
        return None


def _estimate_tokens(text: str) -> int:
    """Conservative fallback: ~1 token per character. BGE-M3 (XLM-R
    sentencepiece) is ~1-1.5 tokens/CJK-char and under 1 for latin words, so
    char count is a safe over-estimate for the oversize gate."""
    return len(text)


def count_tokens(text: str) -> int:
    """Embedding-tokenizer token count, with a char-based estimate fallback."""
    global _tokenizer, _warned_estimate
    if not text:
        return 0
    if _tokenizer is None:
        with _lock:
            if _tokenizer is None:
                loaded = _load_tokenizer()
                _tokenizer = loaded if loaded is not None else False
    if _tokenizer is False:
        if not _warned_estimate:
            logger.warning(
                "No local embedding tokenizer; chunk token_count uses a "
                "char-based estimate.",
            )
            _warned_estimate = True
        return _estimate_tokens(text)
    return len(_tokenizer.encode(text, add_special_tokens=False))


def reset_cache() -> None:
    """Drop the cached tokenizer — for tests, and after an embedding-model
    change (the embedding identity changing implies a different tokenizer)."""
    global _tokenizer, _warned_estimate
    with _lock:
        _tokenizer = None
        _warned_estimate = False


__all__ = ["count_tokens", "reset_cache"]
