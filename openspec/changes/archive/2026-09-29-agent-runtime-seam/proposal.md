# Proposal

## Why

agent-build-kit can only talk to one agent, and not because of a decision — it
is an accident of growth. Seven call sites each assemble their own `claude -p`
argv, in three mutually incompatible callable shapes, with three different
answers to "what does a refusal look like":

- `pipeline/wiring.py` streams and interprets refusals; `pipeline/planner.py`
  runs its own `subprocess.run` with no cwd and no tool policy;
  `pipeline/restack.py` runs one with **no refusal handling at all**, so a
  conflict-resolution run that was rate-limited looks identical to one that
  found nothing to do.
- `tracks/runner.py` builds a fourth argv shape and is not injectable for
  tests: its tests monkeypatch a module attribute.
- `init/research.py` and `init/propose.py` share a low-level executor that the
  two pipeline sites do not use.

So there is no single place that knows how to run an agent, which means there
is nowhere to change it. Any second runtime today is a fifth argv builder.

There is also a concrete reason to want a second one: an agent reached over the
Agent Client Protocol is billed on demand rather than against a usage window
shared with the operator's own sessions, which is the thing that pauses the
pipeline most often today.

## What Changes

- **An `AgentRuntime` Protocol and registry** (`runtimes/`), mirroring the
  `forges/` and `profiles/` packages this repo already has: a
  `typing.Protocol`, `Frozen` value objects for a request and a result, an
  `implemented` flag, and a registry filled in-process.
- **A `claude_code` adapter** that absorbs the existing subprocess logic — the
  streaming, the `PreToolUse` hook registration, the tool allow/deny
  composition, the usage reading and the refusal interpretation — with **zero
  behaviour change**: same binary, same flags, same semantics.
- **Every call site goes through it**, including the two that are not
  injectable today, and `planner`/`restack` gain the refusal interpretation
  they lack.
- **`runtime` and an optional `runtimes` mapping in `abk.yaml`**, plus an
  `ABK_RUNTIME` per-machine override. An existing `abk.yaml` needs no edit:
  `runtime` defaults to `claude_code` and the flat `models:` block keeps
  meaning "the active runtime's models".
- **`abk doctor` learns to check the runtime at all** — it checks nothing
  runtime-related today, not even that the agent binary exists — and both
  `doctor` and `abk init` learn to ask a runtime whether the commands the
  pipeline forbids are actually refused.

Out of scope, deliberately: any second adapter, and any change to which
runtime an installation uses. `runtime` stays `claude_code` after this change.

## Impact

- **agent-build-kit** only. No other repo, no contract between repos.
- The pipeline's observable behaviour is unchanged, which is the acceptance
  criterion rather than a side note: the existing argv-shape tests must pass
  without being rewritten.
