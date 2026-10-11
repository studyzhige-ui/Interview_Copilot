"""Run admitted turns, supervise cancellation and publish committed outcomes."""

from __future__ import annotations

import asyncio
import json
import logging


from app.conversation.events import HarnessEvent
from app.conversation.application import turn_store
from app.core.config import settings
from app.core.error_messages import humanize_error
from app.conversation.application.chat_history_service import transcript_service
from app.conversation.application.product_object_reference import (
    ProductObjectReferenceUnavailableError,
)
from app.conversation.application.product_object_reference import UNAVAILABLE_MESSAGE
from app.conversation.application.product_object_reference import (
    build_product_object_context,
)
from app.conversation.application.turn_event_buffer import turn_event_buffer


logger = logging.getLogger(__name__)


async def _publish_event(turn_id: str, event_json: str) -> bool:
    """Event delivery is transient; the transcript and Turn own the outcome."""
    from redis.exceptions import RedisError

    try:
        await turn_event_buffer.append(turn_id, event_json)
        return True
    except (RedisError, ConnectionError, TimeoutError):
        logger.warning("Turn event transport unavailable: %s", turn_id)
        return False


async def execute_turn(turn_id: str) -> None:
    turn = await asyncio.to_thread(turn_store._claim, turn_id)
    if turn is None:
        return
    from app.usage.runtime import scope

    with scope(turn.user_pk, f"turn:{turn_id}", username=turn.username):
        await _execute_claimed_turn(turn_id, turn)


async def _execute_claimed_turn(turn_id: str, turn: turn_store.TurnExecution) -> None:
    done_event = None
    delivery_available = True
    failure: str | None = None
    diagnostic_error: str | None = None
    engine = None
    cancelled = False
    waiting = False
    outcome = "completed"
    waiting_reason = "interaction"
    owner_task = asyncio.current_task()
    control_failure: str | None = None

    async def emit(event_json: str) -> None:
        nonlocal delivery_available
        if not delivery_available:
            return
        envelope = json.loads(event_json)
        envelope["dispatch_generation"] = turn.dispatch_generation
        delivery_available = await _publish_event(
            turn_id, json.dumps(envelope, ensure_ascii=False)
        )

    async def watch_cancel() -> None:
        nonlocal control_failure
        while True:
            try:
                stop = await asyncio.to_thread(
                    turn_store._cancellation_requested, turn_id
                )
            except Exception:  # noqa: BLE001 - loss of the durable control plane
                logger.exception("turn cancellation control unavailable: %s", turn_id)
                control_failure = "任务控制连接已中断，请稍后重试"
                stop = True
            if stop:
                if owner_task is not None:
                    owner_task.cancel()
                return
            await asyncio.sleep(1)

    cancel_watcher = asyncio.create_task(
        watch_cancel(), name=f"chat-turn-cancel:{turn_id}"
    )

    async def maintain_heartbeat() -> None:
        while True:
            await asyncio.sleep(settings.TURN_HEARTBEAT_SECONDS)
            try:
                owned = await asyncio.to_thread(
                    turn_store._heartbeat, turn_id, turn.dispatch_generation
                )
                if not owned and owner_task is not None:
                    owner_task.cancel()
                    return
            except Exception:  # noqa: BLE001
                logger.exception("turn heartbeat failed: %s", turn_id)

    heartbeat = asyncio.create_task(
        maintain_heartbeat(),
        name=f"chat-turn-heartbeat:{turn_id}",
    )
    try:
        if turn.automation_validation_error:
            raise ValueError(turn.automation_validation_error)
        from app.conversation.engine import ConversationEngine
        from app.conversation.factory import make_agent_strategy
        from app.conversation.factory import make_chat_strategy

        strategy = (
            make_agent_strategy() if turn.mode == "agent" else make_chat_strategy()
        )
        object_reference_context = await asyncio.to_thread(
            build_product_object_context,
            user_pk=turn.user_pk,
            references=turn.object_references,
        )
        strategy_extras = {
            "execution_mode": turn.execution_mode,
            # Preserve the immutable admitted typed identities separately from
            # the server-rendered label/context projection. The Engine uses
            # this only for deterministic explicit source reads.
            "admitted_object_references": list(turn.object_references),
        }
        if turn.automation_task_id is not None:
            strategy_extras.update(
                {
                    "unattended_automation": True,
                    "builtin_tool_allowlist": turn.automation_tool_names,
                    "persistent_task_skill_refs": list(turn.automation_skill_refs),
                    "persistent_task_id": turn.automation_task_id,
                    "persistent_task_definition_version": (
                        turn.automation_definition_version
                    ),
                }
            )
        engine = ConversationEngine(
            user_id=turn.username,
            user_pk=turn.user_pk,
            session_id=turn.conversation_id,
            user_message=turn.message,
            question_indexes=turn.question_indexes,
            attachments=turn.attachments,
            product_object_context=object_reference_context,
            strategy=strategy,
            turn_id=turn_id,
            dispatch_generation=turn.dispatch_generation,
            strategy_extras=strategy_extras,
        )
        async for event in engine.submit_message():
            if event.type.value == "done":
                done_event = event
                continue
            await emit(event.to_json())
            if event.type.value == "error":
                # Error events are diagnostics, not an implicit Turn outcome.
                diagnostic_error = str(
                    event.data.get("error") or "Turn execution failed"
                )
        declared_outcome = engine.outcome
        outcome = str(declared_outcome or "completed")
        waiting = outcome == "waiting"
        if outcome == "failed":
            failure = diagnostic_error or "Turn execution failed"
        if (
            not waiting
            and not failure
            and outcome in {"completed", "blocked"}
            and not await asyncio.to_thread(turn_store._has_assistant, turn_id)
        ):
            failure = "本轮未生成有效回复"
            outcome = "failed"
    except asyncio.CancelledError:
        if control_failure is not None:
            failure = control_failure
            outcome = "failed"
        else:
            failure = "Turn cancelled"
            cancelled = True
            raise
    except Exception as exc:  # noqa: BLE001
        from app.rag.application.attachment_sources import (
            AttachmentParsingPendingError,
        )

        if isinstance(exc, AttachmentParsingPendingError):
            # The frozen Turn/AttachmentRef already exists. Release compute and
            # let the parsing worker resume this same Turn/generation lineage;
            # never create another user message or silently omit the source.
            waiting = True
            outcome = "waiting"
            waiting_reason = "attachment_parsing"
            await emit(
                HarnessEvent.status("附件仍在解析，完成后将自动继续本轮。").to_json(),
            )
        elif isinstance(exc, ProductObjectReferenceUnavailableError):
            failure = UNAVAILABLE_MESSAGE
            outcome = "failed"
            await emit(HarnessEvent.error(failure).to_json())
            # The admitted user input is already exact History. Persist the
            # deterministic read failure too, so a refresh does not erase the
            # reason this Turn failed before ConversationEngine was created.
            await asyncio.to_thread(
                transcript_service.complete_background_turn,
                turn_id=turn_id,
                ai_msg=f"⚠️ {failure}",
                expected_generation=turn.dispatch_generation,
                ai_blocks=[{"type": "text", "text": f"⚠️ {failure}"}],
            )
        else:
            failure = humanize_error(exc)
            outcome = "failed"
            logger.exception("background turn %s failed", turn_id)
            await emit(HarnessEvent.error(failure).to_json())
    finally:
        try:
            if engine is not None:
                declared_outcome = engine.outcome
                if declared_outcome is not None:
                    outcome = str(declared_outcome)
                waiting = outcome == "waiting"
                if outcome == "failed" and failure is None:
                    failure = diagnostic_error or "Turn execution failed"
            if failure and engine is not None and not cancelled and not waiting:
                await engine.persist_background_failure(failure)
        finally:
            cancel_watcher.cancel()
            heartbeat.cancel()
            await asyncio.gather(cancel_watcher, heartbeat, return_exceptions=True)
            if waiting and not cancelled and not failure:
                await asyncio.to_thread(
                    turn_store._wait,
                    turn_id,
                    waiting_reason,
                    expected_generation=turn.dispatch_generation,
                )
            else:
                finish = (
                    turn_store._finish_automation
                    if turn.automation_task_id is not None
                    else turn_store._finish
                )
                await asyncio.to_thread(
                    finish,
                    turn if turn.automation_task_id is not None else turn_id,
                    (
                        "cancelled"
                        if cancelled
                        else "failed"
                        if failure
                        else outcome
                        if outcome in {"blocked", "cancelled"}
                        else "completed"
                    ),
                    failure,
                    **(
                        {"expected_generation": turn.dispatch_generation}
                        if turn.automation_task_id is None
                        else {}
                    ),
                )

            # Commit the canonical outcome before clients receive completion
            # and reload the transcript. Redis loss is recovered via DB polling.
            emitted_outcome = (
                "cancelled"
                if cancelled
                else "failed"
                if failure
                else "waiting"
                if waiting
                else outcome
            )
            if done_event is not None:
                done_event.data["outcome"] = emitted_outcome
            await emit(
                (
                    done_event
                    or HarnessEvent.done(step=0, elapsed_ms=0, outcome=emitted_outcome)
                ).to_json(),
            )


