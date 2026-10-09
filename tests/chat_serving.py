"""What the chat tests of `abk serve` share, and the HTTP surface they pin.

The agent tab and the sessions page talk to these endpoints; a turn's reply is a
server-sent stream of AG-UI events (`data: <json>` lines).

    GET    /api/units/{change}/{number}/agent?tab=ID
           {"session": {"id", "runtime", "model"} | null,
            "state": "streaming" | "paused" | "attached",
            "composer": {"enabled": bool, "reason": str}, "attached_by": str | null}
    GET    /api/units/{change}/{number}/agent/events?tab=ID
           the tab's stream: a MESSAGES_SNAPSHOT of the recorded history, then what the
           running step records as it arrives. Its closing is the page closing.
    POST   /api/units/{change}/{number}/chat   {"tab", "prompt", "attachments": [...]}
           a turn: 409 while the step runs or another tab holds the lease, otherwise the
           lease is taken for `tab:ID` and the reply streams.
    GET    /api/tabs/events?tab=ID   a page that is no unit's agent tab holds its tab open
           with this; its closing is the page closing.
    DELETE /api/units/{change}/{number}/lease?tab=ID
    POST   /api/permissions/{id}   {"option": OPTION_ID}
    GET    /api/sessions           {"sessions": [{"id", "runtime", "cwd", "title", "held",
                                                  "loadable", "unit"}]}
    GET    /api/sessions/{runtime}/{id}
           {"id", "runtime", "events", "recorded", "tool_calls_available", "read_only",
            "reason", "actions": ["continue" | "fork" | "continue_as_new"]}
    POST   /api/sessions   {"runtime", "model", "unit"?: "change/number", "prompt"}
    POST   /api/sessions/{runtime}/{id}/continue   {"tab", "prompt", "attachments"}
    POST   /api/sessions/{runtime}/{id}/fork       {"tab", "prompt"}

A stream's first event naming the session it writes to is
`{"type": "CUSTOM", "name": "session", "value": {"id": ...}}`; a permission request is
`{"type": "CUSTOM", "name": "permission_request", "value": {"id", "tool", "input",
"options": [{"id", "name", "kind"}]}}`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_build_kit import runtimes
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import AgentSession, Node, SessionRole, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.workspaces import worktree_path
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.runtimes.claude_cli import FakeClaude

WAIT = 15


def unit_worktree(installation: Installation, unit_id: str) -> Path:
    """The unit's worktree, created: a session for the unit starts in it."""
    unit = UnitStore(installation.state_dir / "units.json").get(unit_id)
    assert unit.branch
    path = worktree_path(installation.checkouts[unit.repo], unit.branch, installation.worktree_root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_session(
    installation: Installation, unit_id: str, session: str, *, runtime: str, model: str = "m"
) -> None:
    """The unit's thread, waiting in review, with `session` as its build session."""
    change = unit_id.split("/")[0]
    state = UnitRun(
        unit_id=unit_id,
        change=change,
        sessions={
            SessionRole.BUILD: AgentSession(
                session_id=session,
                runtime=runtime,
                model=model,
                node=Node.IMPLEMENT,
                round=0,
                head="abc123",
            )
        },
    )

    async def write() -> None:
        async with open_checkpointer(unit_graphs_path(installation.state_dir)) as saver:
            await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)

    asyncio.run(write())


def claude_session_file(home: Path, session: str, cwd: Path, *, title: str = "Fix the bug") -> Path:
    """A session Claude Code wrote in an editor: `projects/<directory>/<id>.jsonl`."""
    directory = home / "projects" / str(cwd).replace("/", "-")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session}.jsonl"
    common = {"sessionId": session, "cwd": str(cwd), "version": "2.1.4", "userType": "external"}
    lines = [
        {
            **common,
            "type": "user",
            "uuid": "a1f94290-7e2b-4c6d-8b35-0d9e2f7c1a58",
            "parentUuid": None,
            "timestamp": "2026-10-01T09:00:00.000Z",
            "message": {"role": "user", "content": title},
        },
        {
            **common,
            "type": "assistant",
            "uuid": "5b0d8e42-9f1a-4c73-b6e4-2a8c0f5d7e19",
            "parentUuid": "a1f94290-7e2b-4c6d-8b35-0d9e2f7c1a58",
            "timestamp": "2026-10-01T09:00:05.000Z",
            "message": {
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": "I found the cause in the parser."}],
            },
        },
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


# Starts `argv` as a process of nobody's here: forked twice and reparented, as an editor's is.
# The server does not take its own children (the agents it runs) for an editor.
_DETACH = (
    "import os, sys\n"
    "r, w = os.pipe()\n"
    "if os.fork() == 0:\n"
    "    os.close(r)\n"
    "    if os.fork() == 0:\n"
    "        os.write(w, str(os.getpid()).encode())\n"
    "        os.close(w)\n"
    "        null = os.open(os.devnull, os.O_RDWR)\n"
    "        for fd in (0, 1, 2):\n"
    "            os.dup2(null, fd)\n"
    "        os.execvp(sys.argv[1], sys.argv[1:])\n"
    "    os._exit(0)\n"
    "os.close(w)\n"
    "pid = os.read(r, 32).decode()\n"
    "os.wait()\n"
    "print(pid)\n"
)


@contextmanager
def detached(argv: list[str], cwd: Path | None = None) -> Iterator[int]:
    out = subprocess.run(
        [sys.executable, "-c", _DETACH, *argv], cwd=cwd, capture_output=True, text=True, check=True
    )
    pid = int(out.stdout)
    try:
        yield pid
    finally:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


@contextmanager
def holding_process(session: str) -> Iterator[int]:
    """A process that has `session` open, as an editor running `claude --resume ID` does."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
    with detached([*sleeper, "--resume", session]) as pid:
        yield pid


def events_of(response: httpx.Response) -> Iterator[dict[str, Any]]:
    """The AG-UI events of a streamed response, as they arrive."""
    for line in response.iter_lines():
        if line.startswith("data:"):
            yield json.loads(line.removeprefix("data:").strip())


def turn(api: httpx.Client, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Send a turn and read its whole reply."""
    with api.stream("POST", url, json=body, timeout=WAIT) as response:
        assert response.status_code == 200, response.read()
        return list(events_of(response))


def until(condition: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT
    while not condition():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def use_claude(monkeypatch: pytest.MonkeyPatch, stdout: str) -> FakeClaude:
    """Have the `claude_code` runtime run `fake`, which answers every call with `stdout`."""
    fake = FakeClaude(stdout=stdout)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    return fake


def prompt_of(argv: list[str]) -> str:
    return argv[argv.index("-p") + 1]


class BlockingClaude(FakeClaude):
    """A `claude` that does not answer until the test lets it: a long turn."""

    def __init__(self, stdout: str) -> None:
        super().__init__(stdout=stdout)
        self.started = threading.Event()
        self.release = threading.Event()

    def __call__(self, argv, **kwargs):
        self.started.set()
        self.release.wait(WAIT)
        return super().__call__(argv, **kwargs)


def use_blocking_claude(monkeypatch: pytest.MonkeyPatch, stdout: str) -> BlockingClaude:
    fake = BlockingClaude(stdout)
    runtimes.names()
    monkeypatch.setitem(runtimes._REGISTRY, "claude_code", ClaudeCodeRuntime(execute=fake))
    return fake


@contextmanager
def claude_working_in(cwd: Path) -> Iterator[int]:
    """A Claude Code process in `cwd` that does not name its session: plain `claude`, or
    `claude -c`, as an editor starts it."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
    with detached([*sleeper, "claude"], cwd=cwd) as pid:
        yield pid
