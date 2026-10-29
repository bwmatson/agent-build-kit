"""What an agent execution engine has to answer, and the values it answers
with.

Every "run the agent and get a result" call in the pipeline goes through one
`AgentRuntime.run()`, given an `AgentRequest` built from abk-level concepts (a
role, a working directory, a tool policy) rather than one runtime's CLI flags.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.transcript import TranscriptEvent
from agent_build_kit.sandboxes import Coverage, SandboxPolicy
from agent_build_kit.usage import Context, Usage, UsageSource

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
Role = Literal["implement", "review", "rework_review", "regression", "plan", "generic"]

# How much of what an agent does abk can interpose on. `all_calls`: every
# tool call reaches abk before it runs (Claude Code's hook; an ACP agent that
# defers file and terminal work to the client). `agent_flagged`: only the
# calls the agent itself decides to ask about. `none`: nothing.
PolicyCoverage = Literal["all_calls", "agent_flagged", "none"]


class PromptTransport(StrEnum):
    """How a runtime carries a prompt to its agent."""

    ARGUMENT = "argument"  # one element of the command line
    STDIN = "stdin"  # the process reads it on its standard input
    PROTOCOL = "protocol"  # a message of the agent protocol


# The most bytes of UTF-8 a prompt may be on each transport: under the single-argument cap with
# room for the other arguments, and a bound on the prompt (not the pipe) for the others.
SAFE_PROMPT_BYTES: dict[PromptTransport, int] = {
    PromptTransport.ARGUMENT: 100_000,
    PromptTransport.STDIN: 2_000_000,
    PromptTransport.PROTOCOL: 2_000_000,
}


class PromptTooLarge(ValueError):
    """A prompt is over the safe size of its runtime's transport; nothing was started."""


def check_prompt_size(request: AgentRequest, transport: PromptTransport) -> int:
    """The request's prompt size in bytes of UTF-8, or `PromptTooLarge` when it is over the
    transport's safe size."""
    data = request.prompt.encode()
    limit = SAFE_PROMPT_BYTES[transport]
    if len(data) > limit:
        named = f" for {request.change}" if request.change else ""
        raise PromptTooLarge(
            f"the {request.role} prompt{named} is {len(data)} bytes; "
            f"the {transport} transport carries at most {limit}"
        )
    return len(data)


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
    no_commit: bool = False  # refuse `git commit` too: the person commits, not the turn
    planning_paths: tuple[str, ...] = ()  # unwritable in the worktree: the pipeline's own
    # Files no command may write, wherever they are: the planning repo's abk.yaml, which holds
    # the review policy a person owns.
    fenced_files: tuple[Path, ...] = ()
    scoped: bool = True  # False: only commit and push are refused, nothing of the unit's rules
    # What the kernel confines the process to; None leaves the process unconfined.
    sandbox: SandboxPolicy | None = None
    # The backend confines the step, so the location guards the kernel repeats stand down.
    confined: bool = False


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
    change: str = ""  # the change the call is for, when it names one
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
    planning_reports_dir: Path | None = None
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
    # The Claude account the call runs on; None: the default account.
    # A claude_account.Account. Untyped: that module imports `config`, which imports this one,
    # so typing it needs the models moved out of `config` first.
    account: Any = None
    # Added to the spawned agent's environment: where a per-run gateway key goes.
    env: dict[str, str] = {}
    # The whole environment the agent starts with, not an addition to ours; None: ours.
    environment: dict[str, str] | None = None


def child_environment(
    environment: dict[str, str] | None, env: dict[str, str]
) -> dict[str, str] | None:
    """What a spawned agent starts with: `environment` whole when given, else this process's,
    plus `env` on top. None when neither is given, for the process's own."""
    if environment is None and not env:
        return None
    return full_environment(environment, env)


def full_environment(environment: dict[str, str] | None, env: dict[str, str]) -> dict[str, str]:
    """`child_environment` as a dict always: this process's environment when neither is given."""
    return {**(os.environ if environment is None else environment), **env}


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
    cumulative_cost_usd: float | None = None  # a running total the runtime reports for its session
    duration_ms: int | None = None
    session_id: str | None = None
    usage_source: UsageSource = "none"
    context: Context | None = None  # the context window's use over the call, when it says
    reported_model: str | None = None  # the model the runtime says ran, when it says

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


class SpellingResult(Frozen):
    """What became of one attempted spelling of a forbidden command class."""

    label: str
    spelling: str
    command: str
    refused: bool
    # The first pattern that refused it, in list order; empty when none did.
    by: str = ""
    # The recommendation leaves this class to the person: it never fails the check.
    by_design: bool = False


class PolicyReport(Frozen):
    """Whether this runtime's agent actually refuses what abk forbids.

    `unenforced` names the forbidden command classes that were *not*
    intercepted, in abk's own words; `fix` is what an operator should run
    about it, which the installation supplies and abk never interprets.
    """

    ok: bool
    unenforced: tuple[str, ...] = ()
    fix: str = ""
    results: tuple[SpellingResult, ...] = ()
    # What the answer is: empty for a runtime's own answer.
    source: str = ""
    # Why no answer could be given; empty when one was.
    cannot_check: str = ""


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


class NetworkUnavailable(RuntimeError):
    """A run ended on a failure to reach the network or the model's host: the
    CLI's words as the message, how sure the signature is, and the host and port called."""

    def __init__(
        self, message: str, *, strength: Literal["strong", "weak"], host: str, port: int = 443
    ) -> None:
        super().__init__(message)
        self.strength = strength
        self.host = host
        self.port = port


