# Proposal

## Why

`abk init` never asks which runtime to use. The drafted `abk.yaml` has no `runtime:` key, so the configuration
default applies, and init's own research and propose steps run on whatever runtime is active — the default, on a
machine where nothing has been chosen. On a machine without that default's program the steps fail, and the file is
written for a runtime that may not exist. The first sign is a failure, or a later `abk doctor` line, for a choice
nobody made.

Meanwhile the facts that decide the choice are cheap to learn: whether a program is on the path, whether the optional
library is installed, what a help text says, and — for an agent speaking the Agent Client Protocol — which models it
advertises when a session opens, none of which needs a model.

## What Changes

- **A probe, no model call.** Each runtime can report the candidates it finds on this machine: the command, whether
  it is usable, and the reason when it is not. A table of known protocol agents (data, in the ACP runtime's module)
  says how each is started, what it needs, and how far its entry is verified.
- **`abk init` asks.** After detecting repos and before any step that runs an agent: show the candidates, ask which,
  ask that runtime's own questions (a hook on the runtime, so a new runtime needs no change to init), offer the
  guided policy step, show the resulting `abk.yaml` fragment and write only on confirmation. The chosen runtime is
  passed explicitly to research and propose.
- **Models from what costs nothing.** A runtime that can list models without a model call offers them with the
  agent's current one as default; one that cannot says so and leaves roles empty.
- **Non-interactive routes** that produce the same fragment: `--runtime`, `--agent-command`, repeatable `--set`,
  `--runtime-config FILE`, `--dry-run`, and `--yes` that refuses to guess between several usable runtimes.
- **`abk doctor` shares the probe**: other usable runtimes on this machine, and a selected entry that is only
  documented, not verified.
- **A policy fix on an existing installation.** `abk init --policy-only` runs just the policy step against the
  installation's `abk.yaml` (no detection, research or propose), `--policy-fix ARGV` supplies and records the fix
  command, and the step shows the fix and the unrefused classes first, runs it with output visible, re-checks, prints
  per class and spelling what is now refused, and exits 0, 1 or 2. `--yes` runs a configured fix only when
  `--policy-fix` or `--run-policy-fix` is given. This change is priority 1: the person needs the flow to apply a
  policy fix and test it end to end.
- **An acceptance run** of the real `abk init` as a subprocess against a stub agent that fails the test on any prompt.

Not included: installing an agent or the optional library for the person (init prints the exact command), and
probing whether an agent's credentials work (that needs a model call; the policy check or the first unit finds it).

## Impact

- **agent-build-kit** only: `runtimes/` (the hooks, the table), `init/` and `cli/init.py`, `cli/doctor.py`, the
  configuration schema (a policy marker on a runtime's entry), `docs/cli.md`, `docs/agent-runtimes.md`, the changelog.
- No contract with another repo. An existing `abk.yaml` loads unchanged.
