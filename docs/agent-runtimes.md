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
without a hook contract" and "Proving the constraint: `check_policy`" below),
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
| `pipeline/planner.py` | the planning graph call | plain `claude -p ... --output-format text`; no `--permission-mode`, no cwd, no tool policy, no injected executor shared with anything else |
| `pipeline/restack.py` `claude_resolver` | conflict resolution edit | `--allowedTools` only — no `--permission-mode` (it edits because its tool list says so), no model, no commit — a narrower Claude Code call than the others, built independently |
| `tracks/runner.py` | health/improve/recommend/implement tracks | `--worktree`, `--add-dir`, `--permission-mode acceptEdits`, `--allowedTools`/`--disallowedTools`, `--model`, `--output-format json` |
| `init/research.py` `research` | writes the toolchain recommendations doc | `--allowedTools` (web access), `--output-format text`; no `--permission-mode` |
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
| build, review, rework-review | `pipeline/wiring.py` `build_run` (`build_run_review` wraps it); `runtime=` injects. `build_run` takes the model per call, and the graph nodes pick it: the implement model for `tests` and `implement`, the rework model for `fix_checks`, `rework` and `adapt` |
| the planning graph call | `pipeline/planner.py` `_ask`; `plan_round(runtime=...)` injects |
| conflict resolution | `pipeline/restack.py` `claude_resolver`; `runtime=` injects, and a refusal is re-raised by `move_branch_onto` rather than read as a conflict |
| the scheduled tracks | `tracks/runner.py` `phase_request`, run by `claude_phase`; `runtime=` injects (through `run_track`, each track and `claude_phase`), and a refusal is logged and fails the phase rather than raising |
| research | `init/research.py` `research` |
| a proposal | `init/propose.py` `propose` |
| the login refresh before a usage read | `runtimes/claude_code.py` `refresh_login` — Claude Code's own, not a request |

`init/claude_call.py` now only resolves which runtime an init step uses
(`runtime_for`) and turns a failed result into an error (`succeeded`).

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
| `supports_session_resume` | attr | whether `AgentRequest.resume_session` continues an earlier session; `on_session` is told each session's id as soon as it is known. A runtime without it is never sent a session to resume, and a session it cannot continue raises `SessionUnavailable`. The `acp` runtime supports it where the agent declares the `loadSession` capability; see ACP sessions below |
| `passes_env` | attr | whether the runtime may be minted a gateway key: its agent takes the key from `AgentRequest.env`. One that does not is never minted one (see Spend through a gateway). It may still add `request.env` to its agent's environment, as Claude Code does for `ABK_OUT` |
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
  implement: opus
  rework: opus
  review: opus
  rework_review: fable
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
runtime's names: `claude_code` declares today's `opus`/`fable`; `acp`
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
fails the step.

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

## Proving the constraint: `check_policy`

A runtime whose agent runs its own tools is only as constrained as that
agent's own configuration, and abk must not take that on trust — a
`policy_coverage` of `agent_flagged` states a capability, not a fact about
this machine. `check_policy` establishes the fact.

- **A local answer, where one exists.** Claude Code's adapter answers without
  calling anything: the hook is registered per run and the same denies are
  passed as flags.
- **A probe run, otherwise.** In a throwaway worktree with no remote, the
  adapter asks the agent to attempt one representative command per forbidden
  class — a bare force push, an amend, a skipped commit gate, a merge of a
  pull request, and so on. A class passes only when the attempt reached abk
  and was refused there: a terminal request the rules refused, or a permission
  request answered with a refusing option. Every other class — never
  attempted, run without asking, allowed by the rules, or cut off because no
  refusing option was on offer — is reported unenforced. A probe run that
  itself fails (the agent does not start, or errors) is an error, not a
  report. The command shapes come from abk's own `command_policy` (a test
  holds the list to it), so this names no product, and every attempt is
  harmless in that worktree even if it does run.

  What the client cannot see: an agent that declines a forbidden command
  before announcing any tool call tells abk nothing, so no refusal line, and
  no layer, can be logged for it. The tier-2 build test does not accept that
  silence: it requires a refusal line naming its layer, and fails for an agent
  that never makes the attempt.
