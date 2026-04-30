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
    knowledge_chunks: list[dict] = field(default_factory=list)
    current_query: str = ""
    context_text: str = ""
    total_tokens: int = 0


@dataclass
class ContextBundle:
    working_state: dict = field(default_factory=dict)
    interview_state: dict = field(default_factory=dict)
    recent_turns: list[dict] = field(default_factory=list)
    relevant_memories: list[dict] = field(default_factory=list)
    knowledge_chunks: list[dict] = field(default_factory=list)
    current_query: str = ""


class TokenBudgeter:
    RECENT_TURNS_TOKEN_BUDGET = 4000
    MEMORY_TOKEN_BUDGET = 1600
    KNOWLEDGE_TOKEN_BUDGET = 5000

    def trim_messages(self, messages: list[dict], budget: int | None = None) -> list[dict]:
        budget = budget or self.RECENT_TURNS_TOKEN_BUDGET
        total = 0
        cutoff_index = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            tokens = count_tokens(messages[index]["content"])
            if total + tokens > budget:
                cutoff_index = index + 1
                break
            total += tokens
        else:
            cutoff_index = 0
        return messages[cutoff_index:]

    def trim_items(
        self,
        items: list[dict],
        *,
        content_key: str,
        budget: int,
    ) -> list[dict]:
        selected: list[dict] = []
        total = 0
        for item in items:
            tokens = count_tokens(str(item.get(content_key) or ""))
            if selected and total + tokens > budget:
                break
            selected.append(item)
            total += tokens
        return selected


class PromptRenderer:
    def render_answer_prompt(self, bundle: ContextBundle, *, system_rules: str) -> str:
        parts = [system_rules.strip()]
        parts.extend(self._render_state(bundle))
        if bundle.relevant_memories:
            parts.append("[Long-term Memories]\n" + self._render_memories(bundle.relevant_memories))
        if bundle.knowledge_chunks:
            parts.append("[Retrieved Knowledge]\n" + self._render_knowledge(bundle.knowledge_chunks))
        if bundle.recent_turns:
            parts.append("[Recent Turns]\n" + self._render_recent_turns(bundle.recent_turns))
        parts.append("[Current Query]\n" + bundle.current_query.strip())
        return "\n\n".join(part for part in parts if part.strip())

    def render_context_text(self, bundle: ContextBundle) -> str:
        parts = []
        parts.extend(self._render_state(bundle))
        if bundle.relevant_memories:
            parts.append("[Long-term Memories]\n" + self._render_memories(bundle.relevant_memories))
        if bundle.recent_turns:
            parts.append("[Recent Turns]\n" + self._render_recent_turns(bundle.recent_turns))
        if bundle.knowledge_chunks:
            parts.append("[Retrieved Knowledge]\n" + self._render_knowledge(bundle.knowledge_chunks))
        parts.append("[Current Query]\n" + bundle.current_query.strip())
        return "\n\n".join(part for part in parts if part.strip())

    def _render_state(self, bundle: ContextBundle) -> list[str]:
        return [
            "[Working State]\n" + json.dumps(bundle.working_state, ensure_ascii=False, indent=2),
            "[Interview State]\n" + json.dumps(bundle.interview_state, ensure_ascii=False, indent=2),
        ]

    def _render_memories(self, memories: list[dict]) -> str:
        lines = []
        for index, memory in enumerate(memories, start=1):
            line = (
                f"[M{index}] [{memory.get('type', 'memory')}] "
                f"{memory.get('description', '')}: {memory.get('content', '')}"
            )
            if memory.get("staleness_note"):
                line += f" ({memory['staleness_note']})"
            lines.append(line)
        return "\n".join(lines)

    def _render_knowledge(self, chunks: list[dict]) -> str:
        lines = []
        for index, chunk in enumerate(chunks, start=1):
            source = chunk.get("source_type") or chunk.get("source") or "knowledge"
            score = chunk.get("score")
            score_text = f" score={float(score):.3f}" if score is not None else ""
            lines.append(f"[K{index}] [{source}{score_text}] {chunk.get('text', '')}")
        return "\n\n".join(lines)

    def _render_recent_turns(self, turns: list[dict]) -> str:
        return "\n".join(f"{item['role']}: {item['content']}" for item in turns)


class ContextAssemblyPipeline:
    DEFAULT_RECENT_TURNS = 10
    RECENT_TURNS_TOKEN_BUDGET = 4000

    def __init__(
        self,
        budgeter: TokenBudgeter | None = None,
        renderer: PromptRenderer | None = None,
    ):
        self.budgeter = budgeter or TokenBudgeter()
        self.renderer = renderer or PromptRenderer()

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
            knowledge_chunks=[],
            include_memories=False,
        )

    def assemble_answer_context(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
        relevant_memories: list[dict] | None = None,
        retrieved_documents: str = "",
        knowledge_chunks: list[dict] | None = None,
    ) -> AssembledContext:
        return self._assemble_common(
            session_id=session_id,
            user_id=user_id,
            current_query=current_query,
            relevant_memories=relevant_memories or [],
            retrieved_documents=retrieved_documents,
            knowledge_chunks=knowledge_chunks or [],
            include_memories=True,
        )

    def _assemble_common(
        self,
        session_id: str,
        user_id: str,
        current_query: str,
        relevant_memories: list[dict],
        retrieved_documents: str,
        knowledge_chunks: list[dict],
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
        cleaned = self._repair_pairs(
            self.budgeter.trim_messages(self._sanitize(recent_turns))
        )
        memories = self.budgeter.trim_items(
            relevant_memories if include_memories else [],
            content_key="content",
            budget=self.budgeter.MEMORY_TOKEN_BUDGET,
        )
        chunks = list(knowledge_chunks)
        if retrieved_documents:
            chunks.append(
                {
                    "id": "legacy_retrieved_documents",
                    "source_type": "retrieved",
                    "text": retrieved_documents.strip(),
                }
            )
        chunks = self.budgeter.trim_items(
            chunks,
            content_key="text",
            budget=self.budgeter.KNOWLEDGE_TOKEN_BUDGET,
        )
        bundle = ContextBundle(
            working_state=working_state,
            interview_state=interview_state,
            recent_turns=cleaned,
            relevant_memories=memories,
            knowledge_chunks=chunks,
            current_query=current_query,
        )
        context_text = self.renderer.render_context_text(bundle)
        return AssembledContext(
            working_state=working_state,
            interview_state=interview_state,
            recent_turns=cleaned,
            relevant_memories=memories,
            knowledge_chunks=chunks,
            current_query=current_query,
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

    def _repair_pairs(self, messages: list[dict]) -> list[dict]:
        repaired = list(messages)
        while repaired and repaired[0]["role"] == "Agent":
            repaired.pop(0)
        while repaired and repaired[-1]["role"] == "User":
            repaired.pop()
        return repaired


context_pipeline = ContextAssemblyPipeline()
prompt_renderer = context_pipeline.renderer
