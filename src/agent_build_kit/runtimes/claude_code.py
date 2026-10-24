"""Claude Code as an agent runtime: `claude -p`, run as a subprocess.

The one place that builds a `claude` argv and reads what the process hands
back. A request's policy brings the PreToolUse hook (`hooks/policy`) and the
pipeline's deny list with it; its progress callback turns the run into a
streamed one (`pipeline/claude_stream`); and a failed exit is sorted into a
spent usage window, an interruption, or a failed result as
`pipeline/usage_guard` has always told them apart.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from agent_build_kit import claude_account, config
from agent_build_kit.config import ConfigError, ModelsConfig
from agent_build_kit.hooks.policy import hook_settings
from agent_build_kit.pipeline.call_record import call_recorder
from agent_build_kit.pipeline.claude_stream import (
    STREAM_FLAGS,
    ResultEvent,
    describe,
    final_text,
    own_words,
    records,
    request_fills,
    result_event,
    stream_run,
)
from agent_build_kit.pipeline.usage_guard import (
    USAGE_URL,
    UsageReading,
    read_cached_usage,
    read_live_usage,
)
from agent_build_kit.pipeline.vocabulary import OverheadNode
from agent_build_kit.runtimes.base import (
    AccountLine,
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    Candidate,
    Model,
    ModelList,
    ModelSource,
    NetworkUnavailable,
    PermissionMode,
    PolicyCoverage,
    PolicyReport,
    PromptTransport,
    Question,
    QuestionKind,
    Run,
    ServiceUnavailable,
    SessionUnavailable,
    UsageStatus,
    Which,
    check_prompt_size,
    child_environment,
    full_environment,
    validate_argv,
)
from agent_build_kit.runtimes.claude_output import AgentFailure, agent_failure
from agent_build_kit.runtimes.network import network_failure
from agent_build_kit.runtimes.traced import traced
from agent_build_kit.sandboxes import Coverage, SandboxPolicy
from agent_build_kit.sandboxes.confinement import (
    SandboxRefused,
    confinement,
    scrubbed_environment,
)
from agent_build_kit.settings import named_value
from agent_build_kit.usage import Context, ContextBasis, context_of

if TYPE_CHECKING:
    from agent_build_kit.installation import Installation

# (argv, *, cwd, on_event, input) -> the finished process: `claude_stream.stream_run`'s
# shape. `input` is the prompt, written to the process's standard input. `on_event` is called
# with each JSON event as it is printed, and is None for a run that is not streamed.
Execute = Callable[..., subprocess.CompletedProcess[str]]

# A usage reading, or None when there is none: `usage_guard`'s readers.
ReadUsage = Callable[[], UsageReading | None]

logger = logging.getLogger(__name__)

# The host Claude Code's connectors need besides the API host.
MCP_PROXY_HOST = "mcp-proxy.anthropic.com"

# Passed beside the hook on every policed run, on top of every registered
# forge's own merge commands. Redundant by design: two independent things have
# to fail before the agent can merge its own PR.
DISALLOWED = "Bash(git push --force *) Bash(git reset --hard*) Bash(rm -rf*) Bash(git branch -D*)"


def disallowed() -> str:
    """The deny flags for a policed run: every forge's, then these.

    Resolved per call rather than at import, so a forge registered later is
    covered and importing this module never pulls the registry in.
    """
    from agent_build_kit import forges

    merges = " ".join(f"Bash({prefix}*)" for prefix in forges.denied_prefixes())
    return f"{merges} {DISALLOWED}".strip()


# abk's permission modes in Claude Code's words; None passes no mode, so the
# run has what its tool list allows and nothing more.
PERMISSION_MODES: dict[PermissionMode, str | None] = {
    "edit": "acceptEdits",
    "allowed_tools_only": None,
}


def spawn(
    argv: list[str],
    *,
    cwd: Path | None = None,
    on_event: Callable[[dict], None] | None = None,
    env: dict[str, str] | None = None,
    environment: dict[str, str] | None = None,
    input: str = "",
    sandbox: SandboxPolicy | None = None,
) -> subprocess.CompletedProcess[str]:
    """The real `claude` process: streamed when there is someone to tell. `env`
    is added to `environment` when given, else to this process's own. `input` is
    the prompt, on its standard input. `sandbox` starts it through the backend's command,
    behind the allowlist proxy and without abk's own credentials."""
    if sandbox is None:
        return _spawn(argv, cwd, on_event, child_environment(environment, env or {}), input)
    merged = scrubbed_environment(full_environment(environment, env or {}))
    try:
        # The proxy runs only for a step that is confined.
        with confinement(sandbox) as confined:
            wrapped = confined.wrap(argv)
            return _spawn(wrapped, cwd, on_event, {**merged, **confined.environment}, input)
    except SandboxRefused as refused:
        # The sandbox is not what the repo requires: the step is not started.
        return subprocess.CompletedProcess(argv, 1, "", str(refused))


