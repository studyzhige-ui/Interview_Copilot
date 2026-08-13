"""Auto-import all tool modules to trigger self-registration."""

from app.agent_runtime.tools import (  # noqa: F401
    agent_task,
    attachment_vision,
    career,
    career_domains,
    file_tool,
    gmail,
    gmail_observation,
    history,
    interview_history,
    jobs,
    knowledge,
    mock_interview,
    personalization,
    resume,
    resume_profile,
    web,
)
from app.agent_runtime.tool_registry import registry
from app.services.google_gmail_connector import (
    build_configured_google_gmail_connector,
)


# A configured real adapter makes the read Tool discoverable even before a
# particular user connects. Missing user grant/scope is then handled as the
# existing same-call connection Interaction; incomplete deployment config
# means no callable handler and therefore no Tool registration at all.
_gmail_connector = build_configured_google_gmail_connector()
if _gmail_connector is not None:
    registry.register(gmail.build_gmail_search_messages_tool(lambda: _gmail_connector))
