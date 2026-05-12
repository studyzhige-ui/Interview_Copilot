"""Auto-import all tool modules to trigger self-registration."""

from app.agent_runtime.tools import (  # noqa: F401
    file_tool,
    interview_history,
    jobs,
    knowledge,
    memory,
    resume,
    web,
)
