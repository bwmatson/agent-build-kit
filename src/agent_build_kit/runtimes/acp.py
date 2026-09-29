"""An agent speaking the Agent Client Protocol, as an agent runtime.

Spawns the agent `runtimes.acp.command` names and drives one session per run
over stdio, on its own event loop so callers stay synchronous.

The prompt's response carries an end-of-turn reason, so the outcome is read
from that and never from the answer's text: `end_turn` is an answer, a
ceiling or a refusal is a failed result saying which, and `cancelled` is an
interruption, as is an agent killed by a signal. `AgentRequest.allowed_tools`/
`denied_tools` are inert here — the protocol has no per-session tool list
(docs/agent-runtimes.md) — and a named `worktree` is refused, not ignored.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from acp import PROTOCOL_VERSION, RequestError, connect_to_agent, text_block
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

# How long a turn that did not end normally reads in the unit's log: each
# calls for something different of whoever reads it.
STOPPED: dict[str, str] = {
    "max_tokens": "the agent reached its token ceiling before finishing the turn",
    "max_turn_requests": "the agent reached its ceiling on model requests in one turn",
    "refusal": "the agent refused to carry on with the prompt",
}


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
    default_models: ModelsConfig = ModelsConfig()

    def __init__(self) -> None:
        # The models already reported as not on offer, and whether the agent's
        # lack of extra workspace roots has been: once per runtime, not once
        # per unit a tick runs through it.
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
        command = config.runtime_entry(name=NAME).command or list(self.agent_command)
        if not command:
            return AgentResult(ok=False, text="", error=f"runtimes.{NAME}.command is not set")
        return asyncio.run(self._run(command, request))

    async def _run(self, command: list[str], request: AgentRequest) -> AgentResult:
        session = _Session(request.on_event)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=request.cwd,
                limit=LINE_LIMIT,
            )
        except OSError as exc:
            return AgentResult(ok=False, text="", error=f"could not start {command[0]}: {exc}")
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        # Drained as it arrives, so an agent that logs a lot never blocks on
        # a full pipe; kept for the error when the run breaks.
        stderr = asyncio.create_task(process.stderr.read())
        # No file or terminal capability is advertised, so the agent must not
        # call those methods; one that does is answered "method not found".
        conn = connect_to_agent(cast(Client, session), process.stdin, process.stdout)
        try:
            stop_reason = await self._turn(conn, session, request)
        except RequestError as exc:
            return AgentResult(ok=False, text="", error=f"the agent answered an error: {exc}")
        except (ConnectionError, EOFError) as exc:
            said = await _ended(process, stderr)
            if process.returncode is not None and process.returncode < 0:
                raise AgentInterrupted(
                    f"the agent was killed by signal {-process.returncode}"
                ) from exc
            return AgentResult(
                ok=False, text="", error=f"the agent went away: {exc} {said}".strip()
            )
        finally:
            session.said()
            await conn.close()
            await _ended(process, stderr)

        if stop_reason == "cancelled":
            raise AgentInterrupted("the agent's turn was cancelled")
        if stop_reason != "end_turn":
            error = STOPPED.get(stop_reason, f"the turn ended with {stop_reason!r}")
            return AgentResult(ok=False, text=session.answer, error=error, stop_reason=stop_reason)
        return AgentResult(ok=True, text=session.answer, stop_reason=stop_reason)

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
        with the agent's own default, which is not a failure."""
        option = _model_option(options)
        if option is not None and model in _offered(option):
            if option.current_value != model:
                await conn.set_config_option(
                    config_id=option.id, session_id=session_id, value=model
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


async def _ended(process: asyncio.subprocess.Process, stderr: asyncio.Task[bytes]) -> str:
    """Wait for the agent to exit once its input is closed; what it said on
    stderr, for an error."""
    if process.stdin is not None and not process.stdin.is_closing():
        process.stdin.close()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except TimeoutError:
        process.kill()
        await process.wait()
    return (await stderr).decode(errors="replace").strip()


RUNTIME = AcpRuntime()

_: AgentRuntime = RUNTIME