def _spawn(
    argv: list[str],
    cwd: Path | None,
    on_event: Callable[[dict], None] | None,
    merged: dict[str, str] | None,
    input: str,
) -> subprocess.CompletedProcess[str]:
    if on_event is not None:
        return stream_run(argv, cwd=cwd, on_event=on_event, env=merged, input=input)
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        check=False,
        env=merged,
        input=input,
    )


NAME = "claude_code"

# The host the CLI calls, which the probe looks at when a run ends on a connection failure.
API_HOST = urlparse(USAGE_URL).hostname or ""

# The variable the CLI reads for the address it calls, in place of the default host.
BASE_URL_VARIABLE = "ANTHROPIC_BASE_URL"

# The port the default host is called on.
API_PORT = 443


def _api_endpoint(request: AgentRequest) -> tuple[str, int]:
    """The host and port this run called: the base-URL override it was started with, from
    the request, else the environment the CLI inherits; the default host otherwise."""
    if BASE_URL_VARIABLE in request.env:
        override = request.env[BASE_URL_VARIABLE]
    elif request.environment is not None:
        override = request.environment.get(BASE_URL_VARIABLE, "")
    else:
        # The process environment alone: it is what the CLI inherits, and a `.env` value is
        # never exported to it.
        override = named_value(BASE_URL_VARIABLE, None)
    parsed = urlparse(override)
    if not override or not parsed.hostname:
        return API_HOST, API_PORT
    try:
        port = parsed.port
    except ValueError:
        port = None
    return parsed.hostname, port or (80 if parsed.scheme == "http" else API_PORT)


# What starts the agent when `runtimes.claude_code.command` is not set.
AGENT_COMMAND: tuple[str, ...] = ("claude",)


# The model aliases Claude Code documents, since it cannot be asked.
MODEL_ALIASES: tuple[str, ...] = ("opus", "sonnet", "haiku", "fable")


def command() -> list[str]:
    """The argv prefix every `claude` call starts with: the installation's
    `runtimes.claude_code.command` when it sets one, else `claude` on PATH —
    the same binary `abk doctor` checks for."""
    return list(config.runtime_entry(name=NAME).command or AGENT_COMMAND)


def _account_run_kwargs(account: claude_account.Account | None = None) -> dict[str, Any]:
    """How a `claude` that is not a build is started in the account: its environment,
    or nothing for the default account."""
    entry = claude_account.environment_entry(account)
    return {"env": child_environment(None, entry)} if entry else {}


def refresh_login(run: Callable[..., object] = subprocess.run) -> None:
    """Have Claude Code refresh its OAuth token, with the smallest call it
    takes — see `usage_guard.refresh_login` for why the usage read needs it."""
    started = time.monotonic()
    argv = [*command(), "-p", "Reply with OK and nothing else.", "--model", "haiku"]
    done = run(
        argv, capture_output=True, text=True, check=False, timeout=120, **_account_run_kwargs()
    )
    # The output is discarded, so the row has no figures: a duration and the exit status.
    call_recorder(OverheadNode.LOGIN_REFRESH, say=print)(
        AgentResult(
            ok=getattr(done, "returncode", 0) == 0,
            text="",
            duration_ms=round((time.monotonic() - started) * 1000),
        ),
        role="generic",
        model="haiku",
        runtime=NAME,
    )


def integration_branches() -> tuple[str, ...]:
    """The branches this workspace's repos integrate on, beyond `main` and
    `master`, which a direct push is always refused.

    The hook is its own process and loads no workspace, so what it should
    protect has to be handed to it. Only the extras are listed: a workspace on
    `main` adds nothing, and its hook settings stay as they always were.
    """
    return tuple(
        sorted(
            {repo.default_branch for repo in config.active().repos.values()} - {"main", "master"}
        )
    )


