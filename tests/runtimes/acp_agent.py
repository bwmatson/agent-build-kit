"""A small agent speaking the Agent Client Protocol, for the `acp` adapter's tests.

Run as a real subprocess over stdio, built on the same library the adapter
uses, so what the adapter sees is what a real agent sends: the initialize
answer with its capabilities and identity, a session carrying its modes and
its model choice as a config option, the commands it offers, thought and
message chunks, tool calls started and updated, and a prompt answered with an
end-of-turn reason.

    python acp_agent.py RECORD [--stop REASON] [--no-additional-dirs] [--linger] [--fail HOW]

Every request and notification the client sends is appended to RECORD as one
JSON line — `{"method": ..., "params": ...}`, exactly as it arrived on the
wire, captured through the library's own connection observer rather than
rebuilt from the handler's keyword arguments — so a test can say what the
adapter actually put on the wire, `_meta` included. The model in force at
prompt time, which the wire's `session/prompt` carries no field for, is
recorded separately as its own pseudo-method line (`MODEL_AT_PROMPT`).
`--stop` is the end-of-turn reason
the prompt is answered with (`end_turn` unless given).
`--no-additional-dirs` leaves the `additionalDirectories` session capability
unadvertised. `--linger` starts a child in the agent's own process group that
inherits its stderr and sleeps for `HANG_SECONDS`, writing the child's pid to
`orphan_pid_file(RECORD)`, then ends the turn as usual and exits once its input
closes: an agent that is gone while something it started still holds stderr.
`--fail` breaks the prompt partway through, after the preamble:
`exit` writes `STDERR_LINE` to stderr and exits 3, `kill` sends the agent
SIGKILL, `error` answers the prompt with an internal error, and `hang` closes
its stdout, writes `STDERR_LINE` to stderr and lingers for `HANG_SECONDS`
without exiting, as an agent whose stdio loop died while its process did not.
`orphan` first starts a child that inherits its stderr and sleeps for
`HANG_SECONDS`, writing the child's pid to `orphan_pid_file(RECORD)`, then does
what `hang` does: a wrapper whose real agent keeps stderr open. `detach` is
`orphan` with the child in a session of its own, out of reach of a kill of the
agent's process group. `set_model` leaves the model on offer but answers every
`session/set_config_option` for it with a JSON-RPC error, as an agent that
offers a model and then refuses to switch to it.

Three more options make it do work, in place of the edit it otherwise only
reports. What it did, and what the client answered, is appended to RECORD as
`did/<what>` lines beside the requests:

    [--act ACTIONS] [--probe terminal|ask] [--unasked PREFIX]
    [--only PREFIX] [--split] [--offer KIND,...]

`--usage reported|extra|malformed|uncounted|empty|negative` has the prompt's
response carry a `usage` payload: the protocol's own counts, the same with
fields no client knows, counts that are not numbers, a payload with none of
the four counts, an empty one, or a negative count. Without it the response
carries none.
`--cost USD|EUR` has the agent send a `usage_update` before the answer, with
the session's cumulative cost in that currency, as the protocol's own update
carries it.

`--act` names a JSON file holding a list of actions, taken in order:

- `{"terminal": COMMAND, "args": [...]}` has the client run a command through
  its terminal capability — create, wait for exit, read the output, release —
  and records the output and exit status, or the error the client answered.
  `"kill_after": SECONDS` gives up waiting for it after that long and kills it
  first, as an agent with a timeout of its own does; `"limit": BYTES` is the
  output byte limit it asks for; `"raw_input": {...}` is what its tool call
  says it is running, when that differs from the terminal it creates.
- `{"write": PATH, "content": TEXT}` and `{"read": PATH, "line": N, "limit": N}`
  go through the client's file capability, recording the error for one that
  is refused.
- `{"unasked": COMMAND, "status": STATUS, "output": TEXT}` runs a command of its
  own without asking, ending its tool call with STATUS (`completed` unless said)
  and TEXT as what it produced (`done` unless said).
- `{"edit": PATH, "content": TEXT}` writes the file itself, on disk, without
  asking and without the client's file capability: an agent that edits with a
  tool of its own. `"output"` of the tool call is `done`.
- `{"ask": KIND, "command": ..., "paths": [...], "options": [KIND, ...]}` runs a
  tool of the agent's own the way an agent that executes its own tools does:
  it asks permission, naming the command in its raw input and the paths as
  locations, offering the option kinds given (all four unless said), and
  records which it was answered. It "runs" the tool only if allowed — a
  `did/run` line, never a real process — and on a cancelled answer waits for
  the client's `session/cancel` and ends the turn `cancelled`, unless
  `"carry_on": true`. `"sparse": true` sends a permission request naming
  nothing but the tool call's id, the tool call's start having said the rest.
  `"locations": false` sends an edit's target as `path` in its raw input
  instead, with no locations at all. `"title": TEXT` is the request's title
  in place of the command or `Edit <paths>`; with no paths and no command the
  raw input names no target either, so the title is all there is.

`--probe` has it attempt what the prompt names, one attempt per inline code
span: an absolute path is a write to it, anything else a command — through
the client's capabilities (`terminal`) or by asking permission (`ask`).
`--unasked` makes it run, without asking, any command starting with PREFIX:
an agent whose own configuration does not flag that class, so the client
only hears of it from the tool call's updates. That run too is only
reported, never performed. `--only` has it attempt just the commands starting
with PREFIX; `--split` sends a probed terminal command as a program and its
arguments rather than one line; `--offer` is the option kinds its probed asks
offer.
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
import time
from pathlib import Path
from typing import Any, Literal, cast, get_args

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
from acp.connection import StreamDirection, StreamEvent
from acp.helpers import update_available_commands
from acp.interfaces import Agent, Client
from acp.schema import (
    AgentCapabilities,
    AvailableCommand,
    Cost,
    Implementation,
    PermissionOption,
    PromptCapabilities,
    SessionAdditionalDirectoriesCapabilities,
    SessionCapabilities,
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SessionMode,
    SessionModeState,
    StopReason,
    ToolCallLocation,
    ToolCallUpdate,
    UsageUpdate,
)
from pydantic import ValidationError

SESSION = "sess_7Hq2Zk4PxYwVb9nR"

# What the agent offers for its `model` config option, and runs on unless the
# client picks another.
MODELS = ("swift-1", "deep-2")
DEFAULT_MODEL = MODELS[0]

# The wire's `session/prompt` carries no model field, so the fake records the
# model it is about to answer with as a line of its own, in the same
# `{"method", "params"}` shape as every wire message: a pseudo-method a test
# can look up with `requests()` like any other.
MODEL_AT_PROMPT = "test/model_at_prompt"

# The agent's own environment as it started, for the variables a test names: a
# pseudo-method line like the above, `{"ABK_GATEWAY_KEY": value-or-null}`.
ENVIRONMENT = "test/environment"
WATCHED_ENV = ("ABK_GATEWAY_KEY",)

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

# What `--usage` puts in the prompt response, as it goes on the wire
# (`PromptResponse.usage`): the protocol's own names, then the same with a
# field no client knows yet, then one whose counts are not numbers.
REPORTED_USAGE = {
    "totalTokens": 9200,
    "inputTokens": 7000,
    "outputTokens": 1500,
    "thoughtTokens": 300,
    "cachedReadTokens": 400,
    "cachedWriteTokens": 0,
}
USAGE_PAYLOADS: dict[str, dict[str, Any]] = {
    "reported": REPORTED_USAGE,
    "extra": {**REPORTED_USAGE, "serviceTier": "priority", "_meta": {"billing": {"plan": "x"}}},
    "malformed": {"totalTokens": "lots", "inputTokens": None, "outputTokens": [1]},
    "uncounted": {"totalTokens": 9200},
    "empty": {},
    "negative": {"inputTokens": -1, "outputTokens": 1500},
}

# What `--cost` reports: the session's cumulative spend so far.
COST_AMOUNT = 0.31

# The permission options it offers, as a real agent words them: the ids are
# its own, so only the kinds say which option refuses.
OPTIONS = {
    "allow_once": ("proceed_once", "Allow once"),
    "allow_always": ("proceed_always", "Always allow"),
    "reject_once": ("cancel", "Reject"),
    "reject_always": ("never", "Always reject"),
}
# The most output it asks the client to keep of a command.
OUTPUT_LIMIT = 64 * 1024
# Seconds it waits for the client's `session/cancel` after a cancelled answer.
CANCEL_WAIT = 2.0


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
        self,
        record: Path,
        stop: StopReason,
        *,
        additional_dirs: bool = True,
        linger: bool = False,
        fail: str | None = None,
        acts: list[dict[str, Any]] | None = None,
        probe: str | None = None,
        unasked: str | None = None,
        only: str | None = None,
        split: bool = False,
        offer: list[str] | None = None,
        usage: str | None = None,
        cost: str | None = None,
    ) -> None:
        self._usage = usage
        self._cost = cost
        self._record = record
        self._stop = stop
        self._additional_dirs = additional_dirs
        self._linger = linger
        self._fail = fail
        self._acts = acts
        self._probe = probe
        self._unasked = unasked
        self._only = only
        self._split = split
        self._offer = offer
        self._model = DEFAULT_MODEL
        self._client: Client | None = None
        self._cwd = str(Path.cwd())
        self._calls = 0
        self._cancelled = asyncio.Event()

    def on_connect(self, conn: Client) -> None:
        self._client = conn

    def observe(self, event: StreamEvent) -> None:
        """The connection's own record of what it received, byte for byte —
        not rebuilt from a handler's keyword arguments, so nothing a handler
        does not itself name (`_meta`, an unhandled field) goes missing."""
        if event.direction != StreamDirection.INCOMING:
            return
        method = event.message.get("method")
        if method is None:
            return
        self._write(method, event.message.get("params") or {})

    def _write(self, method: str, params: dict[str, Any]) -> None:
        with self._record.open("a") as out:
            out.write(json.dumps({"method": method, "params": params}) + "\n")

    async def initialize(
        self, protocol_version: int, client_capabilities=None, client_info=None, **kwargs: Any
    ) -> InitializeResponse:
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
        return None

    async def new_session(
        self, cwd: str, additional_directories=None, mcp_servers=None, **kwargs: Any
    ) -> NewSessionResponse:
        self._cwd = cwd
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
        if config_id == "model" and self._fail == "set_model":
            raise RequestError.internal_error({"details": "the model is not available to select"})
        if config_id == "model" and value in MODELS:
            self._model = str(value)
        return SetSessionConfigOptionResponse(config_options=[_model_option(self._model)])

    async def set_session_mode(self, session_id: str, mode_id: str, **kwargs: Any) -> None:
        return None

    async def prompt(self, session_id: str, prompt: list, **kwargs: Any) -> PromptResponse:
        # The wire's `session/prompt` params carry no model field — the
        # session already carries whichever model was selected — so the
        # model in force is recorded here, as its own line.
        self._write(MODEL_AT_PROMPT, {"model": self._model})
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
        if self._cost is not None:
            await send(
                UsageUpdate(
                    session_update="usage_update",
                    used=9200,
                    size=200000,
                    cost=Cost(amount=COST_AMOUNT, currency=self._cost),
                )
            )
        for chunk in PREAMBLE_CHUNKS:
            await send(update_agent_message_text(chunk))
        if self._fail == "exit":
            print(STDERR_LINE, file=sys.stderr, flush=True)
            sys.exit(3)
        if self._fail == "kill":
            os.kill(os.getpid(), signal.SIGKILL)
        if self._fail == "error":
            raise RequestError.internal_error({"details": "the model endpoint went away"})
        if self._linger or self._fail in ("orphan", "detach"):
            self._leave_child(new_session=self._fail == "detach")
        if self._fail in ("hang", "orphan", "detach"):
            os.close(1)
            print(STDERR_LINE, file=sys.stderr, flush=True)
            time.sleep(HANG_SECONDS)
        if self._acts is not None or self._probe is not None:
            if not await self._work(session_id, prompt):
                return self._response("cancelled")
            for chunk in ANSWER_CHUNKS:
                await send(update_agent_message_text(chunk))
            return self._response()
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
        return self._response()

    def _response(self, stop: StopReason | None = None) -> PromptResponse:
        """The prompt's answer, carrying the usage `--usage` asks for. Built
        without validation, so a payload the library itself would refuse
        (`malformed`) still goes out on the wire as an agent could send it."""
        stop = stop or self._stop
        if self._usage is None:
            return PromptResponse(stop_reason=stop)
        return PromptResponse.model_construct(stop_reason=stop, usage=USAGE_PAYLOADS[self._usage])

    def _leave_child(self, *, new_session: bool) -> None:
        """Start a child that holds this agent's stderr for `HANG_SECONDS`."""
        child = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({HANG_SECONDS})"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            start_new_session=new_session,
        )
        orphan_pid_file(self._record).write_text(str(child.pid))

    async def _work(self, session_id: str, prompt: list) -> bool:
        """Take `--act`'s actions, or `--probe`'s attempts; False once the
        client has cancelled the turn."""
        acts = list(self._acts or [])
        if self._probe is not None:
            text = " ".join(getattr(block, "text", "") for block in prompt)
            acts += [
                self._attempt(span)
                for span in re.findall(r"`([^`\n]+)`", text)
                if self._only is None or span.startswith(self._only)
            ]
        for act in acts:
            if "terminal" in act:
                await self._terminal(
                    session_id,
                    act["terminal"],
                    act.get("args", []),
                    kill_after=act.get("kill_after"),
                    limit=act.get("limit", OUTPUT_LIMIT),
                    raw_input=act.get("raw_input"),
                )
            elif "write" in act:
                await self._write_file(session_id, act["write"], act.get("content", ""))
            elif "read" in act:
                await self._read(session_id, act["read"], act.get("line"), act.get("limit"))
            elif "edit" in act:
                await self._edit_unasked(session_id, act["edit"], act.get("content", ""))
            elif "titled_terminal" in act:
                await self._run_titled_terminal(
                    session_id, act["titled_terminal"], act.get("also", 0), act.get("output")
                )
            elif "unasked" in act:
                await self._run_unasked(
                    session_id, act["unasked"], act.get("status", "completed"), act.get("output")
                )
            elif not await self._ask(session_id, act):
                return False
        return True

    def _attempt(self, span: str) -> dict[str, Any]:
        """One attempt at what an inline code span of the prompt names."""
        if span.startswith("/") and " " not in span:
            if self._probe == "terminal":
                return {"write": span, "content": "probe\n"}
            return {"ask": "edit", "paths": [span]}
        if self._unasked and span.startswith(self._unasked):
            return {"unasked": span}
        if self._probe == "terminal":
            if self._split:
                command, *args = span.split()
                return {"terminal": command, "args": args}
            return {"terminal": span, "args": []}
        return {"ask": "execute", "command": span, "options": self._offer or list(OPTIONS)}

    def _call_id(self) -> str:
        self._calls += 1
        return f"call_{self._calls:02d}"

    async def _send(self, session_id: str, update: Any) -> None:
        client = self._client
        assert client is not None
        await client.session_update(session_id=session_id, update=update)

    async def _terminal(
        self,
        session_id: str,
        command: str,
        args: list[str],
        *,
        kill_after: float | None = None,
        limit: int = OUTPUT_LIMIT,
        raw_input: dict[str, Any] | None = None,
    ) -> None:
        client = self._client
        assert client is not None
        entry: dict[str, Any] = {"command": command, "args": args}
        call = self._call_id()
        await self._send(
            session_id,
            start_tool_call(
                call,
                " ".join([command, *args]),
                kind="execute",
                status="in_progress",
                raw_input=raw_input or {"command": command, "args": args},
            ),
        )
        try:
            created = await client.create_terminal(
                session_id=session_id,
                command=command,
                args=args,
                env=[],
                cwd=self._cwd,
                output_byte_limit=limit,
            )
            try:
                exited = await asyncio.wait_for(
                    client.wait_for_terminal_exit(
                        session_id=session_id, terminal_id=created.terminal_id
                    ),
                    timeout=kill_after,
                )
            except TimeoutError:
                await client.kill_terminal(session_id=session_id, terminal_id=created.terminal_id)
                exited = await client.wait_for_terminal_exit(
                    session_id=session_id, terminal_id=created.terminal_id
                )
            output = await client.terminal_output(
                session_id=session_id, terminal_id=created.terminal_id
            )
            await client.release_terminal(session_id=session_id, terminal_id=created.terminal_id)
            entry.update(
                output=output.output,
                truncated=output.truncated,
                exitCode=exited.exit_code,
                signal=exited.signal,
            )
            status = "completed" if exited.exit_code == 0 else "failed"
        except RequestError as exc:
            entry["error"] = exc.to_error_obj()
            status = "failed"
        except ValidationError as exc:
            # A client without the method answers null, which is no terminal.
            entry["error"] = {"message": "the client's answer was not a terminal", "data": str(exc)}
            status = "failed"
        self._write("did/terminal", entry)
        shown = entry.get("output")
        await self._send(
            session_id,
            update_tool_call(
                call,
                status=status,
                content=[tool_content(text_block(shown))] if shown else None,
            ),
        )

    async def _write_file(self, session_id: str, path: str, content: str) -> None:
        client = self._client
        assert client is not None
        entry: dict[str, Any] = {"path": path}
        try:
            await client.write_text_file(session_id=session_id, path=path, content=content)
            entry["ok"] = True
        except RequestError as exc:
            entry["error"] = exc.to_error_obj()
        self._write("did/write", entry)

    async def _read(self, session_id: str, path: str, line: int | None, limit: int | None) -> None:
        client = self._client
        assert client is not None
        entry: dict[str, Any] = {"path": path}
        try:
            read = await client.read_text_file(
                session_id=session_id, path=path, line=line, limit=limit
            )
            entry["content"] = read.content
        except RequestError as exc:
            entry["error"] = exc.to_error_obj()
        self._write("did/read", entry)

    async def _ask(self, session_id: str, act: dict[str, Any]) -> bool:
        """Ask before running one of its own tools; False once cancelled."""
        client = self._client
        assert client is not None
        kind = act["ask"]
        command = act.get("command")
        paths = act.get("paths", [])
        offered = act.get("options", list(OPTIONS))
        call = self._call_id()
        title = act.get("title") or (command if command is not None else f"Edit {' '.join(paths)}")
        raw_input: dict[str, Any] = (
            {"command": command} if command is not None else {"paths": paths, "new": "probe\n"}
        )
        sends_locations = act.get("locations", True)
        if command is None and not sends_locations:
            raw_input = {"path": paths[0], "new": "probe\n"} if paths else {"new": "probe\n"}
        locations = (
            [ToolCallLocation(path=path, line=None) for path in paths] if sends_locations else []
        )
        await self._send(
            session_id,
            start_tool_call(
                call, title, kind=kind, status="pending", locations=locations, raw_input=raw_input
            ),
        )
        answer = await client.request_permission(
            session_id=session_id,
            tool_call=ToolCallUpdate(tool_call_id=call)
            if act.get("sparse")
            else ToolCallUpdate(
                tool_call_id=call,
                title=title,
                kind=kind,
                status="pending",
                locations=locations or None,
                raw_input=raw_input,
            ),
            options=[
                PermissionOption(option_id=OPTIONS[k][0], name=OPTIONS[k][1], kind=k)
                for k in offered
            ],
        )
        outcome = answer.outcome
        chosen = getattr(outcome, "option_id", None)
        chosen_kind = next((k for k in offered if OPTIONS[k][0] == chosen), None)
        self._write(
            "did/ask",
            {
                "kind": kind,
                "command": command,
                "paths": paths,
                "offered": offered,
                "outcome": outcome.outcome,
                "optionId": chosen,
                "optionKind": chosen_kind,
            },
        )
        if outcome.outcome == "cancelled":
            await self._send(session_id, update_tool_call(call, status="failed"))
            if act.get("carry_on"):
                return True
            try:
                await asyncio.wait_for(self._cancelled.wait(), timeout=CANCEL_WAIT)
            except TimeoutError:
                pass
            return False
        if chosen_kind is not None and chosen_kind.startswith("allow"):
            self._write("did/run", {"kind": kind, "command": command, "paths": paths})
            await self._send(session_id, update_tool_call(call, status="completed"))
        else:
            await self._send(session_id, update_tool_call(call, status="failed"))
        return True

    async def _edit_unasked(self, session_id: str, path: str, content: str) -> None:
        """Edit a file with a tool of its own, never asking the client."""
        call = self._call_id()
        await self._send(
            session_id,
            start_tool_call(
                call,
                f"Edit {path}",
                kind="edit",
                status="in_progress",
                locations=[ToolCallLocation(path=path, line=None)],
                raw_input={"path": path, "new": content},
            ),
        )
        Path(path).write_text(content)
        self._write("did/edit", {"path": path})
        await self._send(session_id, update_tool_call(call, status="completed"))

    async def _run_unasked(
        self,
        session_id: str,
        command: str,
        status: Literal["completed", "failed", "in_progress", "pending"] = "completed",
        output: str | None = None,
    ) -> None:
        """Run a command of its own without asking: the client sees only the
        tool call's updates. `output` is what the call's update says it
        produced, in place of the usual `done`."""
        text = "done" if output is None else output
        call = self._call_id()
        await self._send(
            session_id,
            start_tool_call(
                call, command, kind="execute", status="in_progress", raw_input={"command": command}
            ),
        )
        self._write("did/run", {"kind": "execute", "command": command, "paths": []})
        await self._send(
            session_id,
            update_tool_call(
                call,
                status=status,
                content=[tool_content(text_block(text))],
                raw_output={"exit_code": 0, "stdout": f"{text}\n", "stderr": ""},
            ),
        )

    async def _run_titled_terminal(
        self, session_id: str, command: str, also: int, output: str | None
    ) -> None:
        """A terminal call that sends no raw input: the command in
        the title (` + N commands` when batched) and as a `$ ` line of the
        start's content, and a failed end with text and no raw output."""
        call = self._call_id()
        title = f"terminal: {command}"
        if also:
            title += f" + {also} command" + ("s" if also > 1 else "")
        await self._send(
            session_id,
            start_tool_call(
                call,
                title,
                kind="execute",
                status="in_progress",
                content=[tool_content(text_block(f"$ {command}"))],
            ),
        )
        self._write("did/run", {"kind": "execute", "command": command, "paths": []})
        await self._send(
            session_id,
            update_tool_call(
                call,
                status="failed",
                content=[tool_content(text_block(f"terminal failed: {output}"))],
            ),
        )

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        self._cancelled.set()

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        return None


