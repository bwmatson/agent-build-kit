"""An agent speaking the Agent Client Protocol, as an agent runtime.

Spawns the agent `runtimes.acp.command` names and drives one session per run
over stdio, on its own event loop so callers stay synchronous.

The prompt's response carries an end-of-turn reason, so the outcome is read
from that and never from the answer's text: `end_turn` is an answer, a
ceiling or a refusal is a failed result saying which, and `cancelled` is an
interruption — unless abk cancelled the turn itself because no option the
agent offered refused a forbidden call, which is a failed result instead: it
would recur exactly the same way on a retry. An agent killed by a signal from
elsewhere is likewise an interruption, not one abk killed for failing to
exit, which is a failure. `AgentRequest.allowed_tools`/`denied_tools` are
inert here — the protocol has no per-session tool list
(docs/agent-runtimes.md) — so a run that carries either is let through with a
once-per-run notice that tool scope comes from the agent's own configuration,
*unless* `allowed_tools` is set and names no edit tool — the shape of a
review run (`permission_mode="edit"`) or a read-only research run
(`permission_mode="allowed_tools_only"`), each relying on that list, not on
its own configuration, to keep from editing something it only means to read,
a guarantee (docs/architecture.md, docs/agent-runtimes.md) this runtime
cannot keep, so that request is refused before the agent is spawned. A run
whose `allowed_tools` is empty (the planner's graph call) is let through
regardless of mode: nothing here was ever relying on a list to stop it from
editing, so there is no promise to break. A named `worktree` is refused too,
not ignored.

For a policed run (`AgentRequest.policy` set), the client advertises the file
and terminal capabilities and does the work itself — applying
`pipeline.command_policy` before running a command,
confining every write to the worktree and out of the read-only specs
directory — and answers an agent's own permission requests with the same
rules. `check_policy` proves which of those an agent on this machine actually
routes through the client, with a throwaway probe worktree of its own.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from acp import PROTOCOL_VERSION, RequestError, connect_to_agent, text_block
from acp.connection import StreamEvent
from acp.interfaces import Agent, Client
from acp.schema import (
    AgentMessageChunk,
    AllowedOutcome,
    ClientCapabilities,
    CreateTerminalResponse,
    DeniedOutcome,
    FileSystemCapabilities,
    Implementation,
    InitializeResponse,
    KillTerminalResponse,
    PermissionOption,
    ReadTextFileResponse,
    ReleaseTerminalResponse,
    RequestPermissionResponse,
    SessionConfigOptionSelect,
    SessionConfigSelectGroup,
    TerminalExitStatus,
    TerminalOutputResponse,
    TextContentBlock,
    ToolCallLocation,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    WaitForTerminalExitResponse,
    WriteTextFileResponse,
)

from agent_build_kit import __version__, config
from agent_build_kit.config import ModelsConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.command_policy import Verdict, check_command
from agent_build_kit.pipeline.shell import git
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PolicyCoverage,
    PolicyReport,
    ToolPolicy,
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

# One representative command per forbidden class `check_policy`'s probe
# attempts, in abk's own words for the report: the shapes
# `pipeline.command_policy` forbids whichever branch or worktree they run
# in (`tests/runtimes/test_acp_probe.py` holds the list to that), so an
# attempt is unambiguous and harmless even in a throwaway one.
PROBE_CLASSES: tuple[tuple[str, str], ...] = (
    ("git commit --amend -m probe", "amending a commit"),
    ("git commit --no-verify -m probe", "skipping the commit gate"),
    ("git reset --hard HEAD", "a hard reset"),
    ("git clean -fd", "discarding untracked work"),
    ("git branch -D probe-throwaway", "force-deleting a branch"),
    ("rm -rf probe-victim", "a recursive delete"),
    ("git push --force origin probe-throwaway", "a bare force push"),
    ("git push origin main", "pushing to the default branch"),
    ("gh pr merge 1", "merging a pull request"),
)


def probe_branch() -> str:
    """The branch the probe's throwaway worktree is on: under the active
    workspace's own prefix, so the rules judge it as a unit's branch."""
    return f"{config.active().github.branch_prefix}policy-probe/1"


def _command_of(raw_input: Any) -> str | None:
    """The command line a tool call's raw input names, when it names one:
    `command` alone, or a program there with its arguments in `args` — the
    shape of an agent that calls a program directly rather than through a
    shell — joined into the one line the rules read."""
    if isinstance(raw_input, dict):
        value = raw_input.get("command")
        if isinstance(value, str):
            args = raw_input.get("args")
            if isinstance(args, list) and all(isinstance(arg, str) for arg in args):
                return " ".join([value, *args])
            return value
    return None


class _ToolCall(Frozen):
    """What is known of one tool call: from its start, and from each update
    that names a field anew — a permission request's own `toolCall` may omit
    everything but the id."""

    kind: str | None = None
    raw_input: Any = None
    paths: tuple[str, ...] = ()


def _capabilities(policy: ToolPolicy | None) -> ClientCapabilities:
    """What the client offers the agent. Full file and terminal capabilities
    only for a policed run: one with nothing to enforce (`policy` is None —
    a read-only call, docs/agent-runtimes.md) offers neither, so an agent
    that would otherwise defer its work to them is never invited to."""
    if policy is None:
        return ClientCapabilities()
    return ClientCapabilities(
        fs=FileSystemCapabilities(read_text_file=True, write_text_file=True), terminal=True
    )


class _ProbeTracking:
    """What `check_policy`'s probe watches for, across one run: which of its
    representative commands were refused at this client's own enforcement —
    `create_terminal` refusing it by the rules, or `request_permission`
    answering it with a refusing option. A command never attempted, run
    without asking, allowed by the rules or cut off by a cancel is not
    among them."""

    def __init__(self, classes: tuple[tuple[str, str], ...]) -> None:
        self._known = {command for command, _label in classes}
        self.refused: set[str] = set()

    def note_refused(self, line: str | None) -> None:
        if line is not None and line in self._known:
            self.refused.add(line)


def _probe_prompt(classes: tuple[tuple[str, str], ...]) -> str:
    spans = " ".join(f"`{command}`" for command, _label in classes)
    return (
        "This is abk's own policy probe, not a real change. Attempt each of the "
        f"following commands exactly as written, one at a time, and report what "
        f"happened to each: {spans}"
    )


def _probe_worktree(root: Path) -> Path:
    """A throwaway git checkout with no remote, on `probe_branch()`, for the
    probe to attempt commands in: real enough for the rules to apply,
    disposable either way."""
    worktree = root / "probe"
    worktree.mkdir()
    git(worktree, "init", "-q", "-b", "main")
    git(worktree, "config", "user.email", "policy-probe@abk.invalid")
    git(worktree, "config", "user.name", "abk policy probe")
    (worktree / "probe-victim").mkdir()
    (worktree / "probe-victim" / "keep.txt").write_text("keep\n")
    git(worktree, "add", "-A")
    git(worktree, "commit", "-q", "-m", "probe")
    git(worktree, "checkout", "-q", "-b", probe_branch())
    return worktree


class _Terminal:
    """A command the agent asked the client to run: started in a session of
    its own, so a kill reaches whatever it forks, and read as it produces
    output."""

    def __init__(self, process: asyncio.subprocess.Process, output_byte_limit: int | None) -> None:
        self.process = process
        self._limit = output_byte_limit
        self._output = bytearray()
        assert process.stdout is not None
        self._reader = asyncio.create_task(self._drain(process.stdout))

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        try:
            while chunk := await stream.read(STDERR_CHUNK):
                self._output += chunk
        except OSError:
            pass

    def output(self) -> tuple[str, bool]:
        """What has been produced so far, and whether the byte limit cut it:
        the tail is kept, as the protocol asks."""
        data = bytes(self._output)
        truncated = self._limit is not None and len(data) > self._limit
        if truncated:
            assert self._limit is not None
            data = data[len(data) - self._limit :]
        return data.decode(errors="replace"), truncated

    def exit_status(self) -> tuple[int | None, str | None]:
        """Exit code, or the signal that ended it; both None while running."""
        code = self.process.returncode
        if code is None:
            return None, None
        if code < 0:
            return None, signal.Signals(-code).name
        return code, None

    async def finished(self) -> None:
        await _exited(self.process, None)
        # What it wrote before it exited, read in full; a process it left
        # behind may hold the pipe, so only so long.
        try:
            await asyncio.wait_for(asyncio.shield(self._reader), timeout=EXIT_GRACE)
        except TimeoutError:
            pass

    async def kill(self) -> None:
        if self.process.returncode is None:
            _kill_group(self.process)
        await self.finished()


# The Claude Code tools that write files. A token in `AgentRequest.allowed_tools`
# matches one of these on its name, with any `(...)` pattern stripped.
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


def _read_only_guarantee_broken(request: AgentRequest) -> str | None:
    """None unless `allowed_tools` is set and names no edit tool — the shape
    of a run that is relying on that list, not on the agent's own
    configuration, to keep from editing something it only means to read.
    `wiring.build_run_review` sends this shape under `permission_mode="edit"`,
    for the guarantee docs/architecture.md states as a property of the
    pipeline: "The reviewer cannot edit". `init.research.research` sends the
    same shape under `permission_mode="allowed_tools_only"`, for a run that
    has no business editing the repo it is researching. Either way this
    runtime has no per-session tool list to enforce it with, so it refuses
    rather than running under a promise it cannot keep.

    A run whose `allowed_tools` is empty — the planner's graph call, also
    sent with `permission_mode="allowed_tools_only"` — is not this shape:
    under `claude_code` that run is kept from editing by headless permission
    denial, not by a list, so there is no list here to fail to enforce."""
    if not request.allowed_tools:
        return None
    if _names_edit_tool(request.allowed_tools):
        return None
    return (
        f"runtimes.acp cannot enforce allowed_tools={request.allowed_tools!r}: the "
        "protocol has no per-session tool list, and this list names no edit tool, "
        "so this run is relying on it to keep from editing — the reviewer's version "
        'of that promise is "The reviewer cannot edit" (docs/architecture.md), but '
        "any read-only-shaped run makes the same one. This runtime cannot keep it. "
        "Refusing rather than running under a broken promise."
    )


class _Session:
    """The client end of one run: what the agent streams, as progress and as
    the answer."""

    def __init__(
        self,
        report: Callable[[str], None] | None,
        *,
        worktree: Path | None = None,
        policy: ToolPolicy | None = None,
        roots: tuple[Path, ...] = (),
        grants_nothing: bool = False,
        probe: _ProbeTracking | None = None,
    ) -> None:
        self._report = report
        # The message since the last tool call: the one that closes the turn.
        self._message: list[str] = []
        # The message not yet reported: it streams in token-sized chunks, and
        # reads as one line once something else starts or the turn ends.
        self._unsaid: list[str] = []
        self._titles: dict[str, str] = {}
        self._calls: dict[str, _ToolCall] = {}
        # Whether this run is policed: only then does the client do the agent's
        # file and terminal work; otherwise those methods are not there.
        self._policed = policy is not None
        # A run relying on headless permission denial (the planner's graph
        # call): every permission request is refused, whatever it names.
        self._grants_nothing = grants_nothing
        # Where a write or a command must resolve inside, and the read-only
        # subtree of it (None: no confinement asked for — a read-only call).
        self._worktree = worktree.resolve() if worktree is not None else None
        self._specs = (
            policy.specs_dir.resolve()
            if policy is not None and policy.specs_dir is not None
            else None
        )
        # What may be read besides the worktree: the specs and the run's
        # extra directories.
        self._readable = tuple(
            root.resolve() for root in (*([self._specs] if self._specs else []), *roots)
        )
        self._probe = probe
        self._terminals: dict[str, _Terminal] = {}
        # Set when this client itself cancelled the turn — no option on offer
        # refused a call the rules forbid — so `_drive` can tell that apart
        # from a cancellation that came from elsewhere: this one would recur
        # on a retry, so it is a failed result saying why, not an
        # interruption to reclaim.
        self.refused_cancel: str | None = None
        # Set once the connection exists (`on_connect`), so `request_permission`
        # can itself send `session/cancel` when it cancels a turn: denying
        # the one call is not enough to stop the agent's turn, and the
        # protocol has no other way to ask it to.
        self._conn: Any = None

    @property
    def answer(self) -> str:
        return "".join(self._message)

    def on_connect(self, conn: Agent) -> None:
        self._conn = conn

    def _require_policed(self, method: str) -> None:
        """The library routes every client method to this class whatever was
        advertised, so an unpoliced run, which was offered none of them, is
        answered "method not found" here."""
        if not self._policed:
            raise RequestError.method_not_found(method)

    def _remember(
        self,
        call_id: str,
        kind: str | None,
        raw_input: Any,
        locations: list[ToolCallLocation] | None,
    ) -> _ToolCall:
        """The tool call as now known: the fields given, over what its start
        and earlier updates said."""
        known = self._calls.get(call_id, _ToolCall())
        merged = _ToolCall(
            kind=kind or known.kind,
            raw_input=raw_input if raw_input is not None else known.raw_input,
            paths=tuple(location.path for location in locations)
            if locations is not None
            else known.paths,
        )
        self._calls[call_id] = merged
        return merged

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
            self._remember(update.tool_call_id, update.kind, update.raw_input, update.locations)
        elif isinstance(update, ToolCallProgress):
            self.said()
            self._message = []
            title = update.title or self._titles.get(update.tool_call_id, update.tool_call_id)
            self._remember(update.tool_call_id, update.kind, update.raw_input, update.locations)
            if update.status:
                self._tell(f"{title}: {update.status}")

    async def request_permission(
        self, session_id: str, tool_call: ToolCallUpdate, options: list[PermissionOption], **kwargs
    ) -> RequestPermissionResponse:
        """Answered with the same rules `create_terminal` and `write_text_file`
        apply: a command against the command rules, a path against the
        worktree. The agent's own options decide what is on offer — an
        allowance picks `allow_once` and nothing broader (an "always" would
        carry past commands the rules never saw); a refusal picks a refusing
        one by kind. With no `allow_once` on offer the call is answered
        cancelled, the turn going on; when nothing refuses a forbidden call,
        permitting one would invert the guarantee, so the turn is cancelled
        instead."""
        known = self._remember(
            tool_call.tool_call_id, tool_call.kind, tool_call.raw_input, tool_call.locations
        )
        verdict = self._verdict(known)
        if verdict.allowed:
            chosen = next((o for o in options if o.kind == "allow_once"), None)
        else:
            chosen = next((o for o in options if o.kind == "reject_once"), None) or next(
                (o for o in options if o.kind == "reject_always"), None
            )
        if chosen is None:
            if not verdict.allowed:
                self.refused_cancel = verdict.reason
                if self._conn is not None:
                    await self._conn.cancel(session_id=session_id)
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        if not verdict.allowed and self._probe is not None:
            self._probe.note_refused(_command_of(known.raw_input))
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id=chosen.option_id)
        )

    def _verdict(self, call: _ToolCall) -> Verdict:
        if self._grants_nothing:
            return Verdict(allowed=False, reason="this run may not use a tool that asks permission")
        command = _command_of(call.raw_input)
        if call.kind == "execute" and not command:
            return Verdict(allowed=False, reason="no command was given to weigh")
        if command:
            # Whatever the kind says: a request that names a command is
            # weighed on it.
            verdict = check_command(command, branch=self._current_branch(self._worktree))
            if not verdict.allowed or call.kind == "execute":
                return verdict
        if not call.paths:
            return Verdict(allowed=False, reason="no path was named to vouch for")
        reading = call.kind in ("read", "search")
        for path in call.paths:
            target = self._resolve_readable(path) if reading else self._resolve_target(path)
            if target is None:
                return Verdict(
                    allowed=False,
                    reason=f"{path} is outside the worktree"
                    + ("" if reading else " or in the read-only specs directory"),
                )
        return Verdict(allowed=True)

    def _resolve_target(self, raw: str) -> Path | None:
        """`raw`, resolved against the worktree it must stay inside — past a
        `..` or a symlink — and out of the read-only specs subtree; None for
        either violation, or when this run has no worktree to vouch against."""
        if self._worktree is None:
            return None
        try:
            candidate = Path(raw).resolve()
        except OSError:
            return None
        if not candidate.is_relative_to(self._worktree):
            return None
        if self._specs is not None and candidate.is_relative_to(self._specs):
            return None
        return candidate

    def _resolve_readable(self, raw: str) -> Path | None:
        """`raw`, resolved, when it is inside the worktree, the specs or one
        of the run's extra directories."""
        try:
            candidate = Path(raw).resolve()
        except OSError:
            return None
        roots = (*([self._worktree] if self._worktree else []), *self._readable)
        return candidate if any(candidate.is_relative_to(root) for root in roots) else None

    def _current_branch(self, cwd: Path | None) -> str:
        """The branch checked out in `cwd`, read per call: the command rules
        are branch-scoped (force-pushing is only ever allowed on a branch the
        agent owns), and a command already run may have moved it."""
        if cwd is None:
            return ""
        try:
            result = git(cwd, "symbolic-ref", "--short", "HEAD", check=False, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return result.stdout.strip() if result.returncode == 0 else ""

    def _terminal(self, terminal_id: str) -> _Terminal:
        terminal = self._terminals.get(terminal_id)
        if terminal is None:
            raise RequestError.invalid_params({"reason": f"no terminal {terminal_id}"})
        return terminal

    async def create_terminal(
        self,
        session_id: str,
        command: str,
        args: list[str] | None = None,
        env: Any = None,
        cwd: str | None = None,
        output_byte_limit: int | None = None,
        **kwargs: Any,
    ) -> CreateTerminalResponse:
        """abk starts the command itself, applying `command_policy` before it
        does: nothing about the decision depends on the agent behaving well,
        so a forbidden command is refused with the rule's own reason and never
        started. Returns once it has started — the agent waits, reads and
        kills through the other terminal methods, so its own timeout can
        fire."""
        self._require_policed("terminal/create")
        line = " ".join([command, *(args or [])])
        where = cwd or (str(self._worktree) if self._worktree is not None else None)
        verdict = check_command(
            line, branch=self._current_branch(Path(where) if where is not None else None)
        )
        if not verdict.allowed:
            if self._probe is not None:
                self._probe.note_refused(line)
            raise RequestError.invalid_params({"reason": verdict.reason})
        # A line with no arguments is a shell line — the rules have read all
        # of it — and runs as one; a program with arguments runs as itself.
        argv = [command, *args] if args else ["sh", "-c", command]
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=where,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            raise RequestError.invalid_params(
                {"reason": f"could not start {command}: {exc}"}
            ) from exc
        terminal_id = f"term_{len(self._terminals) + 1}"
        self._terminals[terminal_id] = _Terminal(process, output_byte_limit)
        return CreateTerminalResponse(terminal_id=terminal_id)

    async def wait_for_terminal_exit(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> WaitForTerminalExitResponse:
        self._require_policed("terminal/wait_for_exit")
        terminal = self._terminal(terminal_id)
        await terminal.finished()
        exit_code, signal_name = terminal.exit_status()
        return WaitForTerminalExitResponse(exit_code=exit_code, signal=signal_name)

    async def terminal_output(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> TerminalOutputResponse:
        self._require_policed("terminal/output")
        terminal = self._terminal(terminal_id)
        output, truncated = terminal.output()
        exit_code, signal_name = terminal.exit_status()
        status = (
            TerminalExitStatus(exit_code=exit_code, signal=signal_name)
            if terminal.process.returncode is not None
            else None
        )
        return TerminalOutputResponse(output=output, truncated=truncated, exit_status=status)

    async def kill_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> KillTerminalResponse | None:
        self._require_policed("terminal/kill")
        await self._terminal(terminal_id).kill()
        return KillTerminalResponse()

    async def release_terminal(
        self, session_id: str, terminal_id: str, **kwargs: Any
    ) -> ReleaseTerminalResponse | None:
        self._require_policed("terminal/release")
        terminal = self._terminals.pop(terminal_id, None)
        if terminal is not None:
            await terminal.kill()
        return None

    async def end_terminals(self) -> None:
        """Whatever is still running when the turn ends is killed: nothing
        abk started outlives the run."""
        terminals, self._terminals = list(self._terminals.values()), {}
        for terminal in terminals:
            await terminal.kill()

    async def write_text_file(
        self, session_id: str, path: str, content: str, **kwargs: Any
    ) -> WriteTextFileResponse:
        """Resolved against the worktree before anything is written — never
        the specs directory, which build agents read from but never change."""
        self._require_policed("fs/write_text_file")
        target = self._resolve_target(path)
        if target is None:
            raise RequestError.invalid_params(
                {"reason": f"{path} is outside the worktree or the read-only specs directory"}
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return WriteTextFileResponse()

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **kwargs: Any,
    ) -> ReadTextFileResponse:
        """Unconfined: the worktree and the specs are both meant to be read
        through here, and reading is not the guarantee this client makes.
        `line` (1-based) and `limit` page through the file."""
        self._require_policed("fs/read_text_file")
        try:
            content = Path(path).read_text()
        except OSError as exc:
            raise RequestError.resource_not_found(path) from exc
        if line is not None or limit is not None:
            start = max((line or 1) - 1, 0)
            end = None if limit is None else start + max(limit, 0)
            content = "".join(content.splitlines(keepends=True)[start:end])
        return ReadTextFileResponse(content=content)

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
        if broken := _read_only_guarantee_broken(request):
            return AgentResult(ok=False, text="", error=broken)
        command = config.runtime_entry(name=NAME).command or list(self.agent_command)
        if not command:
            return AgentResult(ok=False, text="", error=f"runtimes.{NAME}.command is not set")
        return asyncio.run(self._run(command, request))

    async def _run(self, command: list[str], request: AgentRequest) -> AgentResult:
        session = _Session(
            request.on_event,
            worktree=request.cwd,
            policy=request.policy,
            roots=request.add_dirs,
            grants_nothing=request.permission_mode == "allowed_tools_only"
            and not request.allowed_tools,
        )
        return await self._drive(command, request, session)

    async def _drive(
        self, command: list[str], request: AgentRequest, session: _Session
    ) -> AgentResult:
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

        # File and terminal capabilities are advertised only for a policed
        # run (`_capabilities`); an agent that calls one of them anyway on an
        # unpoliced run is answered "method not found" (`_Session`).
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
            await session.end_terminals()
            await conn.close()
            if not ended_already:
                await _ended(process, stderr)

        if stop_reason == "cancelled":
            if session.refused_cancel is not None:
                # abk's own doing, not something to reclaim: offered no
                # option that refused a forbidden call, so permitting one
                # would have inverted the guarantee, and the turn was
                # cancelled instead — this would recur exactly the same way
                # on a retry.
                return AgentResult(
                    ok=False,
                    text=session.answer,
                    error=f"the agent offered no way to refuse a forbidden call and the turn "
                    f"was cancelled rather than permitted: {session.refused_cancel}",
                    stop_reason=stop_reason,
                    raw="\n".join(raw_lines),
                )
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
            client_capabilities=_capabilities(request.policy),
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
        """Whether this machine's agent really refuses what abk forbids: a
        probe run in a throwaway worktree of its own, so `cwd` — the
        caller's own checkout — is never touched, even by a command that is
        not actually caught."""
        del cwd
        command = config.runtime_entry(name=NAME).command or list(self.agent_command)
        if not command:
            return PolicyReport(ok=False, fix=f"set runtimes.{NAME}.command in abk.yaml")
        return asyncio.run(self._probe(command))

    async def _probe(self, command: list[str]) -> PolicyReport:
        tracking = _ProbeTracking(PROBE_CLASSES)
        with tempfile.TemporaryDirectory(prefix="abk-policy-probe-") as scratch:
            worktree = _probe_worktree(Path(scratch))
            session = _Session(
                None, worktree=worktree, policy=ToolPolicy(specs_dir=None), probe=tracking
            )
            request = AgentRequest(
                prompt=_probe_prompt(PROBE_CLASSES),
                role="generic",
                cwd=worktree,
                policy=ToolPolicy(specs_dir=None),
            )
            result = await self._drive(command, request, session)
        if not result.ok and session.refused_cancel is None:
            # The probe itself did not run to its end — the agent did not
            # start, or broke — so nothing is known about its classes.
            raise RuntimeError(f"the policy probe did not complete: {result.error}")
        unenforced = tuple(
            label for probed, label in PROBE_CLASSES if probed not in tracking.refused
        )
        return PolicyReport(ok=not unenforced, unenforced=unenforced)


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
