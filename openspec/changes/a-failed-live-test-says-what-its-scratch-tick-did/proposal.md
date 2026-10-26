# Proposal

## Why

An e2e-test (e2e-test) live test that starts a real scratch tick failed far from its cause and left nothing to read. The case: unit
`tier2-tests-are-tagged-by-runtime/16`. Its saved e2e log shows the graph test failing in 2.0 s with
`CalledProcessError: git log main..spec/add-marker/1 exit 128` at `commits_on_branch(scratch)`. The fixture unit's branch did not exist, no agent
call was made, and the log holds no tick output at all, so a usage pause, a planning failure, `nothing ready to build` and a lease are
indistinguishable. Three things made that so:

- The tick output lives only in memory. Each live test file has its own result type and its own tick function (`Ticked` in
  `tests/integration/test_graph_unit.py` with output only; in `test_build_unit.py` with timestamped lines; in `test_telemetry_stack.py` with a
  `pushed` flag), and each decides for itself which assertions print it. The graph test runs `commits_on_branch` bare, so the error fires before
  the next assertion could print the output. The guarded `pushed_commits` that fails with the tick output, the run log and who pushed exists only in
  the build test's open work.
- The product says too little. A tick that builds nothing prints a bare `nothing ready to build`. Per-unit reasons exist (`WaitReason`,
  `wait_reasons`, the decision log) but only the decision log file receives them.
- The saved log is the outer pytest's output alone. The scratch state (planning and app repos, the bare remote, the state directory with
  `runs/units.json`, `paused.json`, `decisions.jsonl`, the usage ledger, the leases, the fake host's calls) lives under pytest's temp directory
  and is lost. Nothing of it is copied.

## What Changes

- **A tick that builds nothing says why, per unit.** After the unchanged first line `nothing ready to build`, one line per candidate unit gives its
  wait reason and what it waits on, bounded to 10 units with a `(+M more)` tail. A usage pause still prints its pause line, and the deadlock and
  full-queue reports are unchanged.
- **Live tests share one tick helper.** One module under `tests/` runs `abk tick` as a process and returns the return code, the lines with their
  times and the scratch environment's summary (names and non-secret values). It also holds the guarded check of the unit's branch: a branch that is
  missing fails with the full tick output, the per-unit reasons, the run log tail and the pause marker. It replaces the bare `commits_on_branch` and
  generalises the build test's `pushed_commits`.
- **A failed live test prints the scratch state.** A pytest plugin adds a `SCRATCH STATE` section to the report of any failed or errored live test
  that has a scratch installation: the last tick's output, the per-unit reasons, a summary of `units.json`, `paused.json`, the lease holders, the
  remote's heads and the app repo's branches, the tails of the decision log and the usage ledger, the fake host's recorded calls and the tick
  environment. It is bounded, redacted, best-effort, and kept nowhere but in the test's own output, so the e2e log and the e2e-test result carry it.
  A one-line cause hint opens it.
- **The graph, build and telemetry live tests use the shared helpers**, so no assertion about a tick or a branch is left without the tick's output.
- The documents say how a live test is written and what a failure now prints.

## Impact

- agent-build-kit: `cli/pipeline.py` (`_nothing_started_reason` and its caller), a new `tests/scratch_tick.py`, a new plugin `tests/scratch_dump.py`
  listed in `tests/conftest.py`, `tests/integration/test_graph_unit.py`, `test_build_unit.py`, `test_telemetry_stack.py`, `docs/architecture.md`,
  `docs/cli.md`, `AGENTS.md`, `CHANGELOG.md`.
- Specs: `unit-scheduling` (the tick's report), `test-tiers` (what live tests share and print), `run-logs` (a failure is diagnosable from the saved log).
- Priority 1: an e2e-test failure with no cause costs a whole run and sends units back to rework, and the faults it hides sit in the pipeline itself.

## Not included

Keeping the scratch state on disk or copying it out, and a retention setting for it (decided against: the bounded dump in the output is
enough); the usage guard of a scratch tick and the skip on a usage pause (`an-e2e-scratch-tick-follows-the-installations-usage-limits`); the ACP
tests' use of the graph log; the time split per test; changing which units a pass starts.
