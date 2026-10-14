"""The protocol half of the fake agents of `policy_fake_agents.py`, imported only once the fake
has written its pid files, because importing the protocol library takes a while on a loaded
machine."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
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
        # An agent that wraps what it runs in a shell asks for the shell, not for the command.
        program, arguments = ("sh", ["-c", line]) if self._args.shell else (line, [])
        created = await client.create_terminal(
            session_id=session_id, command=program, args=arguments
        )
        await client.wait_for_terminal_exit(session_id=session_id, terminal_id=created.terminal_id)
        await client.release_terminal(session_id=session_id, terminal_id=created.terminal_id)
        self._did("ran", command=line)
        return PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        return None


def serve(record: Path, args: argparse.Namespace) -> None:
    asyncio.run(run_agent(cast(Agent, _Agent(record, args))))
