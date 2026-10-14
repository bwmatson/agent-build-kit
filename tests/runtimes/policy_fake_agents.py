"""Fake agents for the policy harness's tests, speaking the Agent Client Protocol over stdio.

Run as a real subprocess: `python policy_fake_agents.py RECORD MODE [--refuse PREFIX]
[--ask PREFIX] [--judge N] [--signal NAME]`. The commands come from the inline code span of each
prompt. RECORD is a directory: the agent writes its pid and the pid of a child it left in its
process group (`agent.pid`, `child.pid`), and one JSON line per thing it did to `did.jsonl`.

- `silent` never answers the first request.
- `judge` answers every prompt: a command starting with a `--refuse` prefix is left unasked
  (the agent's own deny list refused it), one starting with an `--ask` prefix asks permission
  first and asks the terminal only if allowed, any other asks the terminal. After `--judge N`
  prompts it stalls on the next without answering.
- `--signal NAME` has it send that signal to its parent on the first prompt, then stall.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from acp import (
    PROTOCOL_VERSION,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    run_agent,
    start_tool_call,
)
from acp.interfaces import Agent, Client
from acp.schema import AgentCapabilities, PermissionOption, ToolCallUpdate

SESSION = "sess_policy_harness"


def command(record: Path, mode: str, *options: str) -> list[str]:
    """The argv that starts a fake agent recording to the directory `record`."""
    return [sys.executable, str(Path(__file__)), str(record), mode, *options]


def alive(pid: int) -> bool:
    """Whether the process exists and is not a zombie awaiting its reaper."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def pids(record: Path) -> list[int]:
    """The agent's own pid and the pid of the child it left in its group."""
    return [int((record / name).read_text()) for name in ("agent.pid", "child.pid")]


def did(record: Path) -> list[dict[str, Any]]:
    path = record / "did.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class _Agent:
    def __init__(self, record: Path, args: argparse.Namespace) -> None:
        self._record = record
        self._args = args
        self._client: Client | None = None
        self._judged = 0

    def on_connect(self, conn: Client) -> None:
        self._client = conn

    def _did(self, what: str, **fields: Any) -> None:
        with (self._record / "did.jsonl").open("a") as out:
            out.write(json.dumps({"did": what, **fields}) + "\n")

    async def _stall(self) -> None:
        await asyncio.Event().wait()

    async def initialize(self, protocol_version: int, **kwargs: Any) -> InitializeResponse:
        if self._args.mode == "silent":
            await self._stall()
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(),
            auth_methods=[],
        )

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        return None

    async def new_session(self, cwd: str, **kwargs: Any) -> NewSessionResponse:
        return NewSessionResponse(session_id=SESSION)

    async def prompt(self, session_id: str, prompt: list, **kwargs: Any) -> PromptResponse:
        client = self._client
        assert client is not None
        if self._args.signal and not self._judged:
            os.kill(os.getppid(), getattr(signal, self._args.signal))
            await self._stall()
        if self._judged >= self._args.judge:
            await self._stall()
        text = " ".join(getattr(block, "text", "") for block in prompt)
        found = re.search(r"`([^`\n]+)`", text)
        assert found, text
        line = found.group(1)
        self._judged += 1
        if any(line.startswith(prefix) for prefix in self._args.refuse):
            self._did("refused", command=line)
            return PromptResponse(stop_reason="end_turn")
        if any(line.startswith(prefix) for prefix in self._args.ask):
            asked = await client.request_permission(
                session_id=session_id,
                tool_call=ToolCallUpdate(
                    tool_call_id="call_1", title=line, kind="execute", raw_input={"command": line}
                ),
                options=[
                    PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
                    PermissionOption(option_id="reject", name="Reject", kind="reject_once"),
                ],
            )
            chosen = getattr(asked.outcome, "option_id", "cancelled")
            self._did("asked", command=line, outcome=chosen)
            if chosen != "allow":
                return PromptResponse(stop_reason="end_turn")
        await client.session_update(
            session_id=session_id,
            update=start_tool_call("call_1", line, kind="execute", status="in_progress"),
        )
        created = await client.create_terminal(session_id=session_id, command=line, args=[])
        await client.wait_for_terminal_exit(session_id=session_id, terminal_id=created.terminal_id)
        await client.release_terminal(session_id=session_id, terminal_id=created.terminal_id)
        self._did("ran", command=line)
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("mode", choices=["silent", "judge"])
    parser.add_argument("--refuse", action="append", default=[])
    parser.add_argument("--ask", action="append", default=[])
    parser.add_argument("--judge", type=int, default=10**6)
    parser.add_argument("--signal")
    args = parser.parse_args()
    (args.record / "agent.pid").write_text(str(os.getpid()))
    child = subprocess.Popen(
        [sys.executable, "-c", "import asyncio; asyncio.run(asyncio.Event().wait())"],
        stdin=subprocess.DEVNULL,
    )
    (args.record / "child.pid").write_text(str(child.pid))
    asyncio.run(run_agent(cast(Agent, _Agent(args.record, args))))


if __name__ == "__main__":
    main()
