"""What an agent execution engine has to answer, and the values it answers
with.

Every "run the agent and get a result" call in the pipeline goes through one
`AgentRuntime.run()`, given an `AgentRequest` built from abk-level concepts (a
role, a working directory, a tool policy) rather than one runtime's CLI flags.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.usage import Usage, UsageSource

if TYPE_CHECKING:
    # config imports this package to check a selection at load.
    from agent_build_kit.config import ModelsConfig

# abk's own vocabulary for what a run may do beyond its tool list — not a
# runtime's own permission string. "edit": file edits in its working
# directory are accepted without asking (Claude Code's acceptEdits), as a
# build, a review and a proposal have always run. "allowed_tools_only":
# nothing is granted but what `allowed_tools` names (no Claude Code
# permission mode at all), as the planner, research and the restack resolver
# have always run — the resolver edits because its tool list says so. A
# runtime with only one mode ignores the field.
PermissionMode = Literal["edit", "allowed_tools_only"]

# The abk-level roles every call site resolves a model for today
# (config.ModelsConfig). A runtime with no equivalent split may point every
# role at the same model name.
Role = Literal["implement", "review", "rework_review", "generic"]

# How much of what an agent does abk can interpose on. `all_calls`: every
# tool call reaches abk before it runs (Claude Code's hook; an ACP agent that
# defers file and terminal work to the client). `agent_flagged`: only the
# calls the agent itself decides to ask about. `none`: nothing.
PolicyCoverage = Literal["all_calls", "agent_flagged", "none"]


class ToolPolicy(Frozen):
    """What a run may touch, in abk's own terms — not a runtime's flag syntax.

    `pipeline/command_policy.check_command` already enforces the command-level
    rules (deny a pull-request merge, a bare force-push, ...) as pure Python;
    this carries only what a runtime needs to *apply* that somewhere — which
    directory is read-only, which branch prefix scopes the rule — not the
    rules themselves.
    """

    specs_dir: Path | None = None  # read-only; None when this run is meant to write there
    branch_prefix: str = "spec/"


class PermissionChoice(Frozen):
    """One option an agent offers when it asks permission."""

    id: str
    name: str
    kind: str


class PermissionAsk(Frozen):
    """A permission request an agent made that a person is asked to answer."""

    call: str
    tool: str
    input: dict[str, object] = {}
    options: tuple[PermissionChoice, ...] = ()


class AgentRequest(Frozen):
    """One call to an agent, in abk's own terms."""

    prompt: str
    role: Role = "generic"
    cwd: Path | None = None  # None for a call with no worktree (the planner's graph call)
    add_dirs: tuple[Path, ...] = ()  # readable beyond cwd; Claude Code's --add-dir
    model: str | None = None  # already resolved to this runtime's own name
    allowed_tools: str = ""  # Claude Code's --allowedTools syntax; inert under acp
    denied_tools: str = ""  # ditto, --disallowedTools
    permission_mode: PermissionMode = "edit"
    policy: ToolPolicy | None = None  # None: no enforcement asked for (a read-only run)
    on_event: Callable[[str], None] | None = None  # one line per step of progress, if supported
    # The same steps with the agent's replies and commands whole, line breaks kept.
    on_transcript: Callable[[str], None] | None = None
    # Told each event of the run in the shape every runtime shares, as it streams.
    on_record: Callable[[TranscriptEvent], None] | None = None
    # A named checkout the runtime makes for this run itself, off cwd's repo —
    # a track phase's; Claude Code's --worktree. None: the run works in cwd.
    worktree: str | None = None
    # A track run's: the planning repo's branches are the pipeline's to keep,
    # so the runtime refuses branch-changing git aimed at it.
    planning_repo: Path | None = None
    # Where in that repo the run may write (its run log and tracker); the hook
    # refuses file writes outside the run's checkout otherwise.
    planning_state_dir: Path | None = None
    # The one change a propose run may write in that repo. A run with cwd in the
    # planning repo owns all of it as its checkout, so this and the state
    # directory are what the hook opens, and the rest stays fenced off.
    planning_change_dir: Path | None = None
    # The caller keeps the run's whole machine-readable record (`AgentResult.raw`),
    # not only its answer — a track phase writes it to its raw output file.
    # Ignored when `on_event` is set: a streamed run's `raw` is its event lines.
    keep_record: bool = False
    # A session to continue instead of starting one; honoured only by a runtime
    # that declares `supports_session_resume`.
    resume_session: str = ""
    # Told the session's id as soon as the runtime knows it.
    on_session: Callable[[str], None] | None = None
    # Called by the runtime with the finished result, as `on_session` is with
    # the session.
    on_result: Callable[[AgentResult], None] | None = None
    # Asked, on a worker thread, whether a call the abk rules allow may go ahead; it answers
    # with the id of the option chosen, or None to deny. Never consulted for a call the
    # rules forbid, so it cannot widen what a run may do. Honoured by a runtime that asks.
    on_permission: Callable[[PermissionAsk], str | None] | None = None
    # With `resume_session`: continue in a copy of the session, leaving the first untouched.
    fork_session: bool = False
    # Added to the spawned agent's environment: where a per-run gateway key goes.
    env: dict[str, str] = {}


