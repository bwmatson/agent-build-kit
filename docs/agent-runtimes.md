# Agent runtimes

**Status: partly implemented.** The Protocol and its registry
(`runtimes/base.py`, `runtimes/__init__.py`), the Claude Code adapter
(`runtimes/claude_code.py`, the one module that builds a `claude` argv), and
every call site going through `AgentRuntime.run()`, choosing a runtime in
`abk.yaml` or the environment, per-runtime model names, and the `doctor` and
`init` runtime checks are in place. The `acp` adapter (`runtimes/acp.py`, behind
the `acp` extra) runs a prompt, maps each end-of-turn reason, selects a model
and streams progress; a request for a named `worktree` it refuses as a
failed result rather than run in `cwd`. Its client capabilities, permission
answering and `check_policy` are now implemented too (see "Policy enforcement
without a hook contract" and "Proving the constraint: `abk policy check`" below),
and it is registered when the `acp` extra is installed — `runtimes/__init__.py`'s
`_load_builtin` imports `runtimes.acp` and registers it only if that import
succeeds, so an installation without the extra still imports cleanly and knows
`claude_code` alone. Every refusal an operator needs to act on is one progress
line, ``refused `<command>` by abk's command rules: <reason>``; a forbidden
command whose call fails without abk having run or answered it reads "by the
agent's own policy" when the call's output says it was blocked or denied, and
otherwise "by the agent's own configuration", a best-effort attribution, since
the protocol does not say why a call failed. That reading is `runtimes/acp_output.py`'s
`denied_call`: a failed update is a denial when the `error.code` in its raw output is a
known denial code, and otherwise when the phrase list reads it as one. The stop-reason strings are the
SDK's `StopReason` type. This document specifies the whole shape, so that adding
a second runtime is writing an adapter against a fixed Protocol, not another
round of the same subprocess plumbing.

The `claude` CLI's closing event is read the same way in `runtimes/claude_output.py`'s
`agent_failure`: only an explicit set of subtypes (`success`) without `is_error` is a
success, whatever the exit status; an `api_error_status` of 429 then says it is a rate limit
without reading any prose, and otherwise the event's own words decide a rate limit, a lost
session or a plain failure. A non-zero exit with a success event is read by its words too.
Recorded events and updates live under `tests/fixtures/external/claude/` and `.../acp/`.

The second adapter is not another product's SDK. It is **ACP, the Agent Client
Protocol** ([agentclientprotocol.com](https://agentclientprotocol.com)) — a
JSON-RPC protocol between a client and a coding agent, spoken today by a few
dozen agents either natively or through an adapter. One `acp` adapter therefore
buys every one of them, and which agent a workspace uses becomes a command in
its `abk.yaml` rather than a module in this repo. That matters beyond tidiness:
a module here may not name a particular installation's tools at all.

Beware the acronym collision: the *Agent Communication Protocol* (agent to
agent, framework-agnostic) is a different, discontinued thing. This is the
editor-to-coding-agent one.

## Why

Every "run an agent and get a result" step — build, rework, review, the
planner's graph call, restack's conflict resolution, a track phase, research,
propose — currently assembles its own `claude` argv with Claude-Code-specific
flags (`--add-dir`, `--settings`, `--allowedTools`/`--disallowedTools`,
`--permission-mode acceptEdits`, `--model`, `--output-format stream-json`).
Two subsystems assume Claude Code more deeply still: the policy hook
(`hooks/policy.py`) is a `PreToolUse` JSON stdin/stdout contract Claude Code
runs before each tool call, and the usage guard (`pipeline/usage_guard.py`)
polls the provider's usage endpoint with Claude Code's own stored OAuth token.

This is the same problem `forges/base.py` and `profiles/base.py` already
solved for code hosts and toolchains: one caller, several possible answerers.
`AgentRuntime` follows that precedent exactly — a `Protocol` (structural, not
inherited), typed value objects instead of raw subprocess/JSON shapes, an
`implemented: bool` flag so an adapter can be declared before it's usable, and
an in-process registry filled by `_load_builtin`.

**Cross-references.** See [architecture.md](architecture.md)'s "The guards"
section for how the policy hook and usage guard read today — accurate only
because Claude Code is the sole runtime. See
[toolchain-profiles.md](toolchain-profiles.md) for the sibling pattern.
`AgentRuntime` and `ToolchainProfile` are orthogonal — a build step asks the
runtime "run this prompt" and the profile "what command tests this" — except
that `ToolchainProfile.allowed_tools` is written in Claude Code's own
`--allowedTools` syntax, which no other runtime can honour; see
"Tool scoping" below.

## The seven call sites before the seam

Before the seam, each of these built its own `claude` argv:

| Site | What it ran | What was Claude-Code-specific about it |
|---|---|---|
| `pipeline/wiring.py` `build_run`/`build_run_review` | build, review, rework-review | `--add-dir`, `--settings` (hook), `--allowedTools`/`--disallowedTools`, `--permission-mode acceptEdits`, `--model`, streamed via `--output-format stream-json` |
| `pipeline/planner.py` | the planning graph call | a plain `claude` call that reads the prompt on standard input, with `--output-format stream-json --verbose` (a recorded call streams, for its usage); no `--permission-mode`, no cwd, no tool policy, no injected executor shared with anything else |
| `pipeline/restack.py` `claude_resolver` | conflict resolution edit | `--allowedTools` only — no `--permission-mode` (it edits because its tool list says so), no model, no commit — a narrower Claude Code call than the others, built independently |
| `tracks/runner.py` | health/improve/recommend/implement tracks | `--worktree`, `--add-dir`, `--permission-mode acceptEdits`, `--allowedTools`/`--disallowedTools`, `--model`, `--output-format stream-json --verbose` |
| `init/research.py` `research` | writes the toolchain recommendations doc | `--allowedTools` (web access), `--output-format stream-json --verbose`; no `--permission-mode` |
| `init/propose.py` `propose` | writes an OpenSpec change | `--add-dir`, `--settings` (hook), `--allowedTools`, `--permission-mode acceptEdits` |
| `init/claude_call.py` | the shared low-level executor | `subprocess.run` + `check_refusal`; `research.py` and `propose.py` built their own argv and passed it through this |

`planner.py` and `restack.py` did not go through `claude_call` — each ran its
own `subprocess.run` with its own refusal handling (or none, for `restack`).
There was no single executor, no single refusal/rate-limit interpretation, and
no single streaming path — just seven places that each learned to talk to
Claude Code slightly differently, two of them not injectable for tests.

Now each site builds an `AgentRequest` and hands it to a runtime, the active
one unless a test injects another:

| Site | Where its request is built |
|---|---|
| build, review, rework-review | `pipeline/wiring.py` `build_run` (`build_run_review` wraps it); `runtime=` injects. `build_run` takes the model per call, and the graph nodes pick it: the implement model for `tests`, `implement` and `fix_checks` (the model the build session began on), the rework model for `rework`, `restack` and `adapt`; a node that continues a session runs on the model that session recorded |
| the planning graph call | `pipeline/planner.py` `_ask`; `plan_round(runtime=...)` injects; a prompt over the transport's safe size fails the planning attempt, naming the size of each part |
| conflict resolution | in a run, `prepare`'s restack resolves through `build_run` as node `restack`, in the build session, on the rework model (or the model the session recorded); the stack-move handler uses `pipeline/restack.py` `claude_resolver` (`runtime=` injects), whose second call continues the first call's session; a refusal is re-raised by `move_branch_onto` rather than read as a conflict |
| the scheduled tracks | `tracks/runner.py` `claude_phase`; `runtime=` injects (through `run_track`, each track and `claude_phase`), and a refusal is logged and fails the phase rather than raising |
| research | `init/research.py` `research` |
| a proposal | `init/propose.py` `propose` |
| the login refresh before a usage read | `runtimes/claude_code.py` `refresh_login` — Claude Code's own, not a request |

`init/claude_call.py` now only resolves which runtime an init step uses
(`runtime_for`) and turns a failed result into an error (`succeeded`).

## How a prompt reaches the agent

A runtime declares a `prompt_transport`, one of three: `argument` (one element of the
command line), `stdin` (the process reads it on its standard input) or `protocol` (a message of
the agent protocol). Claude Code declares `stdin` and never puts the prompt in its argument
list; ACP declares `protocol`. One check in `runtimes/base.py` (`check_prompt_size`) holds every
request to the safe size of its transport, counted in bytes of UTF-8: 100,000 for `argument`,
2,000,000 for `stdin` and `protocol`. A prompt over it fails before any process starts, with a
message naming the call, the size, the limit and the transport. A command set as
`runtimes.claude_code.command` must pass its standard input on to `claude`, or the prompt
never arrives. Fixed one-line probes (the login refresh, the doctor's reply check) keep their
short prompt as an argument.

## The protocol

`AgentRuntime` is a **`typing.Protocol`**, and that is what keeps adapters
consistent with each other: structural, not inherited, for the reason `Forge`
and `ToolchainProfile` are — an adapter owns its own code, a test double is a
plain class, and the handful of things every adapter needs (the registry,
`implemented`) are free functions and a plain flag, not inherited behaviour.
Conformance is checked where this repo already checks types: every adapter
module ends with `_: AgentRuntime = RUNTIME`, so the type checker in
`poe format` fails on drift, and `runtimes/__init__.py` types its registry
`dict[str, AgentRuntime]` so each registration is a checked assignment.

| Member | Kind | What it answers |
|---|---|---|
| `name` | attr | the key an installation names in `abk.yaml` |
| `implemented` | attr | False while an adapter is declared but unfinished |
| `policy_coverage` | attr | `all_calls`, `agent_flagged` or `none` — how much of what an agent does abk can interpose on |
| `supports_usage_tracking` | attr | whether `get_usage_status` can ever answer |
| `supports_streaming` | attr | whether `AgentRequest.on_event` is ever called |
| `supports_session_resume` | attr | whether `AgentRequest.resume_session` continues an earlier session; `on_session` is told each session's id as soon as it is known. A runtime without it is never sent a session to resume, and a session it cannot continue raises `SessionUnavailable`. The `acp` runtime supports it where the agent advertises both `session/resume` and `session/list`; see ACP sessions below |
| `passes_env` | attr | whether the runtime may be minted a gateway key: its agent takes the key from `AgentRequest.env`. One that does not is never minted one (see Spend through a gateway). It may still add `request.env` to its agent's environment, as Claude Code does for `ABK_OUT` |
| `AgentRequest.environment` | field | the whole environment the agent starts with, instead of this process's; `None` (the default) keeps the process's. `env` is added on top of either. A mapping with no `PATH` starts nothing. `abk serve` passes none; `start_server(installation, agent_environment=...)` gives the agents a chat starts one, including the resume check |
| `requires` | attr | the `runtimes.<name>` keys it cannot run without; a selection missing one fails at load |
| `agent_command` | attr | the argv that starts its agent when `runtimes.<name>.command` is unset; a set `command` replaces it in every run and in `abk doctor`'s PATH check alike |
| `default_models` | attr | its own model names for a role nothing in the file or the environment names |
| `run(request)` | method | run one prompt to completion, report the result |
| `get_usage_status()` | method | where an account-level usage window stands, or None |
| `check_policy(cwd)` | method | whether this agent actually refuses what abk forbids |

`runtimes/base.py`:

```python
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
from typing import Literal, Protocol

from agent_build_kit.model import Frozen

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


class AgentRequest(Frozen):
    """One call to an agent, in abk's own terms."""

    prompt: str
    role: Role = "generic"
    cwd: Path | None = None  # None for a call with no worktree (the planner's graph call)
    add_dirs: tuple[Path, ...] = ()  # readable beyond cwd; Claude Code's --add-dir
    model: str | None = None  # already resolved to this runtime's own name — see Config
    allowed_tools: str = ""  # Claude Code's --allowedTools syntax; see Tool scoping
    denied_tools: str = ""  # ditto, --disallowedTools
    permission_mode: PermissionMode = "edit"
    policy: ToolPolicy | None = None  # None: no enforcement asked for (a read-only run)
    on_event: Callable[[str], None] | None = None  # one line per step of progress, if supported
    # A named checkout the runtime makes for this run itself, off cwd's repo —
    # a track phase's; Claude Code's --worktree. None: the run works in cwd.
    worktree: str | None = None
    # The caller keeps the run's whole machine-readable record (`AgentResult.raw`),
    # not only its answer — a track phase writes it to its raw output file.
    # Ignored when `on_event` is set: a streamed run's `raw` is its event lines.
    keep_record: bool = False


class AgentResult(Frozen):
    """What a call answered — not a subprocess's returncode and stdout."""

    ok: bool
    text: str  # the run's final answer — what plain `-p` would have printed
    raw: str = ""  # everything, for diagnostics a caller doesn't otherwise need
    error: str = ""  # set when ok is False
    stop_reason: str = ""  # the runtime's own word for why the turn ended, for diagnostics


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
    supports_session_resume: bool
    passes_env: bool
    requires: tuple[str, ...]
    agent_command: tuple[str, ...]
    default_models: ModelsConfig

    def run(self, request: AgentRequest) -> AgentResult:
        """Run one prompt to completion and report the result.

        Raises `AgentInterrupted` or `AgentRateLimited` for those two cases, and
        `NetworkUnavailable` (carrying `strength` and `host`) for a run that ended
        on a network or model-host failure; any other non-zero/refused outcome is
        `AgentResult(ok=False, ...)`, never a bare exception a caller has to
        guess the meaning of.
        See "Network outages are a typed error".
        """
        ...

    def get_usage_status(self) -> UsageStatus | None:
        """None when unsupported, or when this call could not get a reading —
        the caller (usage_guard) already treats both the same way."""
        ...

    def check_policy(self, cwd: Path) -> PolicyReport:
        """Whether the forbidden command classes really are refused here."""
        ...
```

`runtimes/__init__.py` mirrors `forges`/`profiles`: `get(name)` returns the
registered adapter or raises with the known list; `_load_builtin` imports the
built-in modules and calls `register(RUNTIME)` on each, filled in-process,
no plugin discovery.

## Selecting a runtime, and per-role models

An existing `abk.yaml` needs no edit. `runtime` defaults to `claude_code`,
which requires no installation facts, and the flat `models:` block keeps
meaning "the active runtime's models":

```yaml
models:                   # unchanged; no runtimes: block needed at all
  implement: sonnet
  rework: sonnet
  review: opus
  rework_review: opus
```

A `runtimes:` entry appears only for a runtime that needs a fact abk cannot
default — `acp` has no default agent to spawn — and only for the runtimes a
workspace actually uses:

```yaml
runtime: acp
runtimes:
  acp:
    command: [some-agent, acp]                  # how to spawn the ACP agent
    policy_fix: [scripts/constrain-agent.sh]    # what `abk init` offers to run
    models: {implement: "..."}                  # only when two runtimes' names must coexist
```

**Workspace-level, not per-repo.** A repo's `forge`/`profile` choice is about
that repo's host and toolchain; `runtime` decides what executes *every*
build/review/rework/track step across the whole workspace — a mixed-runtime
workspace would mean two policy models, two usage windows, two of everything,
which nobody has asked for.

Precisely because it is workspace-level, flipping it in `abk.yaml` moves every
repo at once, which is a poor way to try a runtime out. **`ABK_RUNTIME`**
overrides it for one machine or one invocation, the way `ABK_IMPLEMENT_MODEL`
and its siblings already override `models`.

`models()` resolves each role from the `ABK_*_MODEL` overrides, then
`runtimes.<active>.models` where present, then the flat block — only the roles
the file actually names there — then the active adapter's own
`default_models`. A role no config names never falls back to another
runtime's names: `claude_code` declares `sonnet` for implementing and reworking and `opus` for both reviews; `acp`
declares no names at all, and a role no config names runs on whichever agent
`runtimes.acp.command` spawns and its own default. Role to model is deliberately
many-to-one: a runtime with no "expensive versus cheap reviewer" split may
point `rework_review` at the same model as `review`, and a `generic` role
(init's research and propose, the planner) may fall back to `implement`'s.

**The tracks keep their own `tracks.model` and tool lists**, under `tracks:`,
rather than moving under `runtimes.<name>`. The model is not resolved per
runtime: `tracks.model` defaults to `sonnet`, Claude Code's alias, and is sent
as it stands to whichever runtime is active, so a workspace selecting another
runtime sets `tracks.model` itself (or, once one exists, a `track` role in
`runtimes.<name>.models`). The tool lists, like `AgentRequest.allowed_tools`,
are written in Claude Code's `--allowedTools` syntax and are inert on a
runtime that cannot honour them.

**A selection that cannot work fails at load.** `installation.load_config`
reads the planning root's `.env` first, so an `ABK_RUNTIME` set there counts
wherever abk is run from; `config.load` then resolves the runtime in force
(`ABK_RUNTIME`, then `runtime:`) against the registry, and
checks every fact its adapter lists in `requires` is set in its
`runtimes.<name>` entry; an unknown name, or a missing fact, is a
`ConfigError` naming it. Only the selected runtime's entry is checked, so an
entry left over from trying another runtime out is never made to be complete.

## Tool scoping

`AgentRequest.allowed_tools`/`denied_tools` carry Claude Code's own
`--allowedTools` patterns, and `ToolchainProfile.allowed_tools` extends them in
the same syntax. ACP standardizes no equivalent: an agent's tool set comes from
its own configuration, and the protocol has no "these tools only" parameter on
a session. **On the `acp` path both fields are inert**: `runtimes/acp.py` reads
neither, sends nothing for them, and a request that sets them runs exactly as
one that does not — with one difference from silent inertness: the run's log
gets a once-per-run notice that tool scope comes from the agent's own
configuration, not from the request. Translating the lists would mean guessing
at each agent's own tool names and config format, which is the per-product
knowledge this adapter exists to keep out of abk. A workspace scopes its
agent's tools in that agent's own config instead. This is a real reduction in
expressiveness, not a detail to gloss: it is why the policy work below does
not lean on tool scoping for anything load-bearing.

**The one case where the list is applied is a read-only run.** An ordinary
run's tool list is a hint the run did not need — it names an edit tool because
it was going to edit anyway. Two call sites send a list that names no edit tool
at all, because the list is meant to keep the run from editing rather than
merely describe what it planned to do anyway. `wiring.build_run_review` sends
`permission_mode="edit"` with `allowed_tools` naming no edit tool, because "The
reviewer cannot edit" is a property the pipeline states as a guarantee
(docs/architecture.md). `init.research.research` sends
`permission_mode="allowed_tools_only"` with the same shape of list. On `acp` a
request shaped that way — `allowed_tools` is set but names no edit tool,
whatever `permission_mode` it carries — runs in a **read-only broker mode**:
every edit approval is refused, every write through the client's file
capability is refused, and a command is allowed, whether the agent asks
permission for it or has the client run it, only when it matches one of the
list's `Bash(...)` patterns (`*` stands for anything, as in Claude Code, and a
line chaining a second command or redirecting is not covered). A refusal picks
the agent's rejecting option, and the run is cancelled if none is offered.

**The broker holds only what the agent asks permission for; the rest is
detected.** An agent that runs a tool without asking is not stopped by it. So
before a read-only run starts, `acp` records the worktree's `HEAD`, `git
status --porcelain` and `git diff HEAD`, and compares them after it: a run that
moved `HEAD`, added or removed a status entry, or changed a file already
modified returns `AgentResult(ok=False, error=...)` naming what changed. On
`acp` the reviewer's guarantee is kept by refusing what is asked plus failing
the run on any change. The edit is not prevented and stays on disk; the failed
run is what keeps it from being reviewed and committed. A directory that is not
a git worktree has nothing to compare, and a further change to a file that was
already untracked is not seen. A read-only list naming anything the broker cannot
hold back (a web tool, say, rather than `Read`, `Grep`, `Glob` or `Bash(...)`)
is still refused with `AgentResult(ok=False, ...)` before the agent is even
spawned, rather than run under a promise this runtime cannot keep. The
planner's graph call also sends `permission_mode="allowed_tools_only"`, but
with `allowed_tools` empty, so it is not this shape and is let through:
under `claude_code` that run is kept from editing by headless permission
denial, not by a list, so there is no list here for this runtime to enforce.

## Only the pipeline pushes

A policed run — a build, a rework, a review — never pushes: both runtimes
refuse every `git push` before it runs (`command_policy.check_no_push`; the
`acp` broker applies it itself, Claude Code's hook is registered with
`--no-push`). As a backstop, `build_run` reads the unit branch's head
on the remote before and after each agent step and raises `AgentPushed` only
when both reads succeed, the head moved, and the new head is contained in the
worktree's own branch (an ancestor of its HEAD). An unreadable remote, or a head pushed from elsewhere
(a person, the host's update-branch button), is not the agent's and never
fails the step. A repo with no `origin` has no push to catch, so the
check is skipped there.

## Where a redirect may land

A policed run is given `ABK_OUT`, the path of its own scratch folder
(`<worktree>/.abk/out/<run>/`), in `AgentRequest.env`; the `acp`
runtime hands it to its agent, and Claude Code adds it to `claude`'s
environment. `command_policy.check_command` given the worktree allows a shell
redirect (`>`, `>>`, `&>`) into a run's folder, or out of the worktree, and
refuses any other target in it with a reason that names `$ABK_OUT`. Only
unquoted operators are redirects, and a relative target is read from where
the command's earlier `cd`s have moved the shell (one it cannot follow, to a
variable or `-`, makes a relative target refused). The rule covers a checkout
only when it carries a scratch folder (`scratch.carries_scratch`), so a track
run's project checkout is not policed. Claude Code's hook and the `acp` broker
both ask it, so they agree.

## Policy enforcement without a hook contract

The enforcement *logic* (`pipeline/command_policy.check_command`) is already
pure Python, owned by abk, and runtime-agnostic. Only the *wiring* is
Claude-Code-specific: a `PreToolUse` JSON contract registered per run via
`--settings`. Each adapter declares its `policy_coverage`, and there are three
real cases.

**`all_calls`, through a hook** — Claude Code today. `run()` builds the same
`--settings` registration as now, and folds the same denies into
`denied_tools` too, for the reason `wiring.py` already documents: two
independent things have to fail before an agent can merge its own pull
request. Note the asymmetry this arrangement is stuck with — a hook that
crashes *fails open* in Claude Code, which is why `hooks/policy.py` denies on
every unexpected path.

**`all_calls`, by being the executor** — the strongest case, and it is ACP's.
`fs/read_text_file`, `fs/write_text_file` and the `terminal/*` methods are
*client* capabilities advertised at `initialize`, and the specification is
explicit that an agent "MUST NOT" call one the client did not advertise. An
adapter that advertises them runs every command itself, applying
`check_command` before it does, and resolves file writes against the worktree
before performing them. Nothing fails open, because nothing is delegated.
Whether a given agent actually routes its work through those methods is the
agent's choice, which is why this cannot be assumed — see `check_policy`.

**`agent_flagged`, through permission requests** — what is left when an agent
executes its own tools. `session/request_permission` reaches the client with
the tool call's `kind` (`read`, `edit`, `execute`, ...), its `rawInput`, the
`locations` it would touch, and an **agent-supplied** list of options whose
kinds are `allow_once`, `allow_always`, `reject_once`, `reject_always`; the
client answers with one option's id. An adapter answers `execute` with
`check_command` and `edit` by resolving `locations` against the worktree and
the read-only specs directory. Two limits are structural: the agent decides
*which* calls to ask about, and the client can only pick from the options
offered — so if no rejecting option is offered, the adapter cancels the turn
rather than allowing it. This is a weaker guarantee than the two above and
must be documented per runtime, never assumed equivalent.

**`none`** — an agent with no interception point at all can only be as strict
as its own configuration makes it. `abk doctor` says so plainly.

## Recommended policy

`runtimes/recommended_policy.py` holds the policy the kit recommends for a build
agent as one table. Per forbidden class it records the command globs that refuse
it, the samples the globs must refuse, the samples they must allow, and the
refused samples only a glob refuses (the command rules allow them). The commands
come from the spellings table (`pipeline/command_spellings`); only what a glob
alone can show is written in the policy module. Tests hold the table to both.

**Classes covered:** merging a pull request (the `gh pr merge` command, the raw
API's `pulls/*/merge`, and GraphQL's `mergePullRequest`), amending a commit,
and pushing to `main` or `master`. A force push to the default branch is covered
by the push globs and has no globs of its own.

**Dialect** (`DIALECT`): fnmatch globs: `*` matches any run of characters,
spaces and slashes included, `?` one character, `[...]` a character class;
case-insensitive; matched against the whole command and each segment of a
compound command split at `&&`, `||`, `|`, `;` and a newline, with runs of
whitespace collapsed; a pattern is anchored, so it must match the whole command
or segment and a wrapper prefix is not matched.

**An approximation.** `matches` is the matcher `abk policy check` judges with,
not any agent's own. The acceptance test (below) is the confirmation that a
given agent refuses what the globs say it should.

**Spelling rows without a glob reader.** The globs do not read:

- the wrapper and directory-change rows (`env X=1`, `command`, `sudo`,
  `sudo -u root`, `cd . ;`): patterns are anchored, so a prefix is not matched,
  and the agent folds a wrapper's name itself before matching. The judge alone
  reads these rows. This is a deliberate gap.
- the hard-reset and force-delete rows: those are uncovered classes (below).

**Uncovered classes:** skipping the commit gate, a hard reset, discarding
untracked work, force-deleting a branch, a recursive delete and a bare force
push. Refusing them would also refuse them in interactive use, which is a
choice for the person; the agent's own approval step may gate them, which varies
per agent. Each is listed in `UNCOVERED` with that reason.

**Known false positives and gaps.** A glob cannot tell a message from a command,
so `git commit -m 'document the --amend flag'` and `git commit -m fix push to
main` are refused though harmless (`KNOWN_FALSE_POSITIVES`). Some commands that
do what a class forbids are not caught: an alias (`git -c alias.p=push p origin
main`), a bare `git push` that relies on the configured upstream, and
`git push --all origin` (`KNOWN_GAPS`).

**The superset rule.** An installation's extra patterns follow the recommended
list and never replace it (`patterns(extra)` returns the recommended globs in
table order, then the extras, none repeated).

## Proving the constraint: `abk policy check`

A runtime whose agent runs its own tools is only as constrained as that
agent's own configuration, and abk must not take that on trust — a
`policy_coverage` of `agent_flagged` states a capability, not a fact about
this machine. `abk policy check` (`runtimes/policy_check.py`) establishes it
without running the agent.

- **A local answer, where one exists.** Claude Code's adapter answers without
  calling anything: the hook is registered per run and the same denies are
  passed as flags. It reads no configuration.
- **What the check reads.** For a known agent whose row has an applier, the
  check reads the deny list from the agent's own configuration, through the
  applier's reader, and judges every probe command (`PROBE_CLASSES`, one per
  forbidden class plus the spellings listed once in
  `pipeline/command_spellings.py`) with abk's matcher
  (`recommended_policy.matches`). Each result names the first pattern, in list
  order, that refuses the command; a command no pattern refuses is `not
  refused`. It starts no agent, spends no tokens, asks no question and keeps no
  answer: two runs read the file twice. The report carries the label "what the
  configuration says, in abk's dialect; not observed from the agent", and every
  printout ends with it.
- **What it does not observe.** Whether the agent's own matcher agrees with
  abk's dialect, and the client-side rules (the permission request abk answers,
  the terminal it refuses) are not measured here. The acceptance test below
  measures the agreement.
- **Not covered by design.** The six classes in `UNCOVERED` never fail the
  check: one no pattern refuses is printed `not covered by design`, and one a
  pattern does refuse is printed refused, with its pattern and "not required".
- **Cannot check.** An absent configuration file, one that does not parse and a
  deny path that is not a list each give `cannot_check` naming the path and the
  reason. A runtime command with no table entry, or a known agent with no
  applier, gives `cannot check: abk has no policy for this agent`, and the
  report is never ok. `abk policy check` exits 1 for it; doctor warns.
- **`abk init` asks nothing.** It runs the same check for the configured
  runtime, prints each unenforced class in abk's own words, and
  offers to run `runtimes.<name>.policy_fix` — a command the installation
  supplies, whose contents abk never inspects. This is the shape
  `cli/doctor.py`'s `_forge_access` already uses with `forge.access_fix`.
  Declining leaves the workspace untouched and says which guarantee is
  missing, and no question about spending tokens is asked, with or without
  `--yes`.
- **A machine with the kit and the agent and nothing else.** When the
  installation sets no `policy_fix` and the selected agent has an applier,
  init's policy step offers the kit's own recommended policy (`abk policy
  apply`'s merge): it shows the configuration and the diff, asks, applies the
  deny list, checks again and prints what is now refused. So
  `abk init --policy-only` takes such a machine from a failing check to a
  passing one without the agent's own repository. The toolset is left alone
  (`abk policy apply --toolset`), and `--yes` needs `--run-policy-fix` for it.
- **Applying a policy fix.** On an existing installation run
  `abk init --policy-only` (add `--policy-fix ARGV` to supply the fix, and
  `--yes --run-policy-fix` to run a configured one unattended). It prints the
  fix and the unrefused classes and spellings first, runs the fix with its
  output visible, checks again and prints each class and spelling as refused or
  not, then exits 0, 1 or 2. A fix applies only what its own policy file
  lists, so a fix that exits 0 and prints `the fix made no change` means the
  policy content is missing, not that the fix is broken. For an agent with no
  known fix, relying on abk's own protocol layer is the honest limit: abk
  applies its command rules to the permission requests the agent sends it, and
  cannot see what the agent never asks about, so the runtime's coverage stays
  `agent_flagged`. A known-agent table row says a spelling is covered only when
  its `spellings` note records a live check that showed it; otherwise it reads
  UNVERIFIED. `abk doctor` warns on every run for an entry recorded as
  `unchecked`, without checking it, and goes on warning until that line is
  removed from `abk.yaml` after a pass.
- **`abk doctor` fails rather than warns** when a class is unenforced, and
  prints what to run, in order: the installation's `policy_fix`; else the
  runtime's own advice; else, for an agent whose configuration the kit can
  merge into, `abk policy apply`; else `abk policy patterns` (add the globs to
  the agent's configuration) followed by the `policy_fix` key to set. The
  installation's own fix stays first, with `abk policy apply` after it when the
  agent has an applier. The check reads the configuration each time and keeps
  nothing between runs (`abk init` reads it again after running the fix). A
  configuration that is absent or unreadable is a FAIL in doctor naming the
  path or reason; an agent abk has no policy for (`cannot check`) is a doctor
  warning and never a pass; one skipped because the agent command does not
  resolve is a doctor warning, as the `runtime` check has already failed for
  that cause.

### What a real agent does with its deny list: not yet observed

The acceptance test of the policy check drives a real agent over the probe
commands through a test harness (`tests/runtimes/policy_agent_harness.py`): its
client allows every request and runs nothing, one prompt names each command,
and a command counts as reached when the agent asked the client's terminal for
anything during that prompt's turn, refused otherwise. That reading rests on
two things only a real run can show: how the first known agent signals a
refusal by its own deny list (no terminal request, a failed tool call, or a
rejected permission), and whether its approval step refuses anything beyond the
list when the client allows everything, so that the six classes the
recommendation does not cover are seen to run. **Neither has been observed
yet**: the run was not made, because it bills a real model and
lets the agent's own tools act on the machine, which an unattended build does
not do. The harness has been proven with fake agents only, so the items listed
UNVERIFIED in the change's design stand, and the first run of the acceptance
test on a machine that has the agent records the finding here.

## Network outages are a typed error

A run that ends because the network is down raises `NetworkUnavailable`, carrying the
CLI's words, how sure the sign is (`strong` or `weak`, from `runtimes/network.py`) and the
host and port the run called (the base URL it was started with, else the default host on
443). The claude runtime raises it for a non-zero exit whose words carry
the sign, after reporting the call's spend through `on_result`; the ACP runtime raises it
for a failed result with a strong sign, and names no host, so its weak failures stay
ordinary. A failure that carries an HTTP status, a usage limit, a model refusal and a
permission or tool failure are never an outage: they return `AgentResult(ok=False)` as
before. The pipeline decides what a weak sign means (`pipeline/network_probe.py`).

## A failing model service is a typed error

A claude run whose closing event carries an `api_error_status` of 500 to 599 (an overloaded
529 among them) raises `ServiceUnavailable`, with the status and the CLI's words, after
reporting the call's spend through `on_result`. When the status is null the CLI's own words
`API Error: <status>` are read instead, a word before the number allowed. A 4xx (401, 403,
404 and the rest), a 429 (still `AgentRateLimited`), a model refusal and an ending with no
status in the event or the words stay `AgentResult(ok=False)`. The pipeline parks the unit
and caps a row of them at `global_limits.service_unavailable_attempts`.

## Usage tracking is optional

`get_usage_status()` returns `None` for two different reasons, and callers
must not conflate them:

- the runtime has no such concept at all (`supports_usage_tracking=False`) —
  ACP is this case, and not merely because the protocol declines to standardize
  a window: an agent reached over ACP is billed on demand, per token, with no
  shared ceiling over a time window to exhaust. There is nothing to protect and
  nothing to wait for, so such a runtime may run as long as the work takes. The
  usage-guard *step* is skipped for it entirely, as a capability check rather
  than a per-tick call, and the usage percentages (which live under
  `runtimes.claude_code.limits`, and are refused on any other runtime) apply to nothing. **The "unknown
  reading pauses" rule must not leak into this path** — a runtime that never
  had a window would otherwise pause forever on a reading it can never give.
  What the protocol's `usage_update` notification does carry — context
  occupancy and cumulative cost — is diagnostic, not a ceiling;
- the runtime generally supports it but this call couldn't get a reading even
  though `supports_usage_tracking=True` (Claude Code today, when neither the
  live endpoint nor its own cache answers) — this keeps today's rule: **an
  unknown reading pauses.**

`usage_guard.refresh_login`'s tiny call exists only to force Claude Code's own
OAuth token to refresh; it stays private to that adapter's
`get_usage_status`, not a Protocol member.

`AgentRateLimited` still has a job on a usage-tracking runtime, where it means
a window is spent and the pipeline should pause until it resets. On a runtime
without a window it should not be raised at all: a provider's transient refusal
is that turn failing, reported as `AgentResult(ok=False, ...)` for the unit's
own retry to handle, not a reason to stop starting units.

## Skills stay outside the protocol

`src/agent_build_kit/skills/` are `SKILL.md` files with YAML frontmatter,
installed into a repo's `.claude/skills/` by `abk install-skills`, and
discovered by Claude Code's own skill-loading convention when a *person* (or
an interactive session) works in a repo abk manages. That is a different
audience from `AgentRuntime`: the unattended pipeline's build/review/rework
calls get their instructions from prompt text (`REVIEW_PROMPT`, the track
playbooks) plus the target repo's `CLAUDE.md`, never from a Skill.

Conclusion: Skills packaging is **not a member of `AgentRuntime`.** If another
agent ships an equivalent discovery convention, `skills/install()` gains a
second output format behind the same source-of-truth `SKILL.md` content — a
packaging detail inside `skills/`, not a Protocol method.

## Migration steps

Steps 1 to 5 are done, and `acp` is registered when its extra is installed.

1. Add `runtimes/base.py` — the Protocol and value objects above — and
   `runtimes/__init__.py` with the registry (`get`, `register`,
   `_load_builtin`).
2. Add `runtimes/claude_code.py`: move the existing subprocess logic behind
   `ClaudeCodeRuntime`, with **zero behaviour change** for current users —
   same binary, same flags, same hook, same usage semantics, just reached
   through `.run(request)` instead of each call site building its own argv.
   Concretely it absorbs:
   - `init/claude_call.claude_text` as the low-level executor;
   - `pipeline/claude_stream.stream_run`/`describe`/`final_text` as its
     streaming machinery, wired to `AgentRequest.on_event`;
   - `hooks/policy.hook_settings` plus `wiring.py`'s `ALLOWED`/`DISALLOWED`/
     `allowed_tools()` composition, applied when `request.policy is not None`;
   - `pipeline/usage_guard`'s reading and refusal logic behind
     `get_usage_status()`, raising `AgentInterrupted`/`AgentRateLimited`.

   `implemented = True`, `policy_coverage = "all_calls"`,
   `supports_usage_tracking = True`, `supports_streaming = True`.
3. Update each of the seven call sites to build an `AgentRequest` and call
   `runtimes.get(...).run(request)` instead of shelling out. Five already
   accept an injectable callable for tests; that seam stays and now defaults
   to resolving the active runtime. The other two get one: an injectable
   executor on `tracks/runner`, and a `resolve=` default on
   `restack.resolved_move` — and `planner` and `restack` gain the refusal
   interpretation they lack today.
4. Add `runtime`, the optional `runtimes` mapping and `ABK_RUNTIME` as in
   "Selecting a runtime"; add a `_runtime` check to `abk doctor` and the
   `check_policy` ask to `abk init`.
5. Add `runtimes/acp.py` behind an `acp` extra, with the permission handling
   and client capabilities described above. Done, and registered when the
   `acp` extra is installed — see the status paragraph above.

Unlike an unimplemented `ToolchainProfile` — which affects one repo's commands
and simply holds that repo's units — an unimplemented or misconfigured
`AgentRuntime` affects *every* step. Holding every unit in the workspace is
the wrong failure mode: configuration that cannot work (an unknown runtime, a
selected runtime with no spawn command) fails at config-load time with a clear
message.

## Adding an agent

`abk init` offers a protocol agent when it is in the known-agent table, data in
`runtimes/known_agents.py`. An entry (`KnownAgent`) holds:

- `name`, the label shown in the list, and `program`, the executable looked up
  on the path.
- `variants`, the ways to start it as a protocol server in order of
  preference. Each has an `argv` and, for an agent whose flag spelling varies
  by version, a `marker`: the text its `--help` shows when that is the
  spelling it takes. An entry with one variant is never asked to run.
- `needs`, what the agent wants beyond the program (a running gateway, an API
  key); shown on a usable candidate and asked about during init.
- `verified`, how the entry was checked. It is the honest record: say how it
  was run, or `documented only`; an entry nobody has run is UNVERIFIED, and
  `abk doctor` repeats that for a selected entry. A spelling counts as covered
  by the policy check only when the note records a live check that showed it.
- `source`, where the command came from.

To add one, add the entry and a structural test case; no other framework file
may name the product. An agent not in the table is configured through "Other /
my own configuration": its start command is asked, validated as a program on
the path, and recorded under `runtimes.acp.command`.

**What the models question can and cannot know.** Choosing a model never makes
a model call. The list comes from what the agent advertises when a session
opens (`session/new`'s `model` config option, with no prompt sent); the
`models` session-state form is not read by the pinned library. Claude Code has
no command that lists models, so its list is the documented aliases carried
in the runtime and said to be documented, not queried. An agent that advertises
none gets no list: init says so, leaves the roles empty (the agent's own
default) and accepts a typed name it cannot check; a wrong name is reported
later by the run's "agent does not offer model X" notice.

### Applying the recommended policy

A row may carry an `apply` descriptor (`ApplyPolicy`): the variable the agent reads for its
home and the default directory under the person's home, the configuration file, its format,
the key path of its list of refused commands, how bare scalars are read (`yaml_version`), an
optional recommended toolset and how the row was verified. A row without one has no applier
and nothing guesses a path for it; only a row someone verified against the agent's own
configuration gets one. `runtimes/policy_apply.py` is the engine and names no product.

The merge adds the recommended patterns the list lacks, in table order after the operator's
entries (exact string comparison), then the installation's extras once. **It never re-dumps the
file.** The parse (`ruamel.yaml`, read-only) only finds the list and computes what is missing;
the missing `- <pattern>` lines are inserted into the original text after the list's last item,
copying that item's indentation, dash offset and quote style (a pattern that is not plain-safe,
or that the agent's reader would take for something else such as `off`, is quoted), so every
other byte stays as it was, and the file's line endings are kept. A missing list or section is
inserted as a small block of its own. The result is parsed again and written only when it equals
the original plus the added patterns. It refuses, naming the file, the key and why, and writes
nothing: a list written inline, a single string, `null`, an alias, a tagged or anchored value, a
flow mapping, several documents, a top level that is not a mapping, a file that does not parse
and a section or list of the wrong shape. The toolset is replaced only when asked, as text
(only that list's lines change), and shown from and to. Before the first write the original is
copied to `<file>.abk-backup`, which is never overwritten; the write goes through a temporary
file in the same directory with the file's mode, so a failure leaves the original. An absent
file is reported, naming the home variable, and never created. A second run changes nothing.

To add an agent's applier, fill its row's `apply` after checking its file and key, and add a
writer to `WRITERS` if its format has none (YAML only today); the structural test fails a row
whose format has no writer.

## Per-runtime status

| Runtime | Invocation model | Policy coverage | Model naming | Streaming | Usage window | Status |
|---|---|---|---|---|---|---|
| `claude_code` | local CLI (`claude -p`), subprocess; the prompt is read on standard input (`stdin` transport, never an argument), see [How a prompt reaches the agent](#how-a-prompt-reaches-the-agent) | `all_calls` via the `PreToolUse` hook plus `--disallowedTools` | bare aliases (`sonnet`, `opus`, ...) via `--model` | `--output-format stream-json`, one JSON event per line | live endpoint with its stored OAuth token, falling back to its own cache | **implemented**, as `runtimes/claude_code.py` |
| `acp` | spawns the configured agent, JSON-RPC over stdio; the prompt travels as the `session/prompt` message (`protocol` transport), see [How a prompt reaches the agent](#how-a-prompt-reaches-the-agent); `session/new` takes the worktree as `cwd`, extra readable directories as workspace roots; `session/prompt` returns the end-turn signal with a `stopReason` (`end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`) | `all_calls` when the agent routes file and terminal work through the client's capabilities; `agent_flagged` otherwise, via `session/request_permission`. `check_policy` decides which | agent-defined: session config options expose a `model` category to select among what the agent offers, so a name abk does not recognise is a no-op, not an error | `session/update` notifications: message chunks, thought chunks, tool-call start and update, plan updates | none, and none needed: billed on demand per token, with no shared window over a time period, so a run is limited only by the work | **implemented**, as `runtimes/acp.py`: runs, outcomes, models, progress, enforcement and `check_policy`; registered when the `acp` extra is installed (see the status paragraph at the top) |

### Claude Code's account

With `CLAUDE_CONFIG_DIR` or `ABK_CLAUDE_HOME` set (see [configuration.md](configuration.md)),
the runtime adds `CLAUDE_CONFIG_DIR=<dir>` to the environment of every `claude` it starts.
`abk doctor` checks the login with `claude auth status --json` run that way, reading only the
exit status and `loggedIn`. Before a switch, let units in flight finish (a stored session of
the old account starts fresh) and set the usage windows for the new plan under
`runtimes.claude_code.limits`. See [claude-code-second-account.md](claude-code-second-account.md).

## Test markers

The markers the suite uses:

- `integration` needs node (`npx`) and the network for the real OpenSpec CLI.
  Run with `pytest -m integration`.
- `local_stack` is the e2e-test marker the acceptance tests carry: they build a
  unit through the `acp` runtime with a real agent on the host, named by
  `ABK_ACCEPTANCE_ACP_COMMAND`, and run `abk tick` as a process. They bill on
  demand and take minutes. Run with `pytest -m local_stack` (or `uv run poe
  test-local-stack`).
  Some agents refuse to open their real session store below a pytest process,
  so a build keeps no sessions and a step that resumes one fails. Three
  `verify.env` entries give the agent a scratch home of its own:
  `ABK_ACCEPTANCE_AGENT_HOME_VAR` (the variable the agent reads for its home;
  unset, nothing changes), `ABK_ACCEPTANCE_AGENT_HOME` (the real home, `~`
  expanded) and `ABK_ACCEPTANCE_AGENT_HOME_FILES` (comma-separated plain file
  names to link from it, never a directory or the state database). The scratch
  home is a fresh directory, mode 0700, under pytest's temporary directory
  holding only symbolic links to those files; the agent opens a store of its
  own there. Each acceptance test that later resumes a session asserts after its
  first agent step that the agent lists it, and fails there naming these
  variables. Hazards: the agent can rewrite a linked credential through its
  link, so the real file is updated; the scratch homes go only with pytest's
  temporary-directory retention; only names are logged, never contents; a file
  the agent needs and the list omits shows up as the agent failing to start or
  to reach its model, and the fix is to list it. For an agent whose home cannot
  be moved, leave the home variable unset and set the agent's own guard-bypass
  variable in `verify.env` instead: its sessions then land in the person's real
  store, with a working directory under the test temporary directory, and are
  never removed.
- Every test runs under a time limit on each of its setup, call and teardown.
  A test without the `local_stack` marker has `--test-time-limit` seconds
  (default 60); a `local_stack` test has `--e2e-test-time-limit` seconds
  (default 1800, thirty minutes). Zero turns a limit off, and each option leaves
  the other alone. A failure names the limit passed: "test exceeded the time
  limit of 60 seconds", or "test exceeded the e2e-test time limit of 1800
  seconds".
- The same build run (`tests/integration/test_build_unit.py`) also checks
  the usage report: `abk report --unit` for the built unit has one agent record
  per agent call in its run log, and its tokens and agent time equal the sums of
  the unit's usage-ledger records, with each figure's source named in the JSON
  and the table. It needs nothing beyond the agent above. Run with `uv run
  pytest -m local_stack tests/integration/test_build_unit.py`.
- The `abk init` acceptance run (`tests/integration/test_init_runtime_live_stack.py`,
  also `local_stack`) runs the real command as a process against a stand-in agent
  and makes no model call: the stand-in is the protocol test agent placed on a
  `PATH` of its own under a known agent's program name, and it records every
  request it is sent. It needs node for the OpenSpec CLI and nothing else; its
  last test uses a protocol agent installed on the host and skips without one.
  Run with `uv run pytest -m local_stack
  tests/integration/test_init_runtime_live_stack.py`.
- The telemetry acceptance run (`tests/integration/test_telemetry_stack.py`,
  also `local_stack`) ticks a fixture unit with `ABK_OTEL_ENABLED` on and reads
  the trace and the duration series back from the shared stack's stores. It
  needs the stack's dev instance up, plus node, uv and the agent above, and
  these set to the instance's published ports:
  `ABK_ACCEPTANCE_TRACES_ENDPOINT` and `ABK_ACCEPTANCE_METRICS_ENDPOINT` (the
  OTLP/HTTP intake URLs), `ABK_ACCEPTANCE_TRACES_URL` (the trace store's search
  API) and `ABK_ACCEPTANCE_METRICS_URL` (the metrics store's query API). Each
  run uses a service name of its own, so earlier runs in the stores do not
  answer for it. Run with `uv run pytest -m local_stack
  tests/integration/test_telemetry_stack.py`.
- `replay` (the `tests/replay/` plugin, see "Record and replay of external calls"
  below) puts a reverse proxy in front of an e2e-test test's calls to the model
  provider and package index, so a rerun of an unchanged call is answered from a
  recording. It is off unless `ABK_REPLAY_MODE` says otherwise.
- `serial` marks a test that cannot share a process with others. `poe test`
  runs the suite in parallel workers (pytest-xdist, capped at 8) without these
  tests, then runs them alone in a serial pass. A plain `pytest <file>` runs
  without workers.
- `runtime_<name>` (`runtime_claude_code`, `runtime_acp`) names the one agent
  runtime a `local_stack` test drives; a test with none is the untagged base and
  needs no agent. Two different runtime tags on one live-stack test, from the test,
  its class, its module or a parameter, fail collection naming the test, so a
  scenario that needs two runtimes is two tests. Markers are strict: an
  unregistered one fails collection. `dev_stack` marks a test that needs the
  repo's dev stack. `telemetry_otel` marks a test that needs the shared telemetry stack's
  dev instance and the `ABK_ACCEPTANCE_*` variables; every test of
  `tests/integration/test_telemetry_stack.py` carries it. A machine without the stack holds
  a split on it (`tests.e2e_splits.telemetry: {marker: telemetry_otel}`) and does not skip
  the test: a live test whose dependency is missing still fails.

### Splits and their selectors

A repo's e2e-test tests are divided by `tests.e2e_splits` (see `docs/configuration.md`).
A test is in at most one split (exclusive membership): the tests no split selects are
`rest`, and a test selected by two splits is a finding of `abk e2e-test check`, which finds it
by listing each split's tests through the toolchain profile, not through a plugin of the
repo. The profile reports the selector kinds it supports and turns a split's selector
into what its test runner takes; the python profile supports the selector kind `marker`
and turns it into the `-m` expression of the same text. A run is one selection over the
splits: held splits are left out, and a resume or a scheduled change runs one split alone.

A unit whose tests sit in a held split is parked, not failed: a tick does not start it
and `abk status` shows it as waiting for that split. Once the split is released it runs
only that split's tests on the same commit (the whole run if the commit has moved). The scheduled run of a repo is one change per
split, so a held split's scheduled change stays open and parked while the others run.

### This repo's own splits

The kit's own e2e-test tests are split the way any installation splits its tests: the
`abk.yaml` an installation writes for the kit's repo declares one split per runtime.

```yaml
tests:
  e2e_splits:
    acp:
      marker: runtime_acp
    claude_code:
      marker: runtime_claude_code
```

The names `acp` and `claude_code` and the `runtime_` markers are this repo's choice; an
installation may name its splits anything. The repo's own collection plugin (at most one
runtime tag per live-stack test) is a repo-local convenience, not something the framework
uses. A test keeps the example and the markers registered in `pyproject.toml` in step.

A drift test (`tests/test_live_tests_are_tagged.py`) keeps the tags honest: it fails, naming
each, a live-stack test that starts an agent (through the scratch helper, the agent-home
helper or the agent command setting) without exactly one runtime tag, and a scenario with
an `acp` variant and no `claude_code` variant that has no stated reason in its module's
table of reasons (`ACP_ONLY_REASONS`, scenario name to reason; an empty reason fails too).
No module defines a table today; a module that has none counts as empty. The test does
not check that a `claude_code` scenario has an `acp` variant.

### Holding a split

A hold set with `abk e2e-test hold` has no deadline: no time ends it, only `release` (or
`hold: false` for the split in `abk.yaml`). A gate's hold carries its own deadline.

1. Hold it: `abk e2e-test hold <split> [--reason TEXT]` sets `hold: true` on the split in
   `abk.yaml` and writes the entry in `e2e-held.json`, both or neither.
2. See what waits on it: `abk e2e-test status` lists each split and `rest` as usable or held,
   and the units parked on a held split show as waiting in `abk status`.
3. Release it: `abk e2e-test release <split>` removes both. If a gate entry or a hand-written
   `hold: true` still holds it, the command says so and what to change by hand.

When the two disagree, the configuration wins: a split whose configuration says `hold: false`
is usable although `e2e-held.json` holds it, and `status` shows the file entry as overridden.

## Record and replay of external calls

An e2e-test test that asks for the `replay` fixture (`tests/replay/plugin.py`) is given a
reverse proxy with one loopback listener per upstream in its `ReplayConfig`,
which a test gives by overriding the `replay_config` fixture. The `repos.<name>.tests.replay`
section holds the same fields and is accepted by the schema. The plugin does not read it yet,
so the default fixture returns an empty `ReplayConfig`, which has no upstream; `abk status`,
`abk doctor` and `abk replay review` find a repository's cassettes through its
`tests.replay.directory`. The code under test is pointed at the listener through the variables the upstream names in `env`; `fixture.addresses`
and `fixture.environment()` give them. The mode is `ABK_REPLAY_MODE`.

- A cassette is keyed by the upstream's name, method, path, sorted query, the request
  headers the upstream lists in `keyed_headers` and the body (JSON canonicalised) after
  the rules a test declares. Credentials are in no key and no file; a configured secret in
  a response body, a path or a query fails the recording.
- A call's cassette is written to a staging directory and promoted only when the test's
  setup, call and teardown have all passed. A call still in flight when the test ends, a
  response over `max_body_bytes` and a directory past `max_directory_mb` are not
  promoted, and the proxy lists them (`incomplete`, `too_large`, `over_size`).
- An upstream whose host is part of the stack (`verify.env` URL values, the repositories'
  code hosts, the stack settings, loopback, private ranges and single-label names) is
  refused at startup, naming the key.
- Normalisation is declared per test (`replay_rules`) and stored in the cassette; the
  default is none.

### The report, review and the live refresh

- After a test the plugin keeps what it replayed and what went live. A test that replayed
  anything gets a `replay` entry in its `user_properties` and a line in the terminal summary,
  `replayed: N of M external calls replayed, K live`, followed by each live call with where its
  request differs from the nearest earlier cassette for the same test and call index ("path
  differs", "differs at system"), the cassettes that matched but were too old, the unused ones
  and the declared rules that applied. The outcome is unchanged. Billed calls avoided are
  totalled from the usage figures recorded responses carry, read as `input_tokens` and `output_tokens` under `usage` or `message.usage`; a response without them adds nothing.
  Counting runs for review and writing `report.json` happen once per pytest session, so replay
  runs must not use xdist workers: a worker's session skips both.
- The summary ends with `total: H hit, L live, U unused, A aged out` over the run, a `rule used:`
  line for each declared rule that applied, and the billed-calls line. The combined report, a
  `RunReport`, is also written as `report.json` beside `state.json` in each cassette directory,
  overwritten by every run and ignored by that directory's own `.gitignore`, for whatever
  reads it by machine.
- A passing run marks `needs_review`, with a reason, each cassette of the test that no call
  asked for or that a live call at the same index superseded. Nothing is deleted.
  `abk replay review` lists them and `--keep` or `--delete` decides each. `abk status` counts the
  waiting ones and `abk doctor` notes them, warning when one has waited through more than
  `review_after_runs` runs; the next run prints the same warning and fails nothing. A held
  recording that a later passing run uses again has its mark cleared and leaves the unreviewed
  count; one kept by hand is marked again if a later passing run does not ask for it.
- When each cassette was last used and for how many runs it has waited are kept in
  `state.json` in the cassette directory, which ignores it (and `report.json`) in its own
  `.gitignore`, so a run changes no committed file for them.
- Run in `live` mode whenever the prompt text or the code under test changed, and at least
  weekly otherwise, so a replayed pass does not stand in for the provider's behaviour that day.

### How each upstream is pointed at the proxy

Settled by running the tool where it could be run here, and otherwise left marked:

| Upstream | How it is pointed | State |
|---|---|---|
| `uv` package index | `UV_DEFAULT_INDEX` (`UV_INDEX_URL` is deprecated), and `UV_FIND_LINKS` for files outside the index | confirmed from `uv pip install --help`; whether it reaches a tool run inside an agent's subprocess depends on that agent passing its environment on |
| `npm` registry | the `registry` setting, by `NPM_CONFIG_REGISTRY` or `.npmrc` | UNVERIFIED here: the run was refused in this session |
| Package files on a second host | an index names the host of its files in its own responses, so a proxy for the index would need a second upstream of its own with the links rewritten when served and never in the stored body | UNVERIFIED: no index was run against a proxy |
| Claude Code agent (`claude_code` runtime) | `ANTHROPIC_BASE_URL`, added to the agent's environment by the runtime's `request.env` | UNVERIFIED: no agent was started, since one bills on demand; whether its credentials work against a forwarding proxy is also open |
| ACP agent (`runtimes.acp.command`) | no endpoint override is known: the command is the agent's own, and the framework sets none | UNVERIFIED; left out of replay until an override is shown to work |
| Model provider streaming | the proxy stores a body as the sequence of chunks received and replays it in order, so the format matters only to the secret scan | the proxy is tested with chunked responses; the provider's event format is UNVERIFIED |

An upstream that cannot be pointed at the proxy is left out, and a replay report says so.

## Open questions

- **Whether ACP v2 is worth following.** v1 is stable and is what an adapter
  should speak; v2 is a published draft that reworks permission requests and
  moves past strictly turn-based interaction, and its own guidance is to
  support both side by side for some time. Build v1, negotiate later.
- **Whether the Python SDK is the right substrate.** It exists and is
  pydantic-plus-asyncio only, which suits this repo, but it is pre-1.0 while
  the TypeScript and Rust SDKs are 1.0. Pin it, and expect at least one bump.
- **Whether `policy_coverage` should be a hard gate rather than a doctor
  failure.** Today's answer: `abk doctor` fails on an unenforced class and
  `abk init` offers the fix, but nothing stops an operator running a tick
  anyway. If that turns out to be too permissive, the gate belongs in
  `may_start_unit`, beside the usage check, not in the adapter.
- **What a run's sessions cost an agent that keeps them.** An agent whose
  sessions persist will accumulate one per build, review and rework. Whether
  abk should clean them up, and whether ACP even exposes a way to, is unknown
  until the first sustained run.
- **Is workspace-level runtime selection actually sufficient**, or will there
  be a real case for one repo building under one agent while another builds
  under a different one? Nothing today suggests it, and `ABK_RUNTIME` covers
  trialling; the `abk.yaml` shape above assumes not.

## ACP sessions: recorded and resumed

An `acp` step tells `on_session` its session id as soon as the session is opened (`session/new`,
or `session/resume`), before the prompt is sent, so a step that is killed still leaves its id for the
unit's record. On a resume, the runtime reads the agent's `sessionCapabilities` from its `initialize` answer and
sets `supports_session_resume` from them: the agent must advertise both `resume` and `list`. It
then lists the sessions of the working directory, following `next_cursor` until the id is found or
the pages end, and calls `session/resume` only for a listed id; the step continues in that
session. `session/load` is never used, since it replays the whole conversation to the client. An
agent that does not advertise both, or does not list the id, raises `SessionUnavailable`
(`session <id> not resumed: ...`) before any prompt is sent. The runtime never opens a session of
its own then, because a resume's prompt assumes the old session holds the task; the node says the
session cannot be continued and starts the step over in a new session with its full prompt.

The listing is the guard because Hermes answers a `session/resume` of an unknown id by quietly
creating a new session, with no id in the response, so a purged id would turn a resume into a cold
start sent the short continuation prompt. Hermes lists only sessions that have messages, within
its most recent thousand, and stores the cwd of each resume, so the unit's worktree path must stay
stable across the build loop. A session purged between the listing and the resume still falls
through to that silent new session; the continuation prompt tells the agent to re-run the checks
and read the worktree. How long an agent keeps sessions, and whether ACP exposes cleanup, is still
open: reuse makes sessions live longer, so it matters more.

## Spend through a gateway

A runtime that reaches its model through a gateway gives exact figures that do not depend on
what the agent reports. With `ABK_GATEWAY_URL` and `ABK_GATEWAY_MASTER_KEY` set, the agent step
mints a key per call and passes it in `AgentRequest.env` (`ABK_GATEWAY_KEY`); the `acp` runtime
starts its agent with that environment on top of its own, so an agent that reads its key from
the environment at start spends through it. A runtime whose agent does not take its key from
the environment declares `passes_env = False` (it may still add `request.env`, as Claude Code
does for `ABK_OUT`) and is skipped with one log line per call: no key
is minted and the figures stay the agent's own. The runtime itself does nothing more: the call's
totals are read from the gateway when it ends (`pipeline/gateway_usage.py`) and recorded
beside what the runtime reported. An agent that takes its key some other way gets one minted
for nothing, and its figures stay its own.
