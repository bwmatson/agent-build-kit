"""The AG-UI protocol's own rules, checked against its reference models.

Every event must be one the `ag-ui-protocol` package's models accept (camelCase aliases and
required fields), and the stream must follow the protocol's order: a run opens with
`RUN_STARTED` and ends with exactly one `RUN_FINISHED` or `RUN_ERROR`, messages and tool calls
open, continue and close in order inside it, and runs do not overlap.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ag_ui.core import Event
from pydantic import TypeAdapter

_EVENT = TypeAdapter(Event)


def validate_stream(events: Iterable[dict[str, Any]], *, open_at_end: bool = False) -> None:
    """Raise AssertionError (or the model's ValidationError) if `events` break the protocol."""
    in_run = False
    message: str | None = None  # the message open, by id
    calls: set[str] = set()  # tool calls started and not yet ended
    for event in events:
        _EVENT.validate_python(event)
        kind = event["type"]
        if kind == "MESSAGES_SNAPSHOT":
            assert not in_run, "a snapshot inside a run"
            continue
        if kind == "RUN_STARTED":
            assert not in_run, "a run started inside a run"
            in_run = True
            continue
        assert in_run, f"{kind} outside a run"
        if kind in ("RUN_FINISHED", "RUN_ERROR"):
            assert message is None and not calls, f"{kind} with a message or call still open"
            in_run = False
        elif kind.endswith("_MESSAGE_START"):
            assert message is None, "a message started inside a message"
            message = event["messageId"]
        elif kind.endswith("_MESSAGE_CONTENT"):
            assert message == event["messageId"], "content outside its message"
        elif kind.endswith("_MESSAGE_END"):
            assert message == event["messageId"], "end of a message not open"
            message = None
        elif kind == "TOOL_CALL_START":
            calls.add(event["toolCallId"])
        elif kind in ("TOOL_CALL_ARGS", "TOOL_CALL_END"):
            assert event["toolCallId"] in calls, f"{kind} for a call not started"
            if kind == "TOOL_CALL_END":
                calls.discard(event["toolCallId"])
    assert open_at_end or not in_run, "the stream ended inside a run"