# Claude Code adds a `Co-Authored-By` trailer to the commits it makes and a
# "Generated with" line to the pull requests, unless the setting is empty. The
# pipeline's commits are its own, and a repo may forbid the trailer outright
# (a squash merge copies it into history, and removing it later means
# rewriting commits the agent cannot rewrite), so every run turns it off
# instead of each repo having to ask. `includeCoAuthoredBy` is the older
# spelling of the same switch, kept for a CLI that predates `attribution`.
NO_ATTRIBUTION: dict = {"attribution": {"commit": "", "pr": ""}, "includeCoAuthoredBy": False}


def build_argv(request: AgentRequest) -> list[str]:
    argv = [*command(), "-p"]
    if request.worktree:
        argv += ["--worktree", request.worktree]
    for directory in request.add_dirs:
        argv += ["--add-dir", str(directory)]
    denied = request.denied_tools
    sandboxed = request.policy is not None and request.policy.sandbox is not None
    planning = {
        "planning_repo": request.planning_repo,
        "planning_state_dir": request.planning_state_dir,
        "planning_change_dir": request.planning_change_dir,
        "protected_branches": integration_branches(),
    }
    if request.policy is not None:
        settings = hook_settings(
            request.policy.specs_dir,
            branch_prefix=request.policy.branch_prefix,
            planning_paths=request.policy.planning_paths,
            fenced_files=request.policy.fenced_files,
            no_push=True,
            no_commit=request.policy.no_commit,
            refusals_only=not request.policy.scoped,
            confined=request.policy.confined,
            **planning,
        )
        if request.policy.scoped:
            denied = f"{disallowed()} {denied}".strip()
    elif request.planning_repo is not None:
        settings = hook_settings(None, branch_prefix=config.active().git.branch_prefix, **planning)
    else:
        settings = {}
    # The kit's sandbox is the one enforcement point: Claude Code's own is switched off.
    own = {"sandbox": {"enabled": False}} if sandboxed else {}
    argv += ["--settings", json.dumps({**settings, **NO_ATTRIBUTION, **own})]
    if request.allowed_tools:
        argv += ["--allowedTools", request.allowed_tools]
    if denied:
        argv += ["--disallowedTools", denied]
    if mode := PERMISSION_MODES[request.permission_mode]:
        argv += ["--permission-mode", mode]
    if request.model:
        argv += ["--model", request.model]
    if request.resume_session:
        argv += ["--resume", request.resume_session]
        if request.fork_session:
            argv.append("--fork-session")
    if (
        request.on_event
        or request.on_transcript
        or request.on_record
        or request.on_session
        or request.on_result
    ):
        argv += STREAM_FLAGS
    elif request.keep_record:
        argv += ["--output-format", "json"]
    else:
        # The CLI's default, written out as the call sites always have.
        argv += ["--output-format", "text"]
    return argv


