"""What an ACP agent's tool call update means: the one place it is read."""

from acp.schema import ToolCallProgress


def denied_call(update: ToolCallProgress) -> bool:
    """Whether `update` reports a call the agent's own policy refused."""
    raise NotImplementedError
