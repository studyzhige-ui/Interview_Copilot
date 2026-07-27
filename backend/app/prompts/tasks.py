"""Guidance prompts exposed by the task-management toolset."""

TASK_CREATE_PROMPT = """Use task_create only for work with at least three trackable steps or work that may need interruption recovery.
Create concise, action-oriented tasks in dependency order. Give each task observable acceptance criteria and encode prerequisites with blocked_by."""

TASK_UPDATE_PROMPT = """Use task_update when work actually changes state.
Follow pending → in_progress → verifying. Before verifying, record concrete evidence against the acceptance criteria. Only task_verify may mark a task completed. Use blocked only for an external dependency and abandoned only when the work is intentionally dropped."""

TASK_VERIFY_PROMPT = """Use task_verify after a task is in verifying state and contains concrete evidence.
Treat its verdict as authoritative: address failed criteria before requesting verification again."""

TASK_CHECKPOINT_PROMPT = """Use task_checkpoint after material progress or before interruption.
Record what is complete, verified evidence, unresolved blockers, and one exact next action so recovery does not repeat work."""

TASK_GET_PROMPT = (
    "Use task_get when the current task's scope, criteria, dependencies, or evidence "
    "must be recalled before continuing."
)

TASK_LIST_PROMPT = (
    "Use task_list to choose the next unblocked task or to report overall progress. "
    "Do not infer task state from conversation text when the task list is available."
)

__all__ = [
    "TASK_CHECKPOINT_PROMPT",
    "TASK_CREATE_PROMPT",
    "TASK_GET_PROMPT",
    "TASK_LIST_PROMPT",
    "TASK_UPDATE_PROMPT",
    "TASK_VERIFY_PROMPT",
]
