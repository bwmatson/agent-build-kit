# Proposal

## Why

Every test runs under a sixty-second limit, on each of its setup, call and teardown. That is right for the fast suite, where a hang should
fail in a minute. It also applies to the tier-2 tests, the live-stack acceptance runs, which build a unit through a real agent, tick the
pipeline as a process, and read results back from the stores. Each takes minutes, and a module-scoped fixture that runs a tick takes
minutes too. Since the limit was added, every unit that reached tier 2 failed with one test failure and a column of setup errors, all
reading "test exceeded the time limit of 60 seconds", in tests the unit had not touched. Before the limit those runs took fifteen to
twenty-three minutes and passed. Two units are failed on it now, and every later unit will be.

## What Changes

- **A tier-2 test has its own limit.** A test carrying the tier-2 marker runs under a separate limit, thirty minutes by default, set by its own
  option; zero turns it off. Every other test keeps the sixty seconds.
- **The limit named in a failure says which one it was,** so a tier-2 test that does hang is told apart from a fast test that does.
- **Nothing changes in how the pipeline runs tier 2:** the command and its environment are as before.

## Impact

- agent-build-kit: the time-limit plugin and its tests, the documentation of the test markers, and the changelog.
