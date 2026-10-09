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
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import config
from agent_build_kit.config import ModelsConfig
from agent_build_kit.hooks.policy import hook_settings
from agent_build_kit.pipeline.claude_stream import (
    STREAM_FLAGS,
    ResultEvent,
    describe,
    final_text,
    own_words,
    records,
    result_event,
    stream_run,
)
from agent_build_kit.pipeline.usage_guard import (
    UsageReading,
    read_cached_usage,
    read_live_usage,
)
from agent_build_kit.runtimes.base import (
    AgentInterrupted,
    AgentRateLimited,
    AgentRequest,
    AgentResult,
    AgentRuntime,
    PermissionMode,
    PolicyCoverage,
    PolicyReport,
    SessionUnavailable,
    UsageStatus,
)
from agent_build_kit.runtimes.claude_output import AgentFailure, agent_failure
from agent_build_kit.runtimes.traced import traced

# (argv, *, cwd, on_event) -> the finished process: `claude_stream.stream_run`'s
# shape. `on_event` is called with each JSON event as it is printed, and is
# None for a run that is not streamed.
Execute = Callable[..., subprocess.CompletedProcess[str]]

# A usage reading, or None when there is none: `usage_guard`'s readers.
ReadUsage = Callable[[], UsageReading | None]

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
) -> subprocess.CompletedProcess[str]:
    """The real `claude` process: streamed when there is someone to tell. `env`
    is added to this process's own environment."""
    merged = {**os.environ, **env} if env else None
    if on_event is not None:
        return stream_run(argv, cwd=cwd, on_event=on_event, env=merged)
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, env=merged)


NAME = "claude_code"

# What starts the agent when `runtimes.claude_code.command` is not set.
AGENT_COMMAND: tuple[str, ...] = ("claude",)


def command() -> list[str]:
    """The argv prefix every `claude` call starts with: the installation's
    `runtimes.claude_code.command` when it sets one, else `claude` on PATH —
    the same binary `abk doctor` checks for."""
    return list(config.runtime_entry(name=NAME).command or AGENT_COMMAND)


def refresh_login(run: Callable[..., object] = subprocess.run) -> None:
    """Have Claude Code refresh its OAuth token, with the smallest call it
    takes — see `usage_guard.refresh_login` for why the usage read needs it."""
    run(
        [*command(), "-p", "Reply with OK and nothing else.", "--model", "haiku"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
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
    argv = [*command(), "-p", request.prompt]
    if request.worktree:
        argv += ["--worktree", request.worktree]
    for directory in request.add_dirs:
        argv += ["--add-dir", str(directory)]
    denied = request.denied_tools
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
            no_push=True,
            **planning,
        )
        denied = f"{disallowed()} {denied}".strip()
    elif request.planning_repo is not None:
        settings = hook_settings(None, branch_prefix=config.active().git.branch_prefix, **planning)
    else:
        settings = {}
    argv += ["--settings", json.dumps({**settings, **NO_ATTRIBUTION})]
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
    supports_usage_tracking: bool = True
    supports_streaming: bool = True
    # `--resume <id>`, with the id its init event reports.
    supports_session_resume: bool = True
    # `request.env` is added to `claude`'s environment, but the gateway's key is
    # still not offered to it: that is a decision about the gateway, not the run.
    passes_env: bool = False
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

    def run(self, request: AgentRequest) -> AgentResult:
        return traced(self.name, request, lambda: self._run(request))

    def _run(self, request: AgentRequest) -> AgentResult:
        execute = self._execute or spawn
        # Only when there is something to add: an injected `execute` written
        # before the environment was passed does not take the argument.
        extra = {"env": request.env} if request.env else {}
        result = execute(build_argv(request), cwd=request.cwd, on_event=_progress(request), **extra)
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
            )
            if failure.kind == "rate_limited":
                # Raised, so `_run` never sees it: the spend of a call cut off
                # by the limit is told here.
                if request.on_result is not None:
                    request.on_result(failed.model_copy(update={"error": said}))
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
            **_spent(ended),
        )

    def get_usage_status(self) -> UsageStatus | None:
        read_live = self._read_live or (lambda: read_live_usage(refresh=refresh_login))
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

    def check_policy(self, cwd: Path) -> PolicyReport:
        """Answered locally: every policed run registers the hook and passes
        the same denies as flags, so no class goes unenforced."""
        return PolicyReport(ok=True)


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
        "cost_usd": ended.total_cost_usd,
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
    which never streamed, kept so a caller handing one in still sees the
    exact argv."""

    def execute(argv: list[str], *, cwd: Path | None = None, on_event=None, env=None):
        return run(argv, cwd=cwd)

    return ClaudeCodeRuntime(execute=execute)


RUNTIME = ClaudeCodeRuntime()

_: AgentRuntime = RUNTIME
