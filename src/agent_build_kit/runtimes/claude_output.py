"""What the `claude` CLI's closing event means: the one place it is read.

Whether a run succeeded is decided by the event's subtype and `is_error`; a
rate limit or a failing model service by its `api_error_status` when it has one,
else from its own words, and a session that is gone or too long to continue from its
own words. Callers use the typed result and never read the text again.
"""

import json
import re
from datetime import datetime
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.claude_stream import ResultEvent
from agent_build_kit.pipeline.usage_guard import rate_limit_reset
from agent_build_kit.runtimes.base import RefusedCall

# The closing event's subtypes that say the run succeeded; any other is not one.
SUCCESS_SUBTYPES = frozenset({"success"})

# The HTTP status the closing event's `api_error_status` carries for a rate limit.
RATE_LIMIT_STATUS = 429

# The statuses of a model service that is failing, not refusing this call; the CLI has
# already retried them when it closes on one.
SERVICE_STATUSES = range(500, 600)

# What the CLI prints for an API error when its event carries no status: the status
# follows the words, and a word may come first ("Repeated 529 Overloaded errors").
_API_ERROR_STATUS = re.compile(r"API Error: (?:\D{0,40}?)(\d{3})\b")

FailureKind = Literal["none", "rate_limited", "service_unavailable", "session_unavailable", "other"]


class AgentFailure(Frozen):
    """How a run ended: not a failure (`none`), or which failure it was."""

    kind: FailureKind
    resets_at: datetime | None = None
    # The HTTP status of a `service_unavailable` ending.
    status: int | None = None


def agent_failure(event: ResultEvent | None, text: str) -> AgentFailure:
    """Classify a run from its closing `event` and `text`, the CLI's own words."""
    if event is not None:
        if event.subtype in SUCCESS_SUBTYPES and not event.is_error:
            return AgentFailure(kind="none")
        if event.api_error_status == RATE_LIMIT_STATUS:
            # The status says it; the words only say when it lifts, if they do.
            reset = rate_limit_reset(text)
            return AgentFailure(
                kind="rate_limited", resets_at=reset if isinstance(reset, datetime) else None
            )
    reset = rate_limit_reset(text)
    if reset is not False:
        return AgentFailure(kind="rate_limited", resets_at=reset)
    status = event.api_error_status if event is not None else None
    if status is None and (words := _API_ERROR_STATUS.search(text)):
        status = int(words.group(1))
    if status in SERVICE_STATUSES:
        return AgentFailure(kind="service_unavailable", status=status)
    lowered = text.lower()
    # A resumed conversation that no longer fits its context is as good as gone.
    if "no conversation found" in lowered or "prompt is too long" in lowered:
        return AgentFailure(kind="session_unavailable")
    return AgentFailure(kind="other")


def refused_calls(stdout: str, event: ResultEvent | None) -> tuple[RefusedCall, ...]:
    """The calls the CLI's permission layer refused: the result event lists each, and the
    error tool result of the same call says why (the list names the call, not the reason)."""
    if event is None or not event.permission_denials:
        return ()
    reasons: dict[str, str] = {}
    for line in stdout.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        message = parsed.get("message") if isinstance(parsed, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                reasons[str(block.get("tool_use_id"))] = _text_of(block.get("content"))
    refused = []
    for denial in event.permission_denials:
        given = denial.get("tool_input")
        given = given if isinstance(given, dict) else {}
        subject = next(
            (str(given[k]) for k in ("command", "file_path", "path") if given.get(k)),
            next((v for v in given.values() if isinstance(v, str)), ""),
        )
        refused.append(
            RefusedCall(
                tool=str(denial.get("tool_name", "")),
                subject=subject,
                reason=reasons.get(str(denial.get("tool_use_id")), ""),
            )
        )
    return tuple(refused)


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return ""