- **`abk init` asks before changing anything.** It runs the check for the
  configured runtime, prints each unenforced class in abk's own words, and
  offers to run `runtimes.<name>.policy_fix` — a command the installation
  supplies, whose contents abk never inspects. This is the shape
  `cli/doctor.py`'s `_forge_access` already uses with `forge.access_fix`.
  Declining leaves the workspace untouched and says which guarantee is
  missing.
- **`abk doctor` fails rather than warns** when a class is unenforced, and
  prints the `policy_fix` command. A probe costs one small agent call, so the
  result is cached in the state directory (`<state_dir>/policy-check.json`, per
  runtime) for 15 minutes, as the usage reading already is
  (`runtimes/policy_check.py`); `abk init` asks afresh after running the fix.
  A check the runtime could not answer (it raised) is a FAIL in doctor and a
  printed note in init, and is never cached; one skipped because the agent
  command does not resolve is a doctor warning, as the `runtime` check has
  already failed for that cause.

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

## Per-runtime status

| Runtime | Invocation model | Policy coverage | Model naming | Streaming | Usage window | Status |
|---|---|---|---|---|---|---|
| `claude_code` | local CLI (`claude -p`), subprocess | `all_calls` via the `PreToolUse` hook plus `--disallowedTools` | bare aliases (`opus`, `fable`, ...) via `--model` | `--output-format stream-json`, one JSON event per line | live endpoint with its stored OAuth token, falling back to its own cache | **implemented**, as `runtimes/claude_code.py` |
| `acp` | spawns the configured agent, JSON-RPC over stdio; `session/new` takes the worktree as `cwd`, extra readable directories as workspace roots; `session/prompt` returns the end-turn signal with a `stopReason` (`end_turn`, `max_tokens`, `max_turn_requests`, `refusal`, `cancelled`) | `all_calls` when the agent routes file and terminal work through the client's capabilities; `agent_flagged` otherwise, via `session/request_permission`. `check_policy` decides which | agent-defined: session config options expose a `model` category to select among what the agent offers, so a name abk does not recognise is a no-op, not an error | `session/update` notifications: message chunks, thought chunks, tool-call start and update, plan updates | none, and none needed: billed on demand per token, with no shared window over a time period, so a run is limited only by the work | **implemented**, as `runtimes/acp.py`: runs, outcomes, models, progress, enforcement and `check_policy`; registered when the `acp` extra is installed (see the status paragraph at the top) |

## Test markers

Two markers keep slow tests out of the default suite (`pytest`), and a third keeps a test out of the parallel pass:

- `integration` needs node (`npx`) and the network for the real OpenSpec CLI.
  Run with `pytest -m integration`.
- `local_stack` is the tier-2 marker the acceptance tests carry: they build a
  unit through the `acp` runtime with a real agent on the host, named by
  `ABK_ACCEPTANCE_ACP_COMMAND`, and run `abk tick` as a process. They bill on
  demand and take minutes. Run with `pytest -m local_stack` (or `uv run poe
  test-local-stack`).
- The same build run (`tests/integration/test_acp_build_unit.py`) also checks
  the usage report: `abk report --unit` for the built unit has one agent record
  per agent call in its run log, and its tokens and agent time equal the sums of
  the unit's usage-ledger records, with each figure's source named in the JSON
  and the table. It needs nothing beyond the agent above. Run with `uv run
  pytest -m local_stack tests/integration/test_acp_build_unit.py`.
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
- `serial` marks a test that cannot share a process with others. `poe test`
  runs the suite in parallel workers (pytest-xdist, capped at 8) without these
  tests, then runs them alone in a serial pass. A plain `pytest <file>` runs
  without workers.

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
or `session/load`), before the prompt is sent, so a step that is killed still leaves its id for the
unit's record. On a resume, the runtime reads the agent's `loadSession` capability from its
`initialize` answer. An agent that declares it is sent `session/load` with the recorded id and the
step continues in that session; the history the agent replays while loading is not progress and
not the step's answer, so it is dropped. An agent that does not declare it, or that refuses the
load, raises `SessionUnavailable` (`session <id> not resumed: ...`) before any prompt is sent. The
runtime never opens a session of its own then, because a resume's prompt assumes the old session
holds the task; the node says the session cannot be continued and starts the step over in a new
session with its full prompt.

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
