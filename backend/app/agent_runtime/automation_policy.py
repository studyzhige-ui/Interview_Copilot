"""Deterministic unattended scope over the already-composed tool registry."""

from app.agent_runtime.tool_registry import registry
from app.agent_runtime.tool_policy import ToolEffect

_CLOUD_AUTOMATION_INTERNAL_TOOLS = frozenset({"review_gmail_observation"})


def cloud_sustainable_read_tool_names() -> frozenset[str]:
    """Concrete built-ins eligible for unattended cloud execution now."""

    snapshot = registry.snapshot()
    return frozenset(
        name
        for name in snapshot.tool_names
        if snapshot.effect_for(name) is ToolEffect.READ
    )


def cloud_sustainable_automation_tool_names() -> frozenset[str]:
    """Exact built-ins allowed in unattended PersistentTask definitions.

    Most are reads.  The sole write exception is the Gmail Observation review
    command: it is task-scoped, reversible through append-only correction, and
    independently revalidates source/Turn identity before any domain change.
    """

    snapshot = registry.snapshot()
    return cloud_sustainable_read_tool_names().union(
        name
        for name in _CLOUD_AUTOMATION_INTERNAL_TOOLS
        if name in snapshot.entries
        and snapshot.effect_for(name) is ToolEffect.INTERNAL_WRITE
    )