def orphan_pid_file(record: Path) -> Path:
    """Where `--linger` and `--fail orphan`/`detach` write the pid of the child
    they leave behind."""
    return record.with_suffix(".orphan")


def command(
    record: Path,
    *,
    stop: str = "end_turn",
    additional_dirs: bool = True,
    linger: bool = False,
    fail: str | None = None,
    act: list[dict[str, Any]] | None = None,
    probe: str | None = None,
    unasked: str | None = None,
    only: str | None = None,
    split: bool = False,
    offer: list[str] | None = None,
    usage: str | None = None,
    cost: str | None = None,
) -> list[str]:
    """The argv that starts this agent, as `runtimes.acp.command` names one.
    `act`'s actions are written beside `record`, where `--act` reads them."""
    argv = [sys.executable, str(Path(__file__).resolve()), str(record), "--stop", stop]
    if not additional_dirs:
        argv.append("--no-additional-dirs")
    if linger:
        argv.append("--linger")
    if fail:
        argv += ["--fail", fail]
    if act is not None:
        actions = record.with_suffix(".act.json")
        actions.write_text(json.dumps(act))
        argv += ["--act", str(actions)]
    if probe:
        argv += ["--probe", probe]
    if unasked:
        argv += ["--unasked", unasked]
    if only:
        argv += ["--only", only]
    if split:
        argv.append("--split")
    if offer:
        argv += ["--offer", ",".join(offer)]
    if usage:
        argv += ["--usage", usage]
    if cost:
        argv += ["--cost", cost]
    return argv


