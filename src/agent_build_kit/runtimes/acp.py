"""An agent speaking the Agent Client Protocol, as an agent runtime.

Spawns the agent `runtimes.acp.command` names and drives one session per run
over stdio, on its own event loop so callers stay synchronous.

The prompt's response carries an end-of-turn reason, so the outcome is read
from that and never from the answer's text: `end_turn` is an answer, a
ceiling or a refusal is a failed result saying which, and `cancelled` is an
interruption, as is an agent killed by a signal from elsewhere — not one abk
killed for failing to exit, which is a failure. `AgentRequest.allowed_tools`/
`denied_tools` are inert here — the protocol has no per-session tool list
(docs/agent-runtimes.md) — so a run that carries either is let through with a
once-per-run notice that tool scope comes from the agent's own configuration,
*unless* the list is the only thing standing between an `edit`-mode run and
editing (no edit tool named in `allowed_tools`) — the shape of a review run,
whose reviewer-cannot-edit guarantee (docs/architecture.md) this runtime
cannot keep, so that request is refused before the agent is spawned. A named
`worktree` is refused too, not ignored.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from acp import PROTOCOL_VERSION, RequestError, connect_to_agent, text_block
from acp.connection import StreamEvent
from acp.interfaces import Agent, Client
from acp.schema import (
    AgentMessageChunk,
    ClientCapabilities,
    DeniedOutcome,
    Implementation,
    InitializeResponse,
    PermissionOption,
    RequestPermissionResponse,
    SessionConfigOptionSelect,
    SessionConfigSelectGroup,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
)

from agent_build_kit import __version__, config
from agent_build_kit.config import ModelsConfig
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PolicyCoverage,
    PolicyReport,
)

NAME = "acp"

# A JSON-RPC message is one line; a file's contents can make that line far
# longer than asyncio's 64 KiB default.
LINE_LIMIT = 16 * 1024 * 1024

# Seconds an agent has to exit once its input is closed before it is killed,
# and then for its stderr to close: a process it left behind can hold it open.
EXIT_GRACE = 5.0

# Bytes of the agent's stderr read at a time.
STDERR_CHUNK = 64 * 1024

# Seconds between looks at whether the agent has exited.
EXIT_POLL = 0.05

# How long a turn that did not end normally reads in the unit's log: each
# calls for something different of whoever reads it.
STOPPED: dict[str, str] = {
    "max_tokens": "the agent reached its token ceiling before finishing the turn",
    "max_turn_requests": "the agent reached its ceiling on model requests in one turn",
    "refusal": "the agent refused to carry on with the prompt",
}

# Claude Code tool names (in `AgentRequest.allowed_tools`'s own syntax) that
# can edit a file. Only these two are named by anything in this codebase
# today; a bare name is matched before any `(...)` pattern.
EDIT_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})


def _names_edit_tool(tool_list: str) -> bool:
    return any(token.split("(", 1)[0] in EDIT_TOOLS for token in tool_list.split())


def _scope_warning(request: AgentRequest) -> str | None:
    """Once per run: neither field reaches the agent, so a caller relying on
    either to narrow what it does is not told by this runtime — only by the
    log."""
    named = [
        field
        for field, value in (
            ("allowed_tools", request.allowed_tools),
            ("denied_tools", request.denied_tools),
        )
        if value
    ]
    if not named:
        return None
    return (
        f"{' and '.join(named)} ignored: runtimes.acp has no per-session tool "
        "list to apply them to; tool scope comes from the agent's own configuration"
    )


def _review_guarantee_broken(request: AgentRequest) -> str | None:
    """None unless `allowed_tools` is the only thing standing between an
    `edit`-mode run and editing — the shape `wiring.build_run_review` sends,
    and the guarantee docs/architecture.md states as a property of the
    pipeline: "The reviewer cannot edit". This runtime has no per-session
    tool list to enforce that with, so it refuses rather than reviewing under
    a promise it cannot keep."""
    if request.permission_mode != "edit" or not request.allowed_tools:
        return None
    if _names_edit_tool(request.allowed_tools):
        return None
    return (
        f"runtimes.acp cannot enforce allowed_tools={request.allowed_tools!r}: the "
        "protocol has no per-session tool list, and this list names no edit tool, "
        "so this run is relying on it to keep the reviewer from editing "
        '("The reviewer cannot edit", docs/architecture.md) — a guarantee this '
        "runtime cannot keep. Refusing rather than reviewing under a broken promise."
    )


class _Session:
    """The client end of one run: what the agent streams, as progress and as
    the answer."""

    def __init__(self, report: Callable[[str], None] | None) -> None:
        self._report = report
        # The message since the last tool call: the one that closes the turn.
        self._message: list[str] = []
        # The message not yet reported: it streams in token-sized chunks, and
        # reads as one line once something else starts or the turn ends.
        self._unsaid: list[str] = []
        self._titles: dict[str, str] = {}

    @property
    def answer(self) -> str:
        return "".join(self._message)

    def on_connect(self, conn: Agent) -> None:
        pass

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        if isinstance(update, AgentMessageChunk):
            if isinstance(update.content, TextContentBlock):
                self._message.append(update.content.text)
                self._unsaid.append(update.content.text)
        elif isinstance(update, ToolCallStart):
            self.said()
            self._message = []
            self._titles[update.tool_call_id] = update.title
            self._tell(update.title)
        elif isinstance(update, ToolCallProgress):
            self.said()
            self._message = []
            title = update.title or self._titles.get(update.tool_call_id, update.tool_call_id)
            if update.status:
                self._tell(f"{title}: {update.status}")

    async def request_permission(
        self, session_id: str, tool_call: ToolCallUpdate, options: list[PermissionOption], **kwargs
    ) -> RequestPermissionResponse:
        # Nothing is permitted until the permission rules are answered here.
        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))

    def said(self) -> None:
        """The message streamed since the last line, as one line."""
        text = "".join(self._unsaid)
        self._unsaid = []
        if text.strip():
            self._tell(f"says: {text}")

    def notice(self, line: str) -> None:
        """Something the operator should know about the run, not a step of it:
        to stderr, and to the run's log when it has one."""
        print(f"{NAME}: {line}", file=sys.stderr)
        self._tell(line)

    def _tell(self, line: str) -> None:
        if self._report is None:
            return
        try:
            self._report(f"  {' '.join(line.split())}")
        except Exception:  # noqa: BLE001 — progress is for a reader, never the run's to lose
            pass