class ClaudeCodeRuntime:
    name: str = NAME
    implemented: bool = True
    # The hook sees every tool call before it runs.
    policy_coverage: PolicyCoverage = "all_calls"
    # `spawn` starts the whole process under the backend's command.
    sandbox_coverage: Coverage = Coverage.PROCESS
    sandbox_note: str = ""
    supports_usage_tracking: bool = True
    supports_streaming: bool = True
    # `--resume <id>`, with the id its init event reports.
    supports_session_resume: bool = True
    # `request.env` is added to `claude`'s environment, but the gateway's key is
    # still not offered to it: that is a decision about the gateway, not the run.
    passes_env: bool = False
    # `claude -p` with no prompt argument reads it from standard input.
    prompt_transport: PromptTransport = PromptTransport.STDIN
    # `claude` on PATH is all it needs.
    requires: tuple[str, ...] = ()
    agent_command: tuple[str, ...] = AGENT_COMMAND
    # `ModelsConfig`'s own defaults are Claude Code's names (why each is what
    # it is sits there), so they are declared once.
    default_models: ModelsConfig = ModelsConfig()

    def __init__(
        self,
        *,
        execute: Execute | None = None,
        read_live: ReadUsage | None = None,
        read_cached: ReadUsage | None = None,
    ) -> None:
        self._execute = execute
        self._read_live = read_live
        self._read_cached = read_cached

    def sandbox_paths(self, account: claude_account.Account | None = None) -> dict[str, list[str]]:
        """What the `claude` process itself needs: the folder and state file of the account it
        runs as, the temp folder, the device files and the model hosts."""
        mine = [str(claude_account.home(account)), str(claude_account.state_file(account))]
        return {
            "write": [*mine, "/tmp", "/dev"],
            "read": mine,
            "hosts": [API_HOST, MCP_PROXY_HOST],
        }

    def run(self, request: AgentRequest) -> AgentResult:
        return traced(self.name, request, lambda: self._run(request))

    def _run(self, request: AgentRequest) -> AgentResult:
        check_prompt_size(request, self.prompt_transport)
        execute = self._execute or spawn
        # Only when there is something to add: an injected `execute` written
        # before the environment was passed does not take the argument.
        env = {**request.env, **claude_account.environment_entry(request.account)}
        extra: dict[str, Any] = {"env": env} if env else {}
        if request.environment is not None:
            extra["environment"] = request.environment
        if request.policy is not None and request.policy.sandbox is not None:
            # The model endpoint this run calls (a gateway, when the request names one) is
            # reached through the proxy, so it is allowed.
            host, _ = _api_endpoint(request)
            hosts = tuple(dict.fromkeys([*request.policy.sandbox.hosts, host]))
            extra["sandbox"] = request.policy.sandbox.model_copy(update={"hosts": hosts})
        result = execute(
            build_argv(request),
            cwd=request.cwd,
            on_event=_progress(request),
            input=request.prompt,
            **extra,
        )
        outcome = self._finish(request, result)
        if request.on_result is not None:
            request.on_result(outcome)
        return outcome

    def _finish(
        self, request: AgentRequest, result: subprocess.CompletedProcess[str]
    ) -> AgentResult:

        if result.returncode < 0:
            raise AgentInterrupted(f"claude was killed by signal {-result.returncode}")
        ended = result_event(result.stdout)
        # An error-subtype result has no `result` text, and `final_text` would
        # then hand back the whole transcript; that belongs in `raw` alone.
        text = "" if ended is not None and ended.result is None else final_text(result.stdout)
        stop_reason = ended.subtype if ended is not None else ""
        # Only what the CLI said about the ending, never the transcript:
        # see `claude_stream.own_words`.
        said = f"{own_words(result.stdout)}\n{result.stderr}".strip()
        # A clean exit with no closing event (a plain-text call) is a success.
        failure = (
            agent_failure(ended, said)
            if ended is not None or result.returncode
            else AgentFailure(kind="none")
        )
        if result.returncode and failure.kind == "none":
            # A non-zero exit contradicts a success event: read the words.
            failure = agent_failure(None, said)
        if result.returncode or failure.kind != "none":
            if request.resume_session and failure.kind == "session_unavailable":
                raise SessionUnavailable(said)
            failed = AgentResult(
                ok=False,
                text=text,
                raw=result.stdout,
                error=f"claude exited {result.returncode}: {said}",
                stop_reason=stop_reason,
                turns=ended.num_turns if ended is not None else None,
                **_spent(ended),
                context=_context(result.stdout, ended, request.model),
            )
            strength = (
                network_failure(said)
                if failure.kind not in ("rate_limited", "service_unavailable")
                else None
            )
            if failure.kind in ("rate_limited", "service_unavailable") or strength:
                # Raised, so `_run` never sees it: the spend of a call cut off
                # is told here.
                if request.on_result is not None:
                    request.on_result(failed.model_copy(update={"error": said}))
                if failure.kind == "service_unavailable" and failure.status is not None:
                    raise ServiceUnavailable(said, status=failure.status)
                if strength:
                    host, port = _api_endpoint(request)
                    raise NetworkUnavailable(said, strength=strength, host=host, port=port)
                raise AgentRateLimited(
                    said or "claude reported a usage limit", resets_at=failure.resets_at
                )
            return failed
        return AgentResult(
            ok=True,
            text=text,
            raw=result.stdout,
            stop_reason=stop_reason,
            turns=ended.num_turns if ended is not None else None,
            context=_context(result.stdout, ended, request.model),
            **_spent(ended),
        )

    def get_usage_status(self) -> UsageStatus | None:
        read_live = self._read_live or (
            lambda: read_live_usage(refresh=refresh_login, caller="status")
        )
        reading = read_live() or (self._read_cached or read_cached_usage)()
        if reading is None:
            return None
        return UsageStatus(
            session_pct=reading.session_pct,
            weekly_pct=reading.weekly_pct,
            resets_at=reading.resets_at,
            observed_at=reading.observed_at,
            source=reading.source,
        )

    def detect(self, which: Which, run: Run) -> list[Candidate]:
        del run
        program = AGENT_COMMAND[0]
        found = which(program) is not None
        return [
            Candidate(
                runtime=NAME,
                command=AGENT_COMMAND,
                label="Claude Code",
                usable=found,
                reasons=() if found else (f"{program} is not on the path",),
            )
        ]

    def setup_questions(self) -> list[Question]:
        return [
            Question(
                key="command",
                prompt="The claude executable (a path, or a wrapper with its arguments)",
                default=" ".join(AGENT_COMMAND),
                kind=QuestionKind.ARGV,
                validator=validate_argv,
                writes_to=f"runtimes.{NAME}.command",
            )
        ]

    def list_models(self, command: Sequence[str] | None = None) -> ModelList:
        del command  # nothing is asked: the list is documented
        return ModelList(
            models=tuple(Model(name=alias) for alias in MODEL_ALIASES),
            source=ModelSource.DOCUMENTED,
            note="Claude Code has no command that lists models: these are its documented "
            "aliases, not queried",
        )

    def account_report(self, run: Run, env_file: Path | None) -> list[AccountLine]:
        """The account directory, where the setting came from, and whether it is logged in,
        asked of `auth status` with the account's variable; only its exit status and
        `loggedIn` are read, so no token or address of the answer is kept."""
        where = claude_account.source(env_file).value
        try:
            account = claude_account.home()
            entry = claude_account.environment_entry()
        except ConfigError as error:
            return [
                AccountLine(
                    status="FAIL", detail=str(error), fix=f"write an absolute path for {where}"
                )
            ]
        login = _login_command(entry)
        lines: list[AccountLine] = []
        if entry and named_value("CLAUDE_CODE_OAUTH_TOKEN", env_file):
            lines.append(
                AccountLine(
                    status="warn",
                    detail="CLAUDE_CODE_OAUTH_TOKEN is set beside an account: the token names its "
                    "own account, which the usage guard reads whatever the directory",
                    fix="unset CLAUDE_CODE_OAUTH_TOKEN so the guard reads the account's directory",
                )
            )
        if entry:
            return [*_directory_lines(run, None, account, f"{account} ({where})", login), *lines]
        name = f"the default account {account} is in use"
        return [*_directory_lines(run, None, None, name, login), *lines]

    def check_policy(self, cwd: Path) -> PolicyReport:
        """Answered locally: every policed run registers the hook and passes
        the same denies as flags, so no class goes unenforced."""
        return PolicyReport(ok=True)


