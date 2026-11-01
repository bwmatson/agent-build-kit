# Proposal

## Why

A test that passes alone and fails under load cost a unit a rebuild: unit-test failed during the full parallel run, the
failure was read as the base being broken, and the unit was sent back to planned. The test starts a background thread
that cuts a file, writes to the file through an open handle, waits by polling, and asserts a state the production code
repairs only on its next pass. The same kind of test has been fixed before, each time by waiting longer or tolerating
the failure: process-exit tests racing a kernel listing, a real network call in a tick test, a five-second wait that was
too short, and this same test once already. Nothing stops the next one.

A unit that meets a flake it did not cause has two bad choices: fail on something unrelated, or pass on a lucky rerun
and leave the flake for the next unit.

## What Changes

- **The test in question is made deterministic,** and the code it exercises is made idempotent with a step the test can
  call, so nothing in it waits or polls.
- **Tests cannot grow new timing hazards unnoticed:** a hang fails fast under a time limit, and a guard fails if a test
  uses a bare sleep or an unsynchronised thread or a fixed port, with today's uses listed as a baseline that may only
  shrink.
- **A flake is isolated:** when unit-test fails, the failed tests alone are run again serially, twice. A test that fails
  again is a real failure. A test that passes both times is a flake: it is recorded, and the unit does not fail for it.
- **A flake gets one fix specification:** the pipeline writes a change to make that test deterministic, once per test,
  and every unit that meets the flake waits on that change before it continues. A flake is never allowed to pass
  without a fix owed.
- **New tests are checked for flakiness before review:** the tests a unit adds or changes are run several times under
  load, and any failure fails the unit.
- **The agents are told what makes a test deterministic,** and a violation a change introduces is a required finding.

## Impact

- agent-build-kit: the output-capping code and its test, test configuration and a guard, the unit-test result and the
  toolchain profile, a record and a status line, the writing of a fix change and the gating of waiting units, the
  test-writing and review prompts, and docs. A separate change, `flaky-cleanup`, removes the existing hazards.