def _offered(option: SessionConfigOptionSelect) -> list[str]:
    values: list[str] = []
    for entry in option.options:
        if isinstance(entry, SessionConfigSelectGroup):
            values += [choice.value for choice in entry.options]
        else:
            values.append(entry.value)
    return values


def _model_option(options: list[Any] | None) -> SessionConfigOptionSelect | None:
    for option in options or []:
        if isinstance(option, SessionConfigOptionSelect) and (
            option.category == "model" or option.id == "model"
        ):
            return option
    return None


class AcpRuntime:
    name: str = NAME
    implemented: bool = False
    policy_coverage: PolicyCoverage = "agent_flagged"
    supports_usage_tracking: bool = False
    supports_streaming: bool = True
    # There is no default agent to spawn.
    requires: tuple[str, ...] = ("command",)
    agent_command: tuple[str, ...] = ()
    # No name is this runtime's own — an empty role means the agent's own
    # default, which `_turn` reads as "select nothing" (docs/agent-runtimes.md).
    default_models: ModelsConfig = ModelsConfig(
        implement="", rework="", review="", rework_review=""
    )

    def __init__(self) -> None:
        # The models already reported as not on offer or refused once set —
        # both share this set, so a model reported for one reason is not
        # reported again for the other — and whether the agent's lack of
        # extra workspace roots has been: once per runtime, not once per unit
        # a tick runs through it.
        self._unoffered: set[str] = set()
        self._no_roots_told = False

    def run(self, request: AgentRequest) -> AgentResult:
        if request.worktree:
            # Running it in cwd instead would put a track phase in the
            # planning checkout.
            return AgentResult(
                ok=False,
                text="",
                error=f"runtimes.{NAME} does not create a named worktree; "
                f"{request.worktree!r} needs a runtime that does",
            )
        if broken := _review_guarantee_broken(request):
            return AgentResult(ok=False, text="", error=broken)
        command = config.runtime_entry(name=NAME).command or list(self.agent_command)
        if not command:
            return AgentResult(ok=False, text="", error=f"runtimes.{NAME}.command is not set")
        return asyncio.run(self._run(command, request))

    async def _run(self, command: list[str], request: AgentRequest) -> AgentResult:
        session = _Session(request.on_event)
        if warning := _scope_warning(request):
            session.notice(warning)
        try:
            # In a session of its own, so a kill reaches whatever the command
            # forks (a wrapper's real agent) and not only the command itself.
            # A Ctrl-C at the terminal then reaches abk alone; abk closes the
            # agent's input and, after the grace, kills its group all the same.
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=request.cwd,
                limit=LINE_LIMIT,
                start_new_session=True,
            )
        except OSError as exc:
            return AgentResult(ok=False, text="", error=f"could not start {command[0]}: {exc}")
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        # Drained as it arrives, so an agent that logs a lot never blocks on
        # a full pipe; kept for the error when the run breaks.
        stderr = _Drained(process.stderr)
        # The whole exchange, one JSON-RPC message per line, for `keep_record`
        # (AgentResult.raw) — a caller's only way to see what the agent did
        # beyond the streamed progress lines and the final answer.
        raw_lines: list[str] = []

        def _record(event: StreamEvent) -> None:
            raw_lines.append(json.dumps(event.message))

        # No file or terminal capability is advertised, so the agent must not
        # call those methods; one that does is answered "method not found".
        conn = connect_to_agent(
            cast(Client, session), process.stdin, process.stdout, observers=[_record]
        )
        ended_already = False
        try:
            stop_reason = await self._turn(conn, session, request)
        except RequestError as exc:
            return AgentResult(
                ok=False,
                text="",
                error=f"the agent answered an error: {exc}",
                raw="\n".join(raw_lines),
            )
        except (ConnectionError, EOFError) as exc:
            said, killed = await _ended(process, stderr)
            ended_already = True
            if killed:
                # Its stdio went but its process stayed: the agent broke, and
                # the kill that ended it is ours, so it is no interruption.
                return AgentResult(
                    ok=False,
                    text="",
                    error=f"the agent went away: {exc}; it did not exit and was killed. "
                    f"{said}".strip(),
                    raw="\n".join(raw_lines),
                )
            if process.returncode is not None and process.returncode < 0:
                raise AgentInterrupted(
                    f"the agent was killed by signal {-process.returncode}"
                ) from exc
            return AgentResult(
                ok=False,
                text="",
                error=f"the agent went away: {exc} {said}".strip(),
                raw="\n".join(raw_lines),
            )
        finally:
            session.said()
            await conn.close()
            if not ended_already:
                await _ended(process, stderr)

        if stop_reason == "cancelled":
            raise AgentInterrupted("the agent's turn was cancelled")
        if stop_reason != "end_turn":
            error = STOPPED.get(stop_reason, f"the turn ended with {stop_reason!r}")
            return AgentResult(
                ok=False,
                text=session.answer,
                error=error,
                stop_reason=stop_reason,
                raw="\n".join(raw_lines),
            )
        return AgentResult(
            ok=True, text=session.answer, stop_reason=stop_reason, raw="\n".join(raw_lines)
        )

    async def _turn(self, conn: Any, session: _Session, request: AgentRequest) -> str:
        initialized = await conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="abk", title="agent-build-kit", version=__version__),
        )
        cwd = request.cwd or Path.cwd()
        opened = await conn.new_session(
            cwd=str(cwd),
            additional_directories=self._roots(initialized, session, request),
            mcp_servers=[],
        )
        if request.model:
            await self._select_model(
                conn, session, opened.session_id, opened.config_options, request.model
            )
        # `session.answer` is only the full text once every `session/update`
        # notification up to the answer has been handled: this library
        # (pinned in pyproject.toml) awaits that before `prompt()` returns,
        # and `conn.close()` cancels any still in flight, so a version bump
        # that changes the ordering could silently truncate it.
        response = await conn.prompt(
            session_id=opened.session_id, prompt=[text_block(request.prompt)]
        )
        return str(response.stop_reason)

    def _roots(
        self, initialized: InitializeResponse, session: _Session, request: AgentRequest
    ) -> list[str] | None:
        """The extra readable directories, sent only to an agent that says it
        takes them: one that does not may drop the field without a word."""
        if not request.add_dirs:
            return None
        capabilities = initialized.agent_capabilities
        sessions = capabilities.session_capabilities if capabilities is not None else None
        if sessions is not None and sessions.additional_directories is not None:
            return [str(directory) for directory in request.add_dirs]
        if not self._no_roots_told:
            self._no_roots_told = True
            named = ", ".join(str(directory) for directory in request.add_dirs)
            session.notice(
                f"the agent does not take additional workspace roots; not declared to it: {named}"
            )
        return None

    async def _select_model(
        self, conn: Any, session: _Session, session_id: str, options: list[Any] | None, model: str
    ) -> None:
        """Selected when the agent offers it; otherwise the run carries on
        with the agent's own default, which is not a failure — nor is the
        agent refusing to set it once offered."""
        option = _model_option(options)
        if option is not None and model in _offered(option):
            if option.current_value != model:
                try:
                    await conn.set_config_option(
                        config_id=option.id, session_id=session_id, value=model
                    )
                except RequestError as exc:
                    if model not in self._unoffered:
                        self._unoffered.add(model)
                        session.notice(
                            f"the agent refused model {model!r}: {exc}; running on its default"
                        )
            return
        if model not in self._unoffered:
            self._unoffered.add(model)
            offered = ", ".join(_offered(option)) if option is not None else "none"
            session.notice(
                f"the agent does not offer model {model!r} (offers: {offered}); "
                "running on its default"
            )

    def get_usage_status(self) -> None:
        """Billed per token, with no window to exhaust (docs/agent-runtimes.md)."""
        return None

    def check_policy(self, cwd: Path) -> PolicyReport:
        raise NotImplementedError