def _login_command(entry: dict[str, str]) -> str:
    """The command a person runs to sign in to the account whose environment is `entry`."""
    return " ".join(
        [*(f"{name}={shlex.quote(value)}" for name, value in entry.items())]
        + [*map(shlex.quote, command()), "auth", "login"]
    )


def _directory_lines(
    run: Run,
    account: claude_account.Account | None,
    directory: Path | None,
    name: str,
    login: str,
) -> list[AccountLine]:
    """What one account says of itself: its `directory` is missing (an error), or it is not
    logged in (an error), or it is. A `directory` of None is the default account, whose
    existence is not asked."""
    if directory is not None:
        if not directory.is_dir():
            return [AccountLine(status="FAIL", detail=f"{name} does not exist", fix=login)]
        name = f"{name} exists"
    if _logged_in(run, account):
        return [AccountLine(status="ok", detail=f"{name}, logged in")]
    return [AccountLine(status="FAIL", detail=f"{name}, not logged in", fix=login)]


def labelled_accounts_report(inst: Installation, run: Run) -> list[AccountLine]:
    """One line for each account label a repo names: a note when this machine gives the label
    no directory (its repos use the default account), an error with the login command when the
    directory is missing or not logged in."""
    labels = sorted({repo.account for repo in inst.config.repos.values() if repo.account})
    lines: list[AccountLine] = []
    for label in labels:
        account = claude_account.resolve(inst, label)
        directory = account.config_dir
        if directory is None:
            lines.append(
                AccountLine(
                    status="info",
                    detail=f"account {label!r} has no config_dir on this machine: its repos "
                    "run on the default account",
                )
            )
            continue
        login = _login_command(claude_account.environment_entry(account))
        name = f"account {label!r}: {directory}"
        lines += _directory_lines(run, account, directory, name, login)
    return lines