class AgentResult(Frozen):
    """What a call answered — not a subprocess's returncode and stdout."""

    ok: bool
    text: str  # the run's final answer — what plain `-p` would have printed
    raw: str = ""  # everything, for diagnostics a caller doesn't otherwise need
    error: str = ""  # set when ok is False
    stop_reason: str = ""  # the runtime's own word for why the turn ended, for diagnostics
    turns: int | None = None  # how many turns the run took, when the runtime counts them
    usage: Usage | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    session_id: str | None = None
    usage_source: UsageSource = "none"

    @property
    def succeeded(self) -> bool:
        """Whether the call did its work: it ended `ok` and not on an error result.
        A run that exits cleanly can still close on `error_max_turns`."""
        return self.ok and not self.stop_reason.startswith("error")

    @property
    def tokens(self) -> dict[str, int]:
        """Tokens spent by kind (`input`, `output`, `cache`), from `usage`;
        empty when the runtime reported no counts, and no kind it omits."""
        if self.usage is None:
            return {}
        counts: dict[str, int | None] = {
            "input": self.usage.input_tokens,
            "output": self.usage.output_tokens,
        }
        cached = [self.usage.cache_creation_input_tokens, self.usage.cache_read_input_tokens]
        if any(isinstance(n, int) for n in cached):
            counts["cache"] = sum(n for n in cached if isinstance(n, int))
        return {kind: n for kind, n in counts.items() if isinstance(n, int)}


class PolicyReport(Frozen):
    """Whether this runtime's agent actually refuses what abk forbids.

    `unenforced` names the forbidden command classes that were *not*
    intercepted, in abk's own words; `fix` is what an operator should run
    about it, which the installation supplies and abk never interprets.
    """

    ok: bool
    unenforced: tuple[str, ...] = ()
    fix: str = ""


class AgentInterrupted(RuntimeError):
    """The run was killed (a signal, a timeout the runtime itself enforces, a
    cancelled turn), not refused and not broken. Says nothing about the work:
    the tick resumes the unit from its thread rather than the unit being marked failed."""


class SessionUnavailable(RuntimeError):
    """The runtime could not continue `AgentRequest.resume_session`: it is gone,
    unreadable by this version, or refused."""


class AgentRateLimited(RuntimeError):
    """The runtime refused: an account-level usage window is exhausted, not a
    problem with this call. `resets_at` is None when the runtime cannot say."""

    def __init__(self, message: str, *, resets_at: datetime | None = None) -> None:
        super().__init__(message)
        self.resets_at = resets_at


class UsageStatus(Frozen):
    """Where an account-level usage window stands, in the vocabulary
    `pipeline/usage_guard.py` already uses (`UsageReading`, trimmed to what a
    runtime-agnostic caller can rely on existing)."""

    session_pct: int
    weekly_pct: int
    resets_at: datetime | None
    # When the reading was taken: a cached one may be hours old.
    observed_at: datetime
    source: str


class AgentRuntime(Protocol):
    name: str
    implemented: bool
    policy_coverage: PolicyCoverage
    supports_usage_tracking: bool
    supports_streaming: bool
    # Whether `AgentRequest.resume_session` continues an earlier session; one
    # that does not is never sent it, and its node runs from its start instead.
    supports_session_resume: bool
    # Whether this runtime may be minted a gateway key: its agent takes the key
    # from `AgentRequest.env`. One that does not is never minted one. A runtime
    # may still add `request.env` to its agent's environment without it, as
    # Claude Code does for `ABK_OUT`.
    passes_env: bool
    # The facts this runtime cannot run without, by their key in its
    # `runtimes.<name>` entry in abk.yaml (`command`, ...): a selection that
    # leaves one out fails at load. Empty for a runtime abk can default.
    requires: tuple[str, ...]
    # The argv that starts this runtime's agent when its `runtimes.<name>`
    # entry sets no `command`; one that does replaces it, in the runs the
    # adapter spawns and in what `abk doctor` looks for on PATH alike. Empty
    # for a runtime that spawns nothing.
    agent_command: tuple[str, ...]
    # The model names for a role nothing in abk.yaml or the environment
    # names: this runtime's own, never another's.
    default_models: ModelsConfig

    def run(self, request: AgentRequest) -> AgentResult:
        """Run one prompt to completion and report the result.

        Raises `AgentInterrupted` or `AgentRateLimited` for those two cases;
        any other non-zero/refused outcome is `AgentResult(ok=False, ...)`,
        never a bare exception a caller has to guess the meaning of.
        """
        ...

    def get_usage_status(self) -> UsageStatus | None:
        """None when unsupported, or when this call could not get a reading —
        the caller (usage_guard) already treats both the same way."""
        ...

    def check_policy(self, cwd: Path) -> PolicyReport:
        """Whether the forbidden command classes really are refused here."""
        ...
