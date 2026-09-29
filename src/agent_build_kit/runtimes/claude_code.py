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
import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit.hooks.policy import hook_settings
from agent_build_kit.pipeline.claude_stream import (
    STREAM_FLAGS,
    describe,
    final_text,
    own_words,
    result_event,
    stream_run,
)
from agent_build_kit.pipeline.usage_guard import (
    UsageReading,
    rate_limit_reset,
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
    UsageStatus,
)

# (argv, *, cwd, on_event) -> the finished process: `claude_stream.stream_run`'s
# shape. `on_event` is called with each JSON event as it is printed, and is
# None for a run that is not streamed.
Execute = Callable[..., subprocess.CompletedProcess[str]]

# A usage reading, or None when there is none: `usage_guard`'s readers.
ReadUsage = Callable[[], UsageReading | None]

# Passed beside the hook on every policed run. Redundant by design: two
# independent things have to fail before the agent can merge its own PR.
DISALLOWED = (
    "Bash(gh pr merge*) Bash(git push --force *) Bash(git reset --hard*) "
    "Bash(rm -rf*) Bash(git branch -D*)"
)

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
) -> subprocess.CompletedProcess[str]:
    """The real `claude` process: streamed when there is someone to tell."""
    if on_event is not None:
        return stream_run(argv, cwd=cwd, on_event=on_event)
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)


def refresh_login(run: Callable[..., object] = subprocess.run) -> None:
    """Have Claude Code refresh its OAuth token, with the smallest call it
    takes — see `usage_guard.refresh_login` for why the usage read needs it."""
    run(
        ["claude", "-p", "Reply with OK and nothing else.", "--model", "haiku"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def build_argv(request: AgentRequest) -> list[str]:
    argv = ["claude", "-p", request.prompt]
    if request.worktree:
        argv += ["--worktree", request.worktree]
    for directory in request.add_dirs:
        argv += ["--add-dir", str(directory)]
    denied = request.denied_tools
    if request.policy is not None:
        settings = hook_settings(
            request.policy.specs_dir, branch_prefix=request.policy.branch_prefix
        )
        argv += ["--settings", json.dumps(settings)]
        denied = f"{DISALLOWED} {denied}".strip()
    if request.allowed_tools:
        argv += ["--allowedTools", request.allowed_tools]
    if denied:
        argv += ["--disallowedTools", denied]
    if mode := PERMISSION_MODES[request.permission_mode]:
        argv += ["--permission-mode", mode]
    if request.model:
        argv += ["--model", request.model]
    if request.on_event is not None:
        argv += STREAM_FLAGS
    elif request.keep_record:
        argv += ["--output-format", "json"]
    else:
        # The CLI's default, written out as the call sites always have.
        argv += ["--output-format", "text"]
    return argv


class ClaudeCodeRuntime:
    name: str = "claude_code"
    implemented: bool = True
    # The hook sees every tool call before it runs.
    policy_coverage: PolicyCoverage = "all_calls"
    supports_usage_tracking: bool = True
    supports_streaming: bool = True
    # `claude` on PATH is all it needs.
    requires: tuple[str, ...] = ()
    # What `abk doctor` looks for on PATH when abk.yaml names no command.
    agent_command: tuple[str, ...] = ("claude",)

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
        execute = self._execute or spawn
        result = execute(build_argv(request), cwd=request.cwd, on_event=_progress(request))

        if result.returncode < 0:
            raise AgentInterrupted(f"claude was killed by signal {-result.returncode}")
        ended = result_event(result.stdout)
        # An error-subtype result has no `result` text, and `final_text` would
        # then hand back the whole transcript; that belongs in `raw` alone.
        text = "" if ended is not None and ended.result is None else final_text(result.stdout)
        stop_reason = ended.subtype if ended is not None else ""
        if result.returncode:
            # Only what the CLI said about the ending, never the transcript:
            # see `claude_stream.own_words`.
            said = f"{own_words(result.stdout)}\n{result.stderr}".strip()
            reset = rate_limit_reset(said)
            if reset is not False:
                raise AgentRateLimited(said or "claude reported a usage limit", resets_at=reset)
            return AgentResult(
                ok=False,
                text=text,
                raw=result.stdout,
                error=f"claude exited {result.returncode}: {said}",
                stop_reason=stop_reason,
            )
        return AgentResult(ok=True, text=text, raw=result.stdout, stop_reason=stop_reason)

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


def _progress(request: AgentRequest) -> Callable[[dict], None] | None:
    """Each event worth reading, as a log line for the request's callback."""
    report = request.on_event
    if report is None:
        return None
    prefix = f"{request.cwd}/" if request.cwd is not None else None

    def on_event(event: dict) -> None:
        for line in describe(event):
            # Relative to the worktree: its absolute path is the same long
            # prefix on every line and says nothing.
            report(f"  {line.replace(prefix, '') if prefix else line}")

    return on_event


def through(run: Callable[..., subprocess.CompletedProcess[str]]) -> ClaudeCodeRuntime:
    """This adapter with `run(argv, *, cwd)` in place of the process: the
    shape a call site's own injection point took before the runtime seam,
    which never streamed, kept so a caller handing one in still sees the
    exact argv."""

    def execute(argv: list[str], *, cwd: Path | None = None, on_event=None):
        return run(argv, cwd=cwd)

    return ClaudeCodeRuntime(execute=execute)


RUNTIME = ClaudeCodeRuntime()

_: AgentRuntime = RUNTIME