def _logged_in(run: Run, account: claude_account.Account | None = None) -> bool:
    """Whether `auth status` exits 0 with `loggedIn` true; nothing else of its answer is read."""
    try:
        done = run(
            [*command(), "auth", "status", "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            **_account_run_kwargs(account),
        )
        answer = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and isinstance(answer, dict) and answer.get("loggedIn") is True


def _context(stdout: str, ended: ResultEvent | None, model: str | None) -> Context | None:
    """How full the window was over the run: the window the result names for the model the
    conversation ran on (else the requested one), else the configured table's, which is an
    estimate."""
    fills, markers, ran = request_fills(stdout)
    window = ended.context_window(ran, model) if ended is not None else None
    basis = ContextBasis.REPORTED
    if window is None:
        windows = config.runtime_entry(name=NAME).context_windows
        window = next((windows[m] for m in (ran, model) if m and m in windows), None)
        basis = ContextBasis.ESTIMATED
    return context_of(
        fills,
        window=window,
        basis=basis,
        drop_share=config.active().context.compaction_drop_share,
        markers=markers,
    )


def _spent(ended: ResultEvent | None) -> dict:
    """What the result event says the run spent, as `AgentResult`'s fields."""
    if ended is None:
        return {}
    reported = any(
        figure is not None
        for figure in (ended.usage, ended.total_cost_usd, ended.duration_ms, ended.num_turns)
    )
    return {
        "usage": ended.usage,
        # The result's total is the session's running one, not the call's own spend, so it is
        # reported as the cumulative figure and `cost_usd` stays absent.
        "cumulative_cost_usd": ended.total_cost_usd,
        "duration_ms": ended.duration_ms,
        "session_id": ended.session_id,
        "usage_source": "reported" if reported else "none",
    }


def _progress(request: AgentRequest) -> Callable[[dict], None] | None:
    """Each event worth reading, as a log line for the request's callback, and
    the session's id for its session callback the moment the init event gives it."""
    report, on_session = request.on_event, request.on_session
    transcript, record = request.on_transcript, request.on_record
    if report is None and on_session is None and transcript is None and record is None:
        return None
    prefix = f"{request.cwd}/" if request.cwd is not None else None

    def on_event(event: dict) -> None:
        # Only the init event: each later system event repeats the id, and each
        # report is a checkpoint written to the thread.
        if (
            on_session
            and event.get("type") == "system"
            and event.get("subtype") == "init"
            and event.get("session_id")
        ):
            on_session(str(event["session_id"]))
        if record is not None:
            for made in records(event):
                record(made)
        for callback, whole in ((report, False), (transcript, True)):
            if callback is None:
                continue
            for line in describe(event, whole=whole):
                # Relative to the worktree: its absolute path is the same long
                # prefix on every line and says nothing.
                callback(f"  {line.replace(prefix, '') if prefix else line}")

    return on_event


def through(run: Callable[..., subprocess.CompletedProcess[str]]) -> ClaudeCodeRuntime:
    """This adapter with `run(argv, *, cwd)` in place of the process: the
    shape a call site's own injection point took before the runtime seam,
    which never streamed. `run` is given the argv as it was when the prompt was an
    argument (the prompt after `-p`), so a caller handing one in sees the exact argv, and it
    is called as `run(argv, *, cwd, env=...)` when there is an environment to add (an account
    is set, or the request has entries), so it must accept `env`."""

    def execute(
        argv: list[str],
        *,
        cwd: Path | None = None,
        on_event=None,
        env=None,
        input=None,
        sandbox: SandboxPolicy | None = None,
    ):
        if sandbox is not None:
            # Dropping the policy would run the step unconfined without a word.
            raise RuntimeError("a run injected through `through` cannot carry a sandbox policy")
        if input is not None:
            at = len(command()) + 1  # just after `-p`
            argv = [*argv[:at], input, *argv[at:]]
        return run(argv, cwd=cwd, **({"env": env} if env else {}))

    return ClaudeCodeRuntime(execute=execute)


RUNTIME = ClaudeCodeRuntime()

_: AgentRuntime = RUNTIME
