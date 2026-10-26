# Proposal

## Why

The whole suite runs in one process. Measured on a 24-core host, a run of
`agent-build-kit`'s ~2,300 tests takes about 90 seconds: about 73 seconds in
test bodies and 18 in setup, across ~1,900 of them. The slowest single test
takes 1.5 seconds, so the cost is the count, not any one test. The same suite
with `pytest-xdist` and eight or more workers passed in about 21 seconds, twice.

The pipeline runs tier 1 before every review round and again before each push,
so the suite's duration is paid several times per unit, in the usage window's
wall-clock and as a person waits.

## What Changes

- **A parallel runner is part of the dev toolchain.** `pytest-xdist` joins the
  dev dependencies, and the whole-suite command runs it across workers.
- **Safe by construction.** Tests that share a resource (a port, a lock file, the
  real home directory, a shared fixture repository) are found and isolated, so
  parallel runs are as reliable as serial ones. A test that cannot run beside
  others is marked and run serially.
- **A single test file stays simple.** A bare `pytest <file>` is not made to
  spawn workers; the parallel run is the whole-suite command and CI.
- **The tiers keep their meaning.** Tier 2 (`local_stack`) stays serial, since
  it drives a real agent on the host and is serialized on purpose.
- **The profile knows the command.** The python profile's test command gains
  the workers flag, so what a unit's tier 1 runs is what a developer runs.
