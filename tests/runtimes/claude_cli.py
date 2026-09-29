"""A stand-in for the `claude` binary, faked at the process boundary.

The adapter is given this in place of the real executor, so what it sees is
what the CLI hands back — an exit code, stdout and stderr — and the events of
a streamed run are replayed to it line by line from stdout, the way
`claude_stream.stream_run` reads them from the real process.

The streams below carry what `claude -p --output-format stream-json
--verbose` prints: the init event with its tool list and session, assistant
messages with usage and a null stop reason, the user turn carrying a tool
result, and a result event with its cost, usage and permission denials — not
only the fields the adapter reads.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

SESSION = "3f1c2a9e-5b7d-4e2f-9a61-0c8d7e4b2a15"
MODEL = "claude-opus-5-5"

_USAGE = {
    "input_tokens": 4,
    "cache_creation_input_tokens": 1822,
    "cache_read_input_tokens": 14671,
    "output_tokens": 212,
    "service_tier": "standard",
}


def _init(cwd: Path) -> dict:
    return {
        "type": "system",
        "subtype": "init",
        "cwd": str(cwd),
        "session_id": SESSION,
        "tools": ["Bash", "Edit", "Glob", "Grep", "Read", "Write"],
        "mcp_servers": [],
        "model": MODEL,
        "permissionMode": "acceptEdits",
        "slash_commands": ["compact", "context", "cost", "review"],
        "apiKeySource": "none",
        "claude_code_version": "2.1.4",
        "output_style": "default",
        "agents": ["general-purpose"],
        "skills": [],
        "plugins": [],
        "uuid": "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d31",
    }


def _assistant(content: list[dict]) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": "msg_01Hq7ZkP3xYwVb2nR8tLcD4e",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": content,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": _USAGE,
            "context_management": None,
        },
        "parent_tool_use_id": None,
        "session_id": SESSION,
        "uuid": "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e47",
    }


def _result(text: str, *, is_error: bool = False, turns: int = 3, ms: int = 81234) -> dict:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": is_error,
        "duration_ms": ms,
        "duration_api_ms": ms - 2100 if ms > 2100 else 0,
        "num_turns": turns,
        "result": text,
        "session_id": SESSION,
        "total_cost_usd": 0.0 if is_error else 0.4127,
        "usage": _USAGE if not is_error else dict.fromkeys(_USAGE, 0) | {"service_tier": None},
        "modelUsage": {} if is_error else {MODEL: {"inputTokens": 4, "outputTokens": 212}},
        "permission_denials": [],
        "uuid": "9a4e2c71-8b3d-4f6a-a5e0-7c1b9d2f8e63",
    }


def stream(*events: dict) -> str:
    return "".join(json.dumps(event) + "\n" for event in events)


def finished_build(cwd: Path, answer: str) -> str:
    """A build that says what it will do, edits one file, and answers."""
    return stream(
        _init(cwd),
        _assistant([{"type": "text", "text": "I'll add the marker to the app module."}]),
        _assistant(
            [
                {
                    "type": "tool_use",
                    "id": "toolu_01AbCdEfGhJkLmNpQrStUvWx",
                    "name": "Edit",
                    "input": {
                        "file_path": str(cwd / "src" / "app.py"),
                        "old_string": "MARKER = None",
                        "new_string": 'MARKER = "added"',
                        "replace_all": False,
                    },
                }
            ]
        ),
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "tool_use_id": "toolu_01AbCdEfGhJkLmNpQrStUvWx",
                        "type": "tool_result",
                        "content": f"The file {cwd / 'src' / 'app.py'} has been updated.",
                    }
                ],
            },
            "parent_tool_use_id": None,
            "session_id": SESSION,
            "uuid": "c3e7a1f5-2d9b-4a6e-8f0c-5b2d7e1a9c84",
            "tool_use_result": {
                "filePath": str(cwd / "src" / "app.py"),
                "oldString": "MARKER = None",
                "newString": 'MARKER = "added"',
                "structuredPatch": [],
                "userModified": False,
                "replaceAll": False,
            },
        },
        _assistant([{"type": "text", "text": answer}]),
        _result(answer),
    )


def refused(cwd: Path, message: str) -> str:
    """A run the account had no room for: the refusal arrives as an error
    result, before any turn is spent."""
    return stream(_init(cwd), _result(message, is_error=True, turns=1, ms=412))


class FakeClaude:
    """Records each invocation and answers as the CLI would have."""

    def __init__(self, *, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], Path | None]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        on_event: Callable[[dict], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), cwd))
        if on_event is not None:
            for line in self.stdout.splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    on_event(event)
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)

    @property
    def argv(self) -> list[str]:
        assert len(self.calls) == 1, f"expected one claude invocation, got {len(self.calls)}"
        return self.calls[0][0]


def no_agent(*args, **kwargs) -> subprocess.CompletedProcess[str]:
    raise AssertionError("an agent was run where none should have been")
