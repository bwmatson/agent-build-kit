# Agent runtimes

**Status: design proposal, not implemented.** Claude Code is still the only
runtime the pipeline knows how to talk to — every call site below still shells
out to `claude -p` directly. This document specifies the shape that should sit
behind those calls, so that adding a second runtime is writing an adapter
against a fixed Protocol, not another round of the same subprocess plumbing.
Sections marked **TO BE FILLED IN** are placeholders until Hermes's and
OpenClaw's own specs (and enough of ADK's operational detail) are in hand;
everything else here is settled enough to build against.

## Why

Every "run an agent and get a result" step — build, rework, review, the
planner's graph call, restack's conflict resolution, a track phase, research,
propose — currently assembles its own `claude` argv with Claude-Code-specific
flags (`--add-dir`, `--settings`, `--allowedTools`/`--disallowedTools`,
`--permission-mode acceptEdits`, `--model`, `--output-format stream-json`).
Two subsystems assume Claude Code more deeply still: the policy hook
(`hooks/policy.py`) is a `PreToolUse` JSON stdin/stdout contract Claude Code
runs before each tool call, and the usage guard (`pipeline/usage_guard.py`)
polls Anthropic's usage endpoint with Claude Code's own stored OAuth token.

This is the same problem `forges/base.py` and `profiles/base.py` already
solved for code hosts and toolchains: one caller, several possible answerers.
`AgentRuntime` follows that precedent exactly — a `Protocol` (structural, not
inherited), typed value objects instead of raw subprocess/JSON shapes, an
`implemented: bool` flag so an adapter can be declared before it's usable, and
an in-process registry filled by `_load_builtin`.

**Cross-references.** See [architecture.md](architecture.md)'s "The guards"
section for how the policy hook and usage guard read today — accurate only
because Claude Code is the sole runtime; once this generalizes, that section
should gain a pointer here rather than stating Claude Code specifics as
unconditional fact (not done in this pass — this is a design document only).
See [toolchain-profiles.md](toolchain-profiles.md) for the sibling pattern.
`AgentRuntime` and `ToolchainProfile` are orthogonal — a build step asks the
runtime "run this prompt" and the profile "what command tests this" — except
that `ToolchainProfile.allowed_tools` is already written in Claude Code's own
`--allowedTools` syntax, a coupling this document does not resolve (see
Open questions).

## The seven call sites today

| Site | What it runs | Claude-Code-specific about it |
|---|---|---|
| `pipeline/wiring.py` `build_run_claude`/`build_run_review` | build, rework, review, rework-review | `--add-dir`, `--settings` (hook), `--allowedTools`/`--disallowedTools`, `--permission-mode acceptEdits`, `--model`, streamed via `--output-format stream-json` |
| `pipeline/planner.py:338` `_claude` | the planning graph call | plain `claude -p ... --output-format text`; no cwd, no tool policy, no injected executor shared with anything else |
| `pipeline/restack.py:406` `claude_resolver` | conflict resolution edit | `--allowedTools` only, no model, no commit — a narrower Claude Code call than the others, built independently |
| `tracks/runner.py:330` `build_command` | health/improve/recommend/implement tracks | `--worktree`, `--add-dir`, `--permission-mode acceptEdits`, `--allowedTools`/`--disallowedTools`, `--model`, `--output-format json` |
| `init/research.py:126` `research` | writes the toolchain recommendations doc | `--allowedTools` (web access), `--output-format text` |
| `init/propose.py:266` `propose` | writes an OpenSpec change | `--add-dir`, `--settings` (hook), `--allowedTools`, `--permission-mode acceptEdits` |
| `init/claude_call.py` `claude_text` | the shared low-level executor | `subprocess.run` + `check_refusal`; `research.py` and `propose.py` build their own argv and pass it through this |

Note that `planner.py` and `restack.py` don't even go through `claude_call`
today — each runs its own `subprocess.run` with its own refusal handling (or
none, for `restack`). Part of what this abstraction fixes is that there is
currently no single executor, no single refusal/rate-limit interpretation, and
no single streaming path — just seven places that each learned to talk to
Claude Code slightly differently.

## The protocol

`runtimes/base.py`:

```python
"""What an agent execution engine has to answer, and the values it answers
with.

Every "run the agent and get a result" call in the pipeline goes through one
`AgentRuntime.run()`, given an `AgentRequest` built from abk-level concepts (a
role, a working directory, a tool policy) rather than one runtime's CLI flags.

A `Protocol`, not a base class, for the reason `Forge` and `ToolchainProfile`
are: an adapter owns its own code, a test double is a plain class, and the
handful of things every adapter needs (the registry, `implemented`) are free
functions and a plain flag, not inherited behaviour.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from agent_build_kit.model import Frozen

# abk's own vocabulary for what a run may do to its worktree — not a
# runtime's own permission string. "edit" is Claude Code's acceptEdits;
# "read_only" is a review run that carries no edit tools at all. A runtime
# with only one mode ignores the field.
PermissionMode = Literal["edit", "read_only"]

# The abk-level roles every call site resolves a model for today
# (config.ModelsConfig). A runtime with no equivalent split may point every
# role at the same model name.
Role = Literal["implement", "rework", "review", "rework_review", "generic"]


class ToolPolicy(Frozen):
    """What a run may touch, in abk's own terms — not a runtime's flag syntax.

    `pipeline/command_policy.check_command` already enforces the command-level
    rules (deny `gh pr merge`, a bare force-push, ...) as pure Python; this
    carries only what a runtime needs to *apply* that somewhere — which
    directory is read-only, which branch prefix scopes the rule — not the
    rules themselves. A runtime with no way to intercept tool calls at all
    cannot honour this; see "Tool policy without a hook contract".
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
    allowed_tools: str = ""  # today, Claude Code's --allowedTools syntax — see Open questions
    denied_tools: str = ""  # ditto, --disallowedTools
    permission_mode: PermissionMode = "edit"
    policy: ToolPolicy | None = None  # None: no enforcement asked for (a read-only run)
    on_event: Callable[[str], None] | None = None  # one line per step of progress, if supported


class AgentResult(Frozen):
    """What a call answered — not a subprocess's returncode and stdout."""

    ok: bool
    text: str  # the run's final answer — what plain `-p` would have printed
    raw: str = ""  # everything, for diagnostics a caller doesn't otherwise need
    error: str = ""  # set when ok is False


class AgentInterrupted(RuntimeError):
    """The run was killed (a signal, a timeout the runtime itself enforces),
    not refused and not broken. Says nothing about the work: `reclaim_stale`
    recovers it rather than the unit being marked failed."""


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
    source: str


class AgentRuntime(Protocol):
    name: str
    # False while a runtime is declared but unfinished: callers hold rather
    # than fail — except a runtime, unlike a profile, is load-bearing for
    # every step, so see "Migration" for why this may need to refuse at
    # config-load time instead of per-unit.
    implemented: bool
    # Whether this runtime has an equivalent to Claude Code's PreToolUse hook
    # (or any other tool-call interception point abk can hand a ToolPolicy to).
    supports_tool_policy_hooks: bool
    # Whether get_usage_status can ever answer.
    supports_usage_tracking: bool
    # Whether AgentRequest.on_event will ever be called.
    supports_streaming: bool

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
```

`runtimes/__init__.py` mirrors `forges`/`profiles`: `get(name)` returns the
registered adapter or raises with the known list; `_load_builtin` imports the
built-in modules and calls `register(RUNTIME)` on each, filled in-process,
no plugin discovery.

## Selecting a runtime, and per-role models

```yaml
runtime: claude_code   # agent_build_kit.runtimes registry — like a repo's forge/profile

runtimes:
  claude_code:
    models:
      implement: opus
      rework: opus
      review: opus
      rework_review: fable
  google_adk:      # not implemented — see the placeholder table below
    models: {}
  hermes:
    models: {}
  openclaw:
    models: {}
```

**Workspace-level, not per-repo.** A repo's `forge`/`profile` choice is about
that repo's host and toolchain; `runtime` decides what executes *every*
build/review/rework/track step across the whole workspace — a mixed-runtime
workspace would mean two policy models, two usage windows, two of everything,
which nobody has asked for. See Open questions for whether that ever changes.

`ModelsConfig` moves from one flat block to one block per runtime, keyed the
way `repos` already is. `models()` (`config.py`) resolves
`active().runtimes[active().runtime].models`; a runtime whose config omits a
role falls back to that runtime adapter's own baked-in default (the way
`implement: str = "opus"` is a default today) — never Claude Code's defaults
leaking into an ADK config. Role → model is deliberately many-to-one: a
runtime with no "expensive vs. cheap reviewer" split may point
`rework_review` at the same model as `review`; nothing requires four distinct
names, and a `generic` role (init/research/propose, the planner) may fall back
to `implement`'s model when a runtime's config doesn't distinguish it.

## Optional capabilities

### Tool policy without a hook contract

The enforcement *logic* (`pipeline/command_policy.check_command`) is already
pure Python, owned by abk, and runtime-agnostic. Only the *wiring* — Claude
Code's `PreToolUse` JSON contract, registered per run via `--settings` — is
Claude-Code-specific. Each adapter answers `supports_tool_policy_hooks`.

- **True** (Claude Code today): `run()` builds the same `--settings`
  registration as now, and folds the same denies into `denied_tools` too, for
  the reason `wiring.py` already documents — two independent things have to
  fail before an agent can merge its own PR.
