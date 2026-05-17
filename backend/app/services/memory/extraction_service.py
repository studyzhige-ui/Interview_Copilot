"""Memory extraction — distills durable facts from new conversation turns.

Two memory types live side-by-side under fundamentally different storage:

* **user_profile** — single markdown doc in ``users.user_profile_doc``,
  updated via LLM-returned **patch list**. See
  :mod:`app.services.memory.user_profile_doc_service` for the rationale
  (semantic dedup that ``normalized_key`` rules couldn't achieve).

* **interview_fact** — multi-row in ``memory_items`` table, dedup'd by
  ``(user_id, type, normalized_key)``. Volume can grow large per user
  (one row per interview discussion point), so the per-update payload
  has to stay compact — loading "all facts" into a prompt isn't viable.

Both branches run on every post-turn maintenance pass. The user_profile
branch is intentionally not throttled — its prompt is small (current doc
is bounded by the LLM's update discipline) and the benefit is the
profile staying in lock-step with the conversation.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.memory import MemoryItem
from app.rag.embeddings import agent_fast_llm
from app.services.memory._json_payload import _extract_json_payload, _normalize_key
from app.services.memory.user_profile_doc_service import (
    apply_patches as apply_profile_patches,
    load as load_profile_doc,
)
from app.services.memory.vector_service import memory_vector_service

logger = logging.getLogger(__name__)


_PROFILE_PATCH_PROMPT = """你正在维护用户「{user_id}」的画像档案。档案是一份 markdown 文本，每行是一条事实，行首都以 "- " 开头。

**当前画像档案（不要重写整份，只输出 patch list）：**
```
{current_doc}
```

**新的对话内容：**
```
{conversation}
```

**任务**：基于新对话里出现的关于该用户的事实，输出一个 JSON 数组形式的 patch list。每个 patch 是一个对象：

- `{{"op":"add","new_line":"- 工作年限：3 年"}}` — 追加一条新事实。当画像里没有等价信息时才发，避免重复。
- `{{"op":"update","match_line":"- 工作年限：2 年","new_line":"- 工作年限：3 年"}}` — 把现有的某行替换。`match_line` 必须是当前档案里**逐字符**存在的一行。
- `{{"op":"delete","match_line":"- 目标岗位：前端"}}` — 删除某行。`match_line` 必须是当前档案里逐字符存在的一行。

**铁律**：
1. 只输出 patch list 的 JSON 数组，**不要**输出任何解释或包装文字。
2. 没有变化时，输出空数组 `[]`。
3. **不允许**修改、删除、或重写新对话里没有明确涉及的行——它们必须按原文逐字符保留在档案里。
4. `add` 之前先检查档案里是否已有同等含义的行（即便表述不同），有就改用 `update` 或者干脆跳过。
5. 涉及用户的事实（姓名 / 技术栈 / 目标岗位 / 工作年限 / 准备方向等）才纳入。一次性的 UI 偏好、临时讨论的技术问题不要纳入。

输出：
"""


_INTERVIEW_FACT_PROMPT = """Review the conversation and extract durable interview_fact memories.

These capture WHAT was discussed in an interview and WHAT the user learned.
Content format: "[date if known] [interview title]: [topic], [what happened / was learned], [score if available]"
normalized_key format: "ivf_[topic_snake_case]" (e.g. "ivf_redis_persistence", "ivf_tcp_handshake")

Rules:
- Extract when the conversation discusses a specific interview question or technical topic from an interview
- Include both what was discussed AND the conclusion or learning
- If the user corrected a misunderstanding during review, note the updated understanding
- If a score or evaluation is mentioned, include it
- Never extract user_profile data (name, role, tech stack) — that's handled by a different pipeline
- Never extract generic technical knowledge unrelated to a specific interview

Return a JSON array. Each item:
- type: must be "interview_fact"
- description: short label (max 50 chars)
- normalized_key: snake_case identifier for dedup
- content: the fact (1-2 sentences)
- confidence: 0.0-1.0

If nothing qualifies, return [].

