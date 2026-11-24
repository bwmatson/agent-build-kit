"""The bridge from what an agent run records to the AG-UI events the browser reads.

Both runtimes already tell the server each event of a run in one shape
(`TranscriptEvent`: a Claude stream-json message and an ACP `session/update` alike).
`AgUiEncoder` turns that stream into AG-UI events as it arrives, and
`messages_snapshot` turns a recorded or loaded history into the `MESSAGES_SNAPSHOT`
the agent tab opens on.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from agent_build_kit.pipeline.transcript import TranscriptEvent

_FLAG = re.compile(r"```spec-conflict[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


class AgUiEncoder:
    """One run's events, in order, as AG-UI events (dicts with a `type`).

    - `text` and `reasoning` events open a `TEXT_MESSAGE_START` / `REASONING_MESSAGE_START`
      with a fresh `messageId`, add each event's words as `..._CONTENT` with `delta`, and
      close it with `..._END` when an event of another kind arrives or on `close()`; text
      events that follow one another are one message.
    - a `tool_call` is `TOOL_CALL_START` (`toolCallId`, `toolCallName`), one `TOOL_CALL_ARGS`
      whose `delta` is the input as JSON, and `TOOL_CALL_END`; its `tool_result` is
      `TOOL_CALL_RESULT` (`toolCallId`, `content`).
    - `plan` and `usage` are `CUSTOM` events named `plan` (value: the text) and `usage`
      (value: the counts).
    - a fenced `spec-conflict` block in the assistant's words, however they are split, is also
      a `CUSTOM` event named `spec_conflict` (value: its `requirement` and `reason`).
    - `stop` is `RUN_FINISHED` with `result` `{"stopReason": <the stop text>}`, or `RUN_ERROR`
      with `message` the stop text when it begins with `error`.
    """

    def __init__(self, thread_id: str = "", run_id: str = "") -> None:
        self._thread = thread_id
        self._run = run_id
        self._open: tuple[str, str] | None = None  # (message kind, message id)
        self._count = 0
        self._said = ""  # the open text message's words, and the flags already shown from it
        self._flags = 0

    def start(self) -> list[dict[str, Any]]:
        """The event that opens the run: nothing else of it may come before."""
        return [{"type": "RUN_STARTED", "threadId": self._thread, "runId": self._run}]

    def fail(self, message: str) -> list[dict[str, Any]]:
        """The run ended without a stop reason of its own."""
        return [
            *self._end(),
            {"type": "RUN_ERROR", "message": message, "threadId": self._thread, "runId": self._run},
        ]

    def finish(self, reason: str) -> list[dict[str, Any]]:
        return [
            *self._end(),
            {
                "type": "RUN_FINISHED",
                "threadId": self._thread,
                "runId": self._run,
                "result": {"stopReason": reason},
            },
        ]

    def _end(self) -> list[dict[str, Any]]:
        if self._open is None:
            return []
        kind, message = self._open
        self._open = None
        self._said, self._flags = "", 0
        return [{"type": f"{kind}_MESSAGE_END", "messageId": message}]

    def _words(self, kind: str, text: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if self._open is None or self._open[0] != kind:
            out += self._end()
            self._count += 1
            message = f"{self._run}-msg-{self._count}" if self._run else f"msg-{self._count}"
            self._open = (kind, message)
            role = "assistant" if kind == "TEXT" else "reasoning"
            out.append({"type": f"{kind}_MESSAGE_START", "messageId": message, "role": role})
        out.append({"type": f"{kind}_MESSAGE_CONTENT", "messageId": self._open[1], "delta": text})
        return out

    def _flag(self, text: str) -> list[dict[str, Any]]:
        """The events for the flags `text` completes in the open message."""
        self._said += text
        found = list(_FLAG.finditer(self._said))
        out: list[dict[str, Any]] = []
        for match in found[self._flags :]:
            try:
                value = json.loads(match.group(1))
            except ValueError:
                continue
            if isinstance(value, dict):
                out.append({"type": "CUSTOM", "name": "spec_conflict", "value": value})
        self._flags = len(found)
        return out

    def encode(self, event: TranscriptEvent) -> list[dict[str, Any]]:
        match event.kind:
            case "text":
                return [*self._words("TEXT", event.text), *self._flag(event.text)]
            case "reasoning":
                return self._words("REASONING", event.text)
        out = self._end()
        match event.kind:
            case "tool_call":
                out += [
                    {
                        "type": "TOOL_CALL_START",
                        "toolCallId": event.call,
                        "toolCallName": event.tool,
                    },
                    {
                        "type": "TOOL_CALL_ARGS",
                        "toolCallId": event.call,
                        "delta": json.dumps(event.input),
                    },
                    {"type": "TOOL_CALL_END", "toolCallId": event.call},
                ]
            case "tool_result":
                out.append(
                    {
                        "type": "TOOL_CALL_RESULT",
                        "toolCallId": event.call,
                        "messageId": f"result-{event.call}",
                        "role": "tool",
                        "content": event.text,
                    }
                )
            case "plan":
                out.append({"type": "CUSTOM", "name": "plan", "value": event.text})
            case "usage":
                out.append({"type": "CUSTOM", "name": "usage", "value": event.usage})
            case "permission":
                out.append({"type": "CUSTOM", "name": "permission", "value": event.text})
            case "stop":
                if event.text.startswith("error"):
                    out.append(self.fail(event.text)[-1])
                else:
                    out.append(self.finish(event.text)[-1])
            # A "user" turn is the browser's own: it already has it.
        return out

    def close(self) -> list[dict[str, Any]]:
        """Whatever the run left open."""
        return self._end()


def messages_snapshot(events: Sequence[TranscriptEvent]) -> dict[str, Any]:
    """A `MESSAGES_SNAPSHOT` (`messages`): the assistant's words as `assistant` messages with
    `content`, its tool calls on the assistant message as `toolCalls`
    (`id`, `type: "function"`, `function: {name, arguments}`), and each result as a `tool`
    message with `toolCallId` and `content`."""
    messages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None  # the assistant message still collecting

    def assistant() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = {"id": f"msg-{len(messages) + 1}", "role": "assistant", "content": ""}
            messages.append(current)
        return current

    for event in events:
        match event.kind:
            case "text":
                message = assistant()
                message["content"] += event.text
            case "tool_call":
                assistant().setdefault("toolCalls", []).append(
                    {
                        "id": event.call,
                        "type": "function",
                        "function": {"name": event.tool, "arguments": json.dumps(event.input)},
                    }
                )
            case "tool_result":
                current = None
                messages.append(
                    {
                        "id": f"result-{event.call}",
                        "role": "tool",
                        "toolCallId": event.call,
                        "content": event.text,
                    }
                )
            case "user":
                current = None
                messages.append(
                    {"id": f"msg-{len(messages) + 1}", "role": "user", "content": event.text}
                )
            case "stop":
                current = None
    return {"type": "MESSAGES_SNAPSHOT", "messages": messages}