- **False**, two fallback tiers, in order of preference:
  1. **abk-mediated tool execution** — available only for a runtime whose
     invocation model gives abk the tool implementations themselves (an SDK
     where abk registers a Bash-equivalent tool with its own handler), rather
     than a fully opaque CLI or hosted call. There, the adapter wraps that
     tool with `command_policy.check_command` itself before letting it run —
     no Protocol addition needed, since this happens inside the adapter's own
     `run()`, not a plug-in point `AgentRuntime` has to expose.
  2. **Best-effort / unavailable** — a CLI or hosted-API runtime with no
     interception point at all can only be as strict as its own
     `allowed_tools`/`denied_tools` string lets it be, plus what never
     depended on the hook in the first place (nothing merges without human
     review; the push gate still runs in command form on every branch). This
     must be documented plainly per runtime, not silently weaker than Claude
     Code's guarantee — `abk doctor` should warn (not error) when the active
     runtime has `supports_tool_policy_hooks=False`, so an operator decides
     whether that runtime is safe for their workspace.

### Usage tracking is optional

`get_usage_status()` returns `None` for two different reasons, and callers
must not conflate them:

- the runtime has no such concept at all (`supports_usage_tracking=False`,
  e.g. a hosted API billed per token with no shared session window — there is
  nothing to protect, so the usage-guard *step* should be skipped for that
  runtime entirely, as a capability check, not a per-tick call);
- the runtime generally supports it but this call couldn't get a reading even
  though `supports_usage_tracking=True` (Claude Code today, when neither the
  live endpoint nor `~/.claude.json` answers) — this keeps today's rule: **an
  unknown reading pauses.**

`usage_guard.refresh_login`'s tiny `haiku` call exists only to force Claude
Code's own OAuth token to refresh; it stays private to the Claude Code
adapter's `get_usage_status` implementation, not a Protocol member — no other
runtime's usage polling is expected to need an equivalent trick, and one that
does can do it inside its own adapter the same way.

## Skills stay outside the protocol

`src/agent_build_kit/skills/` (`abk-authoring`, `abk-config`, `abk-pipeline`)
are `SKILL.md` files with YAML frontmatter, installed into a repo's
`.claude/skills/` by `abk install-skills`, and discovered by Claude Code's own
skill-loading convention when a *person* (or an interactive Claude Code
session) works in a repo abk manages. That is a different audience from
`AgentRuntime`: the unattended pipeline's build/review/rework calls get their
instructions from prompt text (`REVIEW_PROMPT`, the track playbooks) plus the
target repo's `CLAUDE.md`, never from a Skill. Skills are onboarding/reference
material for whoever — human or agent — is driving the repo interactively,
orthogonal to which runtime executes the pipeline's own steps.

Conclusion: Skills packaging is **not a member of `AgentRuntime`.** Adding a
second pipeline runtime does not, by itself, obligate a parallel Skills
mechanism. If Hermes, OpenClaw or ADK eventually ship an equivalent discovery
convention for their own interactive product (a manifest, an instructions
directory, an MCP-style tool-description registry), `skills/install()` gains
a second output format behind the same source-of-truth `SKILL.md` content —
a packaging detail inside `skills/`, not a Protocol method.

## Migration steps

1. Add `runtimes/base.py` — the Protocol and value objects above — and
   `runtimes/__init__.py` with the registry (`get`, `register`, `_load_builtin`).
2. Add `runtimes/claude_code.py`: move the existing subprocess logic behind
   `ClaudeCodeRuntime`, with **zero behavior change** for current users —
   same `claude` binary, same flags, same hook, same usage semantics, just
   reached through `.run(request)` / `.get_usage_status()` instead of each
   call site building its own argv. Concretely it absorbs:
   - `init/claude_call.claude_text` as the low-level executor;
   - `pipeline/claude_stream.stream_run`/`describe`/`final_text` as its
     streaming machinery, wired to `AgentRequest.on_event`;
   - `hooks/policy.hook_settings` plus `wiring.py`'s `ALLOWED`/`DISALLOWED`/
     `allowed_tools()` composition, applied when `request.policy is not None`;
   - `pipeline/usage_guard`'s `read_live_usage`/`read_cached_usage`/
     `current_usage`/`refresh_login` behind `get_usage_status()`;
   - `check_refusal`'s `Interrupted`/`RateLimited`/plain-`RuntimeError`
     distinction, raising `AgentInterrupted`/`AgentRateLimited` from here.
   `implemented = True`, `supports_tool_policy_hooks = True`,
   `supports_usage_tracking = True`, `supports_streaming = True`.
3. Update each of the seven call sites to build an `AgentRequest` and call
   `runtimes.get(active().runtime).run(request)` instead of shelling out
   directly: `wiring.build_run_claude`/`build_run_review`,
   `planner.plan_round`'s `_claude`, `restack.claude_resolver`,
   `tracks/runner.build_command`+`run_phase_command`, `init/research.research`,
   `init/propose.propose`. Each already accepts an injectable callable for
   tests (`run`, `run_claude`, `run_openspec`); that seam stays — it now
   defaults to resolving the active runtime instead of calling `claude`
   directly, so existing tests that inject a fake keep working unchanged.