Conversation:
{conversation}
"""


class MemoryExtractionService:
    MIN_CONFIDENCE = 0.65

    async def extract_and_merge(
        self,
        session_id: str,
        user_id: str,
        new_messages: list[dict],
    ) -> list[dict] | None:
        if not new_messages:
            return []
        conversation = "\n".join(
            f"{item['role']}: {item['content']}" for item in new_messages
        )

        persisted: list[dict] = []

        # ── Branch 1: user_profile (patch-based, single-doc) ───────────
        try:
            profile_result = await self._update_user_profile(
                user_id=user_id, conversation=conversation,
            )
            persisted.extend(profile_result)
        except Exception as exc:  # noqa: BLE001 — never break the chat pipeline
            logger.error(
                "user_profile patch pipeline failed for user=%s session=%s: %s",
                user_id, session_id, exc,
            )
            # Fall through — partial success is still success.

        # ── Branch 2: interview_fact (multi-row, normalized_key dedup) ─
        try:
            iv_result = await self._extract_interview_facts(
                session_id=session_id,
                user_id=user_id,
                conversation=conversation,
                new_messages=new_messages,
            )
            if iv_result is None:
                # Hard failure on interview_fact branch — signal to caller
                # so the cursor doesn't advance and the next turn retries.
                return None
            persisted.extend(iv_result)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "interview_fact pipeline failed for user=%s session=%s: %s",
                user_id, session_id, exc,
            )
            return None

        return persisted

    # ── user_profile branch ───────────────────────────────────────────

    async def _update_user_profile(
        self,
        *,
        user_id: str,
        conversation: str,
    ) -> list[dict]:
        current = load_profile_doc(user_id)
        prompt = _PROFILE_PATCH_PROMPT.format(
            user_id=user_id,
            current_doc=current or "（档案当前为空）",
            conversation=conversation,
        )
        response = await agent_fast_llm.acomplete(prompt)
        patches = _extract_json_payload(str(response.text))
        if isinstance(patches, dict):
            # Tolerate LLMs that wrap in ``{"patches": [...]}``.
            patches = patches.get("patches") or patches.get("items") or []
        if not isinstance(patches, list) or not patches:
            return []

        stats = apply_profile_patches(user_id, patches)
        if stats.get("applied", 0) > 0 or stats.get("dropped", 0) > 0:
            logger.info(
                "user_profile patches: user=%s applied=%d dropped=%d skipped=%d",
                user_id, stats["applied"], stats["dropped"], stats["skipped"],
            )
        return [{"type": "user_profile", "patches": stats}] if stats["applied"] else []

    # ── interview_fact branch (multi-row, normalized_key dedup) ───────

    async def _extract_interview_facts(
        self,
        *,
        session_id: str,
        user_id: str,
        conversation: str,
        new_messages: list[dict],
    ) -> list[dict] | None:
        try:
            response = await agent_fast_llm.acomplete(
                _INTERVIEW_FACT_PROMPT.format(conversation=conversation),
            )
            raw_payload = _extract_json_payload(str(response.text))
            if isinstance(raw_payload, dict):
                candidates = raw_payload.get("items", raw_payload.get("memories", []))
            else:
                candidates = raw_payload
            if not isinstance(candidates, list):
                candidates = []
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "interview_fact LLM call failed for session=%s: %s", session_id, exc,
            )
            return None

        max_seq = max((item.get("seq", 0) for item in new_messages), default=0)
        persisted: list[dict] = []
        db: Session = SessionLocal()
        try:
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                if str(candidate.get("type") or "").strip() != "interview_fact":
                    continue
                confidence = float(candidate.get("confidence") or 0.0)
                if confidence < self.MIN_CONFIDENCE:
                    continue
                description = str(candidate.get("description") or "").strip()[:200]
                content = str(candidate.get("content") or "").strip()
                normalized_key = _normalize_key(
                    str(candidate.get("normalized_key") or description)
                )
                if not description or not content:
                    continue
                if len(content.encode("utf-8")) > MemoryItem.MAX_CONTENT_BYTES:
                    content = content[: MemoryItem.MAX_CONTENT_BYTES // 3]

                existing = (
                    db.query(MemoryItem)
                    .filter(
                        MemoryItem.user_id == user_id,
                        MemoryItem.type == "interview_fact",
                        MemoryItem.normalized_key == normalized_key,
                    )
                    .first()
                )
                if existing is None:
                    existing = MemoryItem(
                        user_id=user_id,
                        type="interview_fact",
                        scope="user",
                        description=description,
                        normalized_key=normalized_key,
                        content=content,
                        confidence=confidence,
                        importance=confidence,
                        embedding_status="pending",
                        source_session_id=session_id,
                        last_evidence_seq=max_seq,
                    )
                    db.add(existing)
                else:
                    existing.description = description
                    existing.content = content
                    existing.confidence = confidence
                    existing.importance = max(existing.importance or 0.5, confidence)
                    existing.embedding_status = "pending"
                    existing.source_session_id = session_id
                    existing.last_evidence_seq = max_seq
                    existing.updated_at = datetime.utcnow()

                db.flush()
                try:
                    memory_vector_service.upsert_memory(existing, db=db)
                except Exception as exc:  # noqa: BLE001
                    existing.embedding_status = "failed"
                    logger.warning("Memory vector upsert failed for %s: %s", existing.id, exc)

                persisted.append({
                    "type": "interview_fact",
                    "description": description,
                    "normalized_key": normalized_key,
                    "confidence": confidence,
                })

            db.commit()
            return persisted
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.error("interview_fact merge failed for session=%s: %s", session_id, exc)
            return None
        finally:
            db.close()


memory_extraction_service = MemoryExtractionService()


__all__ = ["MemoryExtractionService", "memory_extraction_service"]
