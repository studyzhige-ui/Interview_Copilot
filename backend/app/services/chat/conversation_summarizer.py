"""Conversation-summary core shared by chat and agent context compaction."""

import logging

from app.core.llm_client_factory import get_internal_llm
from app.prompts.chat import CONVERSATION_COMPACTION_PROMPT
from app.services.chat.context_assembly_pipeline import count_tokens
from app.services.memory._json_payload import _extract_json_payload

logger = logging.getLogger(__name__)

SUMMARY_MAX_TOKENS = 2_500


async def summarize_conversation(
    old_summary: str,
    conversation: str,
    *,
    user_id: str | None = None,
) -> str:
    """Incrementally summarize a conversation for later context assembly."""
    prompt = CONVERSATION_COMPACTION_PROMPT.format(
        old_summary=old_summary or "(无)",
        new_conversation=conversation,
    )
    try:
        response = await get_internal_llm("worker").acomplete(
            prompt,
            response_format={"type": "json_object"},
        )
        new_summary = str(
            _extract_json_payload(str(response.text)).get("summary", "")
        ).strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Conversation summarization failed: %s", exc)
        return ""
    if count_tokens(new_summary) > SUMMARY_MAX_TOKENS:
        new_summary = new_summary[:1200]
    return new_summary


__all__ = ["SUMMARY_MAX_TOKENS", "summarize_conversation"]
