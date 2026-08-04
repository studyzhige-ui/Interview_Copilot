"""Construction of concrete conversation execution strategies."""

from app.conversation.strategy import ExecutionStrategy


def make_agent_strategy() -> ExecutionStrategy:
    """Build the ReAct strategy without loading Agent code on chat-only turns."""
    from app.conversation.agent_strategy import AgentLoopStrategy

    return AgentLoopStrategy()


def make_chat_strategy() -> ExecutionStrategy:
    """Build the deterministic chat-pipeline strategy."""
    from app.conversation.chat_strategy import ChatPipelineStrategy

    return ChatPipelineStrategy()


__all__ = ["make_agent_strategy", "make_chat_strategy"]
