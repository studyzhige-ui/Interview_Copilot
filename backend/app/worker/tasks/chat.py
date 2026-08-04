"""Durable conversation-turn execution."""

from app.task_queue.celery_app import celery_app
from app.core.async_runtime import run_async


@celery_app.task(
    name="tasks.process_conversation_turn",
)
def process_conversation_turn(turn_id: str) -> None:
    from app.services.chat.turn_executor import execute_turn

    run_async(execute_turn(turn_id))


__all__ = ["process_conversation_turn"]