def use_agent(
    record: Path,
    *,
    stop: str = "end_turn",
    additional_dirs: bool = True,
    linger: bool = False,
    fail: str | None = None,
    act: list[dict[str, Any]] | None = None,
    probe: str | None = None,
    unasked: str | None = None,
    only: str | None = None,
    split: bool = False,
    offer: list[str] | None = None,
    usage: str | None = None,
    cost: str | None = None,
) -> None:
    """Point the active workspace's `runtimes.acp.command` at this agent,
    answering every prompt with `stop`."""
    use_command(
        command(
            record,
            stop=stop,
            additional_dirs=additional_dirs,
            linger=linger,
            fail=fail,
            act=act,
            probe=probe,
            unasked=unasked,
            only=only,
            split=split,
            offer=offer,
            usage=usage,
            cost=cost,
        )
    )


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
    parser.add_argument("--stop", default="end_turn", choices=get_args(StopReason))
    parser.add_argument("--no-additional-dirs", dest="additional_dirs", action="store_false")
    parser.add_argument("--linger", action="store_true")
    parser.add_argument(
        "--fail", choices=["exit", "kill", "error", "hang", "orphan", "detach", "set_model"]
    )
    parser.add_argument("--act", type=Path)
    parser.add_argument("--probe", choices=["terminal", "ask"])
    parser.add_argument("--unasked")
    parser.add_argument("--only")
    parser.add_argument("--split", action="store_true")
    parser.add_argument("--offer")
    parser.add_argument("--usage", choices=sorted(USAGE_PAYLOADS))
    parser.add_argument("--cost", choices=["USD", "EUR"])
    args = parser.parse_args()
    agent = FakeAgent(
        args.record,
        args.stop,
        additional_dirs=args.additional_dirs,
        linger=args.linger,
        fail=args.fail,
        acts=json.loads(args.act.read_text()) if args.act else None,
        probe=args.probe,
        unasked=args.unasked,
        only=args.only,
        split=args.split,
        offer=args.offer.split(",") if args.offer else None,
        usage=args.usage,
        cost=args.cost,
    )
    agent._write(ENVIRONMENT, {name: os.environ.get(name) for name in WATCHED_ENV})
    # Only the methods these tests drive: the rest answer "method not found".
    asyncio.run(run_agent(cast(Agent, agent), observers=[agent.observe]))


if __name__ == "__main__":
    main()
