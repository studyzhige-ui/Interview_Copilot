"""Agent adapter for the shared Codex-style context window lifecycle."""

from __future__ import annotations

import asyncio
from app.core.context_budget import RequestBudget, request_tokens, ContextCapacityError
from app.conversation.context_window import admit, compact, item


class ActiveTurnContextReducer:
    def __init__(
        self,
        profile,
        user_id=None,
        *,
        task_anchor=None,
        tool_schemas=None,
        turn_id=None,
        output_tokens=None,
    ):
        self.profile = profile
        self.user_id = user_id
        self.task_anchor = task_anchor
        self.tool_schemas = list(tool_schemas or [])
        self.turn_id = turn_id
        self.output_tokens = output_tokens or min(4096, profile.max_output_tokens)
        budget = RequestBudget.resolve(profile.context_window, self.output_tokens)
        self.request_budget = budget
        self.cheap_prepass_threshold = budget.compact_at
        self.blocking_limit = budget.input_limit
        self.has_attempted_reactive_compact = False
        self._usage_prompt_tokens = None
        self._usage_request_estimate = None
        self.client = None
        self.assembled = None
        self.initial_context = []
        self.runtime_state = None
        self.dispatch_generation = 0
        self.checkpoint_version = 0
        self.covered_call_ids = set()

    def _measure_tokens(self, messages):
        estimate = request_tokens(messages, self.tool_schemas)
        if self._usage_prompt_tokens is None:
            return estimate
        return max(
            1, self._usage_prompt_tokens + estimate - self._usage_request_estimate
        )

    def is_at_blocking_limit(self, prompt_tokens):
        return prompt_tokens >= self.blocking_limit

    def should_compact(self, prompt_tokens):
        return prompt_tokens >= self.cheap_prepass_threshold

    async def compress(self, messages):
        projected = admit(messages)
        prefix = request_tokens(
            [m for m in projected if m.get("role") == "system"], self.tool_schemas
        )
        if self.request_budget.should_compact(self._measure_tokens(projected), prefix):
            projected = await self._compact(projected)
        return projected, self.is_at_blocking_limit(self._measure_tokens(projected))

    async def _compact(self, messages):
        if self.client is None:
            from app.core.llm_client_factory import build_provider_client_for_role

            self.client, _ = await build_provider_client_for_role(
                "primary", user_id=self.user_id
            )
        replacement, report = await compact(
            messages,
            client=self.client,
            profile=self.profile,
            output_tokens=self.output_tokens,
        )
        # The active task is exact, not the possibly clipped retained-user slice.
        anchor_id = (self.task_anchor or {}).get("_context", {}).get("id")
        if self.task_anchor is not None:
            replacement = [
                m
                for m in replacement
                if not (anchor_id and m.get("_context", {}).get("id") == anchor_id)
            ]
            insertion = max(1, len(replacement) - 1)  # before final summary
            replacement[insertion:insertion] = [*self.initial_context, self.task_anchor]
        if self.runtime_state:
            replacement.insert(
                len(replacement) - 1,
                item({"role": "user", "content": self.runtime_state}, "runtime_state"),
            )
        anchor_index = next(
            (
                i
                for i, m in enumerate(messages)
                if anchor_id and m.get("_context", {}).get("id") == anchor_id
            ),
            len(messages),
        )
        covered = self.covered_call_ids | {
            str(m.get("tool_call_id"))
            for m in messages[anchor_index + 1 :]
            if m.get("role") == "tool"
        }
        if self.assembled is not None and self.turn_id:
            from app.conversation import context_store

            saved = await asyncio.to_thread(
                context_store.save,
                self.assembled.conversation_id,
                scope=self.turn_id,
                expected_version=self.checkpoint_version,
                through_seq=self.assembled.through_seq,
                state={
                    "messages": [m for m in replacement if m.get("role") != "system"],
                    "covered_call_ids": sorted(covered),
                    "compaction": report,
                },
                turn_id=self.turn_id,
                dispatch_generation=self.dispatch_generation,
                replace=True,
            )
            if not saved:
                raise ContextCapacityError(
                    "上下文执行版本已变化，已保留原始工具记录，请重试。"
                )
            self.checkpoint_version = saved["version"]
            self.assembled.context_report["compaction"] = report
        self.covered_call_ids = covered
        self._usage_prompt_tokens = None
        self._usage_request_estimate = None
        return replacement

    async def on_context_too_long(self, messages):
        if self.has_attempted_reactive_compact:
            return messages, False
        self.has_attempted_reactive_compact = True
        return await self._compact(admit(messages)), True

    def observe_provider_prompt_tokens(self, prompt_tokens, messages):
        if prompt_tokens > 0:
            self._usage_prompt_tokens = int(prompt_tokens)
            self._usage_request_estimate = request_tokens(messages, self.tool_schemas)

    def mark_consumed(self, messages):
        # Retained as loop observation hook; output admission no longer depends
        # on a per-tool read-once whitelist.
        pass

    def reset_circuit_breaker(self):
        self.has_attempted_reactive_compact = False

    @staticmethod
    def _sanitize_tool_pairs(messages):
        from app.core.context_messages import normalize_tool_pairs

        return normalize_tool_pairs(messages)
