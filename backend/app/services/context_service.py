import json
import logging
from dataclasses import dataclass, field

import tiktoken

from app.services.interview_state_service import interview_state_service
from app.services.state_utils import (
    default_working_state_payload,
    parse_state_blob,
)
from app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

try:
    _tokenizer = tiktoken.get_encoding("cl100k_base")
except Exception:  # noqa: BLE001
    _tokenizer = None


def count_tokens(text: str) -> int:
    if not text:
        return 0
    if _tokenizer is None:
        return len(text.encode("utf-8")) // 3
    return len(_tokenizer.encode(text))


@dataclass
class AssembledContext:
    working_state: dict = field(default_factory=dict)
    interview_state: dict = field(default_factory=dict)
    recent_turns: list[dict] = field(default_factory=list)
    relevant_memories: list[dict] = field(default_factory=list)
    context_text: str = ""
    total_tokens: int = 0


class ContextAssemblyPipeline:
    DEFAULT_RECENT_TURNS = 10
    RECENT_TURNS_TOKEN_BUDGET = 4000

    def assemble_rewrite_context(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
    ) -> AssembledContext:
        return self._assemble_common(
            session_id=session_id,
            user_id=user_id,
            current_query=current_query,
            relevant_memories=[],
            retrieved_documents="",
            include_memories=False,
        )

    def assemble_answer_context(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
        relevant_memories: list[dict] | None = None,
        retrieved_documents: str = "",
    ) -> AssembledContext:
        return self._assemble_common(
            session_id=session_id,
            user_id=user_id,
            current_query=current_query,
            relevant_memories=relevant_memories or [],
            retrieved_documents=retrieved_documents,
            include_memories=True,
        )

    def _assemble_common(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
        relevant_memories: list[dict],
        retrieved_documents: str,
        include_memories: bool,
    ) -> AssembledContext:
        meta = transcript_service.get_session_meta(session_id)
        if meta is None:
            working_state = default_working_state_payload()
            recent_turns = []
        else:
            working_state = parse_state_blob(
                meta["working_state"],
                default_working_state_payload,
            )
            recent_turns = transcript_service.get_recent_turns(
                session_id=session_id,
                max_turns=self.DEFAULT_RECENT_TURNS,
                after_seq=meta["compaction_cursor"],
            )

        interview_state = interview_state_service.get_state(session_id, user_id)
        cleaned = self._repair_pairs(self._truncate(self._sanitize(recent_turns)))
        context_text = self._render_context(
            working_state=working_state,
            interview_state=interview_state,
            recent_turns=cleaned,
            relevant_memories=relevant_memories if include_memories else [],
            retrieved_documents=retrieved_documents,
            current_query=current_query,
        )
        return AssembledContext(
            working_state=working_state,
            interview_state=interview_state,
            recent_turns=cleaned,
            relevant_memories=relevant_memories if include_memories else [],
            context_text=context_text,
            total_tokens=count_tokens(context_text),
        )

    def _sanitize(self, messages: list[dict]) -> list[dict]:
        sanitized = []
        for message in messages:
            role = str(message.get("role") or "").strip()
            content = str(message.get("content") or "").strip()
            if role not in {"User", "Agent"} or not content:
                continue
            if content.startswith("[SYSTEM_") or content.startswith("[DEBUG_"):
                continue
            sanitized.append(
                {
                    "seq": message.get("seq", 0),
                    "role": role,
                    "content": content,
                }
            )
        return sanitized

    def _truncate(self, messages: list[dict]) -> list[dict]:
        total = 0
        cutoff_index = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            tokens = count_tokens(messages[index]["content"])
            if total + tokens > self.RECENT_TURNS_TOKEN_BUDGET:
                cutoff_index = index + 1
                break
            total += tokens
        else:
            cutoff_index = 0
        return messages[cutoff_index:]

    def _repair_pairs(self, messages: list[dict]) -> list[dict]:
        repaired = list(messages)
        while repaired and repaired[0]["role"] == "Agent":
            repaired.pop(0)
        while repaired and repaired[-1]["role"] == "User":
            repaired.pop()
        return repaired

    def _render_context(
        self,
        working_state: dict,
        interview_state: dict,
        recent_turns: list[dict],
        relevant_memories: list[dict],
        retrieved_documents: str,
        current_query: str,
    ) -> str:
        parts = [
            "[Working State]\n" + json.dumps(working_state, ensure_ascii=False, indent=2),
            "[Interview State]\n" + json.dumps(interview_state, ensure_ascii=False, indent=2),
        ]
        if relevant_memories:
            memory_lines = []
            for memory in relevant_memories:
                line = (
                    f"- [{memory['type']}] {memory['description']}: "
                    f"{memory['content']}"
                )
                if memory.get("staleness_note"):
                    line += f" ({memory['staleness_note']})"
                memory_lines.append(line)
            parts.append("[Long-term Memories]\n" + "\n".join(memory_lines))
        if recent_turns:
            parts.append(
                "[Recent Turns]\n"
                + "\n".join(f"{item['role']}: {item['content']}" for item in recent_turns)
            )
        if retrieved_documents:
            parts.append("[Retrieved Knowledge]\n" + retrieved_documents.strip())
        parts.append("[Current Query]\n" + current_query.strip())
        return "\n\n".join(part for part in parts if part.strip())


context_pipeline = ContextAssemblyPipeline()