4. Generalize `config.ModelsConfig`/`abk.yaml` as in "Selecting a runtime"
   above; update `models()` to resolve per active runtime.
5. Add stub adapters `runtimes/google_adk.py`, `runtimes/hermes.py`,
   `runtimes/openclaw.py`: declared, `implemented = False`, every method
   raises `NotImplementedError`, capability flags left as documented
   best-guesses (see the table below), registered in `_load_builtin` beside
   `claude_code`.
6. **Open design point, not resolved here:** unlike an unimplemented
   `ToolchainProfile` (which only affects one repo's tier-1/tier-2 commands,
   and a unit in that repo simply goes `held`), an unimplemented
   `AgentRuntime` affects *every* step — planning, building, tracks all call
   it. Holding every unit in the workspace the way `node_npm` holds one repo's
   units is probably the wrong failure mode; `Installation`/`abk doctor`
   should more likely refuse to load a workspace configured with a
   non-implemented runtime, failing at config-load time with a clear message,
   rather than deferring to per-unit `held` states that would cover the whole
   pipeline in silence. Decide this when the first stub is actually wired in,
   not now.

## Per-runtime status

| Runtime | Invocation model | Tool execution / sandboxing | Model naming | Streaming | Tool policy hook equivalent | Usage/rate tracking equivalent | Status |
|---|---|---|---|---|---|---|---|
| `claude_code` | local CLI (`claude -p`), subprocess | Claude Code's own tool set, gated by `--allowedTools`/`--disallowedTools` + `PreToolUse` hook | bare aliases (`opus`, `fable`, ...) via `--model` | `--output-format stream-json`, one JSON event per line | `PreToolUse` hook, `--settings` per run | live usage endpoint with Claude Code's OAuth token, falling back to `~/.claude.json`'s cache | **implemented** |
| `google_adk` | **TO BE FILLED IN** — SDK (Python/Java) invoked in-process, a local dev server, or a hosted Agent Engine deployment? Each implies a very different `run()` | **TO BE FILLED IN** — ADK's own tool-calling contract; does it expose a pre-tool-call callback abk could hand a `ToolPolicy`? | **TO BE FILLED IN** — Gemini model ids (`gemini-2.5-pro` etc.), and whether ADK lets abk pick a model per agent invocation or only per agent definition | **TO BE FILLED IN** — ADK has streaming events for its own UI; whether they're capturable from a scripted caller is unknown | **TO BE FILLED IN** — does ADK have a before-tool-call callback usable as a hook-equivalent? | **TO BE FILLED IN** — Google Cloud billing/quota, not an Anthropic-style subscription window; likely `supports_usage_tracking = False` unless a Cloud quota API is worth polling | **not implemented** |
| `hermes` | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **not implemented** |
| `openclaw` | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **TO BE FILLED IN** | **not implemented** |

## Open questions

These can't be resolved without the missing specs, and are flagged rather than
guessed at:

- **Does Hermes (or OpenClaw) support anything like `PreToolUse` hooks**, or
  any interception point at all? Until known, both adapters must default to
  `supports_tool_policy_hooks = False` and the "best-effort/unavailable" path.
- **Is OpenClaw a hosted API, a local CLI, or an SDK?** This decides whether
  `AgentRequest.cwd`/`add_dirs` mean anything (a hosted API has no local
  filesystem concept of "worktree") or whether the adapter has to synthesize
  an equivalent (upload/mount a workspace) — a materially different `run()`
  shape than Claude Code's.
- **Does ADK expose a "run to completion, get final text" call at all**, or
  only a session/turn-based conversational API abk would have to drive turn
  by turn to reach an equivalent of `-p`'s one-shot behavior?
- **Do any of the three have an equivalent of a shared, account-level usage
  window** (a subscription-style ceiling separate from raw token billing), or
  is `supports_usage_tracking = False` simply correct for all three, making
  the usage-guard step a Claude-Code-only concern in practice?
- **Does `profile.allowed_tools`'s Claude-Code-flavored syntax
  (`Bash(uv run *)`) need its own per-runtime translation**, or does every
  non-Claude-Code adapter simply not support tool-pattern scoping at all
  (falling back to the coarser allow/deny-by-tool-name split, if that)? This
  document treats it as unresolved, not blocking — see "Why."
- **Is workspace-level runtime selection (one runtime for the whole
  workspace) actually sufficient**, or will there be a real case for one repo
  building under Claude Code while another builds under ADK? Nothing today
  suggests it, but the `abk.yaml` shape above assumes not.
