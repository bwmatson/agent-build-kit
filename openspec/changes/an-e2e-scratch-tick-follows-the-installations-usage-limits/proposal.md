# Proposal

## Why

E2e-test tests that start a real `abk tick` in a scratch installation (the build test, the graph test, the telemetry test; their scratch is made by
`tests/runtime_scratch.py` and `tests/live_build.py`) failed because the inner tick printed `pausing until HH:MM — session usage at 91%
(threshold 70%, live)` and `nothing ready to build`. The unit was never built and the assertion failed on a missing branch, far from the cause.

How the scratch is made, on origin/main and in the open build-test work:

- `runtime_scratch("claude_code", ...)` returns `runtimes_yaml=""`, so the scratch `abk.yaml` has no `runtimes.claude_code.limits` and the inner tick
  uses the defaults (`usage_pause_pct` 70 for the session and the week). The live pipeline's `abk.yaml` sets 95 and 90, but the tests run in a
  repo checkout under the outer `abk`, which exports no path to its own configuration to them (`ABK_CONFIG` is the scratch's, set by the test), so
  nothing of the installation's reaches the scratch.
- The tests assert the build (the branch, its commits, the run log, the telemetry); none of them asserts the usage guard. The outer pipeline has
  already decided to spend the usage on the run, with its own thresholds, before the test starts.
- A failed test is attributed as follows: the run is repeated on the base for the untouched tests, a test that also fails there is `pre_existing`
  and holds other units behind a fix change, and a test that fails with the unit is sent to the agent as feedback to rework the code. A usage pause
  fails on the base exactly as it does with the unit, so as a failure it would hold units behind a defect that does not exist or send the agent to
  rework correct code.

## What Changes

- **A scratch tick of a test that is not about the guard skips the usage guard.** A per-machine setting `ABK_USAGE_GUARD`, `on` by default and
  never read from `abk.yaml`, turns the guard off for the process that has it set: `abk tick` takes no usage reading, applies no threshold, allowance
  or estimate, and never pauses for usage. The tick says so on its first line, and `abk status` shows it. The scratch setup of the Claude Code
  runtime sets it for the tick it starts. Inheriting the installation's numbers was weighed and not chosen (design.md).
- **A test that is about the guard opts in.** The scratch setup takes `usage_guard=True`, which leaves the setting off the environment so the scratch's
  own limits (written by that test) apply.
- **Usage is an environment condition, and the test skips.** After a scratch tick that built nothing, if the scratch's pause marker holds a usage or
  rate-limit pause, the test is skipped with a reason that names the reading and threshold (or the limit message) and says the build was not
  attempted. It is never a failure and never a silent `nothing ready to build`.
- The documents say all of this.

## Impact

- agent-build-kit: `settings.py` (the new setting), `pipeline/usage_guard.py` (`decide_start` returns "go" with no reading when off),
  `cli/pipeline.py` (the tick's first line and `abk status`), `tests/runtime_scratch.py`, `tests/live_build.py`,
  `tests/integration/test_telemetry_stack.py` (its tick helper), `docs/cli.md`, `docs/configuration.md`, the `abk-pipeline` skill.
- Builds on `tier2-tests-are-tagged-by-runtime`: group 15 creates `tests/live_build.py` and group 17 gives the telemetry test the shared scratch. Only the
  group that skips on a pause waits for them.
- Priority 2: e2e-test runs of the Claude Code variants cannot be trusted until this lands.
