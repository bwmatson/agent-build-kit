"""What the `claude` CLI's closing event means: the one place it is read.

Whether a run succeeded is decided by the event's subtype and `is_error`; a
rate limit and a session that is gone are read from its own words. Callers
use the typed result and never read the text again.
"""

from datetime import datetime
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.claude_stream import ResultEvent
from agent_build_kit.pipeline.usage_guard import rate_limit_reset

# The closing event's subtypes that say the run succeeded; any other is not one.
SUCCESS_SUBTYPES = frozenset({"success"})

FailureKind = Literal["none", "rate_limited", "session_unavailable", "other"]


class AgentFailure(Frozen):
    """How a run ended: not a failure (`none`), or which failure it was."""

    kind: FailureKind
    resets_at: datetime | None = None


def agent_failure(event: ResultEvent | None, text: str) -> AgentFailure:
    """Classify a run from its closing `event` and `text`, the CLI's own words."""
    if event is not None:
        if event.subtype in SUCCESS_SUBTYPES and not event.is_error:
            return AgentFailure(kind="none")
    reset = rate_limit_reset(text)
    if reset is not False:
        return AgentFailure(kind="rate_limited", resets_at=reset)
    if "no conversation found" in text.lower():
        return AgentFailure(kind="session_unavailable")
    return AgentFailure(kind="other")
