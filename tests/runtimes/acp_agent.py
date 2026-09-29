"""A small agent speaking the Agent Client Protocol, for the `acp` adapter's tests.

Run as a real subprocess over stdio, built on the same library the adapter
uses, so what the adapter sees is what a real agent sends: the initialize
answer with its capabilities and identity, a session carrying its modes and
its model choice as a config option, the commands it offers, thought and
message chunks, tool calls started and updated, and a prompt answered with an
end-of-turn reason.

    python acp_agent.py RECORD [--stop REASON] [--no-additional-dirs] [--fail HOW]

Every request the client sends is appended to RECORD as one JSON line —
`{"method": ..., "params": ...}`, the params as they arrived on the wire — so
a test can say what the adapter asked for. `--stop` is the end-of-turn reason
the prompt is answered with (`end_turn` unless given).
`--no-additional-dirs` leaves the `additionalDirectories` session capability
unadvertised. `--fail` breaks the prompt partway through, after the preamble:
`exit` writes `STDERR_LINE` to stderr and exits 3, `kill` sends the agent
SIGKILL, `error` answers the prompt with an internal error, and `hang` closes
its stdout, writes `STDERR_LINE` to stderr and lingers for `HANG_SECONDS`
without exiting, as an agent whose stdio loop died while its process did not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    InitializeResponse,
    NewSessionResponse,
    PromptResponse,
    RequestError,
    SetSessionConfigOptionResponse,
    run_agent,
    start_tool_call,
    text_block,
    tool_content,
    update_agent_message_text,
    update_agent_thought_text,
    update_tool_call,
)
from acp.helpers import update_available_commands
from acp.interfaces import Client
from acp.schema import (
    AgentCapabilities,
    AvailableCommand,
    Implementation,
    PromptCapabilities,
    SessionAdditionalDirectoriesCapabilities,
    SessionCapabilities,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionMode,
    SessionModeState,
    ToolCallLocation,
)

SESSION = "sess_7Hq2Zk4PxYwVb9nR"

# What the agent offers for its `model` config option, and runs on unless the
# client picks another.
MODELS = ("swift-1", "deep-2")
DEFAULT_MODEL = MODELS[0]

# Messages arrive in pieces, as a model's output streams: the preamble a word
# at a time, the final answer — which the review step parses as JSON — in two.
PREAMBLE = "I'll add the marker to the app module."
PREAMBLE_CHUNKS = tuple(word + " " for word in PREAMBLE.split())
ANSWER_CHUNKS = ('{"approved": true, ', '"feedback": "", "needs_human": false}')
ANSWER = "".join(ANSWER_CHUNKS)
TOOL_TITLE = "Edit src/app.py"
THOUGHT = "The marker belongs beside the other module constants."
STDERR_LINE = "fake-agent: the model endpoint refused the connection"
# Far longer than any exit grace a test gives the adapter.
HANG_SECONDS = 60


def _model_option(current: str) -> SessionConfigOptionSelect:
    return SessionConfigOptionSelect(
        type="select",
        id="model",
        name="Model",
        description="Which model answers in this session.",
        category="model",
        current_value=current,
        options=[
            SessionConfigSelectOption(value="swift-1", name="Swift", description="Fast, cheaper."),
            SessionConfigSelectOption(value="deep-2", name="Deep", description="Slower, stronger."),
        ],
    )


class FakeAgent:
    def __init__(
        self, record: Path, stop: str, *, additional_dirs: bool = True, fail: str | None = None
    ) -> None:
        self._record = record
        self._stop = stop
        self._additional_dirs = additional_dirs
        self._fail = fail
        self._model = DEFAULT_MODEL
        self._client: Client | None = None

    def on_connect(self, conn: Client) -> None:
        self._client = conn

    def _log(self, method: str, params: dict[str, Any]) -> None:
        with self._record.open("a") as out:
            out.write(json.dumps({"method": method, "params": params}, default=str) + "\n")

    async def initialize(
        self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs: Any
    ) -> InitializeResponse:
        self._log(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "clientCapabilities": client_capabilities.model_dump(by_alias=True, mode="json")
                if client_capabilities is not None
                else None,
                "clientInfo": client_info.model_dump(by_alias=True, mode="json")
                if client_info is not None
                else None,
            },
        )
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_capabilities=AgentCapabilities(
                load_session=False,
                prompt_capabilities=PromptCapabilities(image=False, audio=False),
                session_capabilities=SessionCapabilities(
                    additional_directories=SessionAdditionalDirectoriesCapabilities()
                    if self._additional_dirs
                    else None
                ),
            ),
            auth_methods=[],
            agent_info=Implementation(name="fake-agent", title="Fake Agent", version="0.3.1"),
        )

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        self._log("authenticate", {"methodId": method_id})
        return None

    async def new_session(
        self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs: Any
    ) -> NewSessionResponse:
        self._log(
            "session/new",
            {
                "cwd": cwd,
                "additionalDirectories": additional_directories,
                "mcpServers": [s.model_dump(by_alias=True, mode="json") for s in mcp_servers or []],
            },
        )
        return NewSessionResponse(
            session_id=SESSION,
            modes=SessionModeState(
                current_mode_id="default",
                available_modes=[
                    SessionMode(id="default", name="Default", description="Asks before edits."),
                    SessionMode(id="yolo", name="Unattended", description="Asks for nothing."),
                ],
            ),
            config_options=[_model_option(self._model)],
        )

    async def set_config_option(
        self, config_id: str, session_id: str, value: str | bool, **kwargs: Any
    ) -> SetSessionConfigOptionResponse:
        self._log(
            "session/set_config_option",
            {"configId": config_id, "sessionId": session_id, "value": value},
        )
        if config_id == "model" and value in MODELS:
            self._model = str(value)
        return SetSessionConfigOptionResponse(config_options=[_model_option(self._model)])

    async def set_session_mode(self, session_id: str, mode_id: str, **kwargs: Any) -> None:
        self._log("session/set_mode", {"sessionId": session_id, "modeId": mode_id})
        return None

    async def prompt(self, session_id: str, prompt: list, **kwargs: Any) -> PromptResponse:
        self._log(
            "session/prompt",
            {
                "sessionId": session_id,
                "prompt": [block.model_dump(by_alias=True, mode="json") for block in prompt],
                "model": self._model,
            },
        )
        client = self._client
        assert client is not None
        cwd = Path.cwd()

        async def send(update) -> None:
            await client.session_update(session_id=session_id, update=update)

        await send(
            update_available_commands(
                [AvailableCommand(name="review", description="Review the working tree.")]
            )
        )
        await send(update_agent_thought_text(THOUGHT))
        for chunk in PREAMBLE_CHUNKS:
            await send(update_agent_message_text(chunk))
        if self._fail == "exit":
            print(STDERR_LINE, file=sys.stderr, flush=True)
            sys.exit(3)
        if self._fail == "kill":
            os.kill(os.getpid(), signal.SIGKILL)
        if self._fail == "error":
            raise RequestError.internal_error({"details": "the model endpoint went away"})
        if self._fail == "hang":
            os.close(1)
            print(STDERR_LINE, file=sys.stderr, flush=True)
            time.sleep(HANG_SECONDS)
        await send(
            start_tool_call(
                "call_01",
                TOOL_TITLE,
                kind="edit",
                status="pending",
                locations=[ToolCallLocation(path=str(cwd / "src" / "app.py"), line=None)],
                raw_input={
                    "path": str(cwd / "src" / "app.py"),
                    "old": "MARKER = None",
                    "new": 'MARKER = "added"',
                },
            )
        )
        await send(update_tool_call("call_01", status="in_progress"))
        await send(
            update_tool_call(
                "call_01",
                status="completed",
                content=[tool_content(text_block("Updated src/app.py"))],
                raw_output={"ok": True},
            )
        )
        for chunk in ANSWER_CHUNKS:
            await send(update_agent_message_text(chunk))
        return PromptResponse(stop_reason=self._stop)

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self._log("session/cancel", {"sessionId": session_id})

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._log(method, params)
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        self._log(method, params)


def command(
    record: Path, *, stop: str = "end_turn", additional_dirs: bool = True, fail: str | None = None
) -> list[str]:
    """The argv that starts this agent, as `runtimes.acp.command` names one."""
    argv = [sys.executable, str(Path(__file__).resolve()), str(record), "--stop", stop]
    if not additional_dirs:
        argv.append("--no-additional-dirs")
    if fail:
        argv += ["--fail", fail]
    return argv


def use_agent(
    record: Path, *, stop: str = "end_turn", additional_dirs: bool = True, fail: str | None = None
) -> None:
    """Point the active workspace's `runtimes.acp.command` at this agent,
    answering every prompt with `stop`."""
    use_command(command(record, stop=stop, additional_dirs=additional_dirs, fail=fail))


def use_command(argv: list[str] | None) -> None:
    """Set the active workspace's `runtimes.acp.command` to `argv` (None: unset)."""
    from agent_build_kit import config
    from agent_build_kit.config import RuntimeConfig

    current = config.active()
    entry = RuntimeConfig(command=argv)
    config.activate(current.model_copy(update={"runtimes": {"acp": entry}}), config.active_root())


def requests(record: Path, method: str) -> list[dict[str, Any]]:
    """The params of each `method` request the agent received, in order."""
    if not record.exists():
        return []
    lines = [json.loads(line) for line in record.read_text().splitlines() if line]
    return [line["params"] for line in lines if line["method"] == method]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("--stop", default="end_turn")
    parser.add_argument("--no-additional-dirs", dest="additional_dirs", action="store_false")
    parser.add_argument("--fail", choices=["exit", "kill", "error", "hang"])
    args = parser.parse_args()
    agent = FakeAgent(args.record, args.stop, additional_dirs=args.additional_dirs, fail=args.fail)
    asyncio.run(run_agent(agent))


if __name__ == "__main__":
    main()