class ServiceUnavailable(RuntimeError):
    """A run ended on an HTTP status of 500 to 599 from the model service, after the
    CLI's own retries: the CLI's words as the message, and the status."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


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
    # How much of the agent a sandbox backend confines when this runtime launches it.
    sandbox_coverage: Coverage
    # What `abk policy check` and `abk status` say beside the coverage until it is proven; empty
    # for a runtime whose coverage is.
    sandbox_note: str
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
    # How this runtime carries a prompt to its agent; `check_prompt_size` holds a request to
    # that transport's safe size.
    prompt_transport: PromptTransport
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

        Raises `AgentInterrupted` or `AgentRateLimited` for those two cases, and
        `NetworkUnavailable` (carrying `strength` and `host`) for a run that ended
        on a network or model-host failure; any other non-zero/refused outcome is
        `AgentResult(ok=False, ...)`, never a bare exception a caller has to
        guess the meaning of.
        """
        ...

    def get_usage_status(self) -> UsageStatus | None:
        """None when unsupported, or when this call could not get a reading —
        the caller (usage_guard) already treats both the same way."""
        ...

    def check_policy(self, cwd: Path) -> PolicyReport:
        """Whether the forbidden command classes really are refused here."""
        ...


# What a probe is given instead of the host: `shutil.which` and `subprocess.run`.
Which = Callable[[str], str | None]
Run = Callable[..., subprocess.CompletedProcess]


# What a `Candidate.verified` note starts with when its entry was only read in documentation.
DOCUMENTED_ONLY = "documented only"


class Candidate(Frozen):
    """One way to run an agent that a probe found on this machine."""

    runtime: str
    command: tuple[str, ...]
    label: str
    usable: bool
    reasons: tuple[str, ...] = ()  # why not, when `usable` is False
    note: str = ""  # what it needs, shown on a usable candidate too
    verified: str = ""  # how far its entry has been checked

    @property
    def documented_only(self) -> bool:
        """Whether its entry was taken from documentation and never run."""
        return self.verified.startswith(DOCUMENTED_ONLY)


class QuestionKind(StrEnum):
    ARGV = "argv"
    NAME = "name"
    TEXT = "text"


# The problem with an answer, or None when it is acceptable.
Validator = Callable[[str, Which], str | None]


class Question(Frozen):
    """One thing a runtime's setup asks, and where the answer is written."""

    key: str
    prompt: str
    default: str
    kind: QuestionKind
    validator: Validator
    writes_to: str


class ModelSource(StrEnum):
    ADVERTISED = "advertised"  # the agent said so when a session opened
    DOCUMENTED = "documented"  # static names carried in the runtime, not queried
    NONE = "none"  # the agent lists none


class Model(Frozen):
    name: str
    current: bool = False


class ModelList(Frozen):
    models: tuple[Model, ...] = ()
    source: ModelSource = ModelSource.NONE
    note: str = ""  # says where the list came from, or why there is none


def name_validator(known: tuple[str, ...]) -> Validator:
    """A validator accepting only a name in `known`."""

    def validate(answer: str, which: Which) -> str | None:
        del which
        return None if answer in known else f"{answer!r} is not one of: {', '.join(known)}"

    return validate


def validate_argv(answer: str, which: Which) -> str | None:
    """An answer that is a command whose program is on the path."""
    try:
        argv = shlex.split(answer)
    except ValueError as exc:
        return f"not a command: {exc}"
    if not argv:
        return "enter a command"
    return None if which(argv[0]) else f"{argv[0]} is not on the path"


@runtime_checkable
class Detects(Protocol):
    def detect(self, which: Which, run: Run) -> list[Candidate]: ...


@runtime_checkable
class AsksQuestions(Protocol):
    def setup_questions(self) -> list[Question]: ...


class AccountLine(Frozen):
    """One line `abk doctor` prints about the account a runtime runs on."""

    status: Literal["ok", "info", "warn", "FAIL"]
    detail: str
    fix: str = ""


@runtime_checkable
class ReportsAccount(Protocol):
    def account_report(self, run: Run, env_file: Path | None) -> list[AccountLine]: ...


@runtime_checkable
class ListsModels(Protocol):
    def list_models(self, command: Sequence[str] | None = None) -> ModelList: ...


def candidates_of(runtime: AgentRuntime, which: Which, run: Run) -> list[Candidate]:
    """What `runtime` finds on this machine; none for a runtime without `detect`."""
    return runtime.detect(which, run) if isinstance(runtime, Detects) else []


def questions_of(runtime: AgentRuntime) -> list[Question]:
    """The setup questions `runtime` declares; none for one without them."""
    return runtime.setup_questions() if isinstance(runtime, AsksQuestions) else []


def account_report_of(runtime: AgentRuntime, run: Run, env_file: Path | None) -> list[AccountLine]:
    """What `runtime` says of its account; no lines for a runtime without one."""
    return runtime.account_report(run, env_file) if isinstance(runtime, ReportsAccount) else []


def models_of(runtime: AgentRuntime, command: Sequence[str] | None = None) -> ModelList:
    """The models `runtime` lists, asking `command` when given and the configured one
    otherwise; an empty list saying so for a runtime that cannot."""
    if isinstance(runtime, ListsModels):
        return runtime.list_models(command)
    return ModelList(note="this runtime does not list its models")