class _Drained:
    """A stream read to its end as it arrives, what it said so far always at
    hand."""

    def __init__(self, stream: asyncio.StreamReader) -> None:
        self._said = bytearray()
        self._task = asyncio.create_task(self._drain(stream))

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        try:
            while chunk := await stream.read(STDERR_CHUNK):
                self._said += chunk
        except OSError:
            # A pipe that broke has ended as surely as one that closed.
            pass

    async def said(self) -> tuple[str, bool]:
        """What the stream said, waiting at most `EXIT_GRACE` for its end, and
        whether it ended: a process can keep it open for as long as it likes."""
        if not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=EXIT_GRACE)
            except TimeoutError:
                pass
        ended = self._task.done() and not self._task.cancelled()
        return self._said.decode(errors="replace").strip(), ended


def _kill_group(process: asyncio.subprocess.Process) -> None:
    """SIGKILL the agent's process group: the agent and all it forked that
    stayed in its session."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


async def _exited(process: asyncio.subprocess.Process, timeout: float | None) -> bool:
    """Whether the agent exited within `timeout` seconds (None: however long
    it takes). Not `process.wait()`: that also waits for the agent's pipes to
    close, which a process it left behind can keep open for good."""
    loop = asyncio.get_running_loop()
    deadline = None if timeout is None else loop.time() + timeout
    while process.returncode is None:
        if deadline is not None and loop.time() >= deadline:
            return False
        await asyncio.sleep(EXIT_POLL)
    return True


async def _ended(process: asyncio.subprocess.Process, stderr: _Drained) -> tuple[str, bool]:
    """Wait for the agent to exit once its input is closed: what it said on
    stderr, for an error, and whether it had to be killed for not exiting —
    a signal of our own, not one it received from elsewhere."""
    if process.stdin is not None and not process.stdin.is_closing():
        process.stdin.close()
    killed = False
    if not await _exited(process, EXIT_GRACE):
        _kill_group(process)
        killed = True
        await _exited(process, None)
    said, closed = await stderr.said()
    if not closed:
        # The agent is gone but something it started still holds its stderr:
        # nothing abk should leave running. One that left the agent's session
        # is out of reach and may hold it for good, so abk lets go of its end.
        _kill_group(process)
        # Process exposes no close of its own; its transport is not in the stubs.
        process._transport.close()  # pyrefly: ignore[missing-attribute]
    return said, killed


RUNTIME = AcpRuntime()

_: AgentRuntime = RUNTIME
