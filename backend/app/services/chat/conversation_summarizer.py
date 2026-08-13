"""Conversation-summary core shared by chat and agent context compaction."""

import json
import logging
import re

from app.core.llm_client_factory import get_internal_llm
from app.core.tokens import token_count, truncate_to_tokens
from app.prompts.chat import CONVERSATION_COMPACTION_PROMPT

logger = logging.getLogger(__name__)

SUMMARY_MAX_TOKENS = 2_500


def _extract_json_payload(raw_text: str) -> dict:
    text = str(raw_text or "").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(1))
    return value if isinstance(value, dict) else {}


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
    if token_count(new_summary) > SUMMARY_MAX_TOKENS:
        new_summary = truncate_to_tokens(new_summary, SUMMARY_MAX_TOKENS)
    return new_summary


__all__ = ["SUMMARY_MAX_TOKENS", "summarize_conversation"]
