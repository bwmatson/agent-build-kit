"""What the `claude` CLI's closing event means: the one place it is read.

A rate limit, a session that is gone and a failed run are decisions that come
from the event's structured fields first and its own words only after. Callers
use the typed result and never read the text again.
"""

from datetime import datetime
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.claude_stream import ResultEvent

FailureKind = Literal["none", "rate_limited", "session_unavailable", "other"]


class AgentFailure(Frozen):
    """How a run ended: not a failure (`none`), or which failure it was."""

    kind: FailureKind
    resets_at: datetime | None = None


def agent_failure(event: ResultEvent | None, text: str) -> AgentFailure:
    """Classify a run from its closing `event` and `text`, the CLI's own words."""
    raise NotImplementedError