async def fail_orphaned_turns() -> int:
    """Queued deadlines and running leases are different contracts."""
    closed = await asyncio.to_thread(turn_store._close_expired_turns)
    for turn_id, error in closed:
        await asyncio.to_thread(
            transcript_service.complete_background_turn,
            turn_id=turn_id,
            ai_msg=f"⚠️ {error}",
            ai_blocks=[{"type": "text", "text": f"⚠️ {error}"}],
        )
        await _publish_event(
            turn_id,
            HarnessEvent.error(error).to_json(),
        )
        await _publish_event(
            turn_id,
            HarnessEvent.done(
                step=0,
                elapsed_ms=0,
                outcome="failed",
            ).to_json(),
        )
    return len(closed)


async def monitor_orphaned_turns() -> None:
    interval = max(5, settings.TURN_STALE_SECONDS // 2)
    while True:
        await asyncio.sleep(interval)
        try:
            orphan_count = await fail_orphaned_turns()
            if orphan_count:
                logger.warning("Closed %d stale conversation turn(s).", orphan_count)
            from app.conversation.application.attachment_waiting_service import (
                recover_terminal_attachment_turns,
            )

            resumed = await asyncio.to_thread(
                recover_terminal_attachment_turns,
                actions=turn_store.attachment_resume_actions(),
            )
            if resumed:
                logger.info(
                    "Recovered %d attachment-waiting conversation turn(s).",
                    len(resumed),
                )
        except Exception:  # noqa: BLE001
            logger.exception("orphan turn monitor failed")
