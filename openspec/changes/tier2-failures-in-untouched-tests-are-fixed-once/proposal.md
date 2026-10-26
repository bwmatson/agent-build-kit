# Proposal

## Why

A unit failed e2e-test on four tests in a file it did not change, after a run of nearly fifty minutes. E2e-test runs the repo's whole live-stack marker
on the unit's branch, and any failed test fails the unit; nothing asks whether the same test fails on the base. The cost has three parts. The unit
is failed, or sent back to rework, for a fault that is not in its diff. The stored output of those tests is appended to the unit's feedback, so a
rework agent is told to repair tests it did not write. And the fault itself has no owner: the next unit meets it again, pays the same fifty
minutes, and fails the same way.

Unit-test already handles the equivalent case for a flaky test (`flaky-tests`): the failed tests are run again alone, a flake is recorded, one change is
written per test, and every unit that met it waits on that change. E2e-test has none of it. An e2e-test failure is also not a flake to be rerun: a run
costs tens of minutes, so the question has to be answered with one run of only the failed tests, on the base, once.

## What Changes

- **Each failed e2e-test test is classified.** A test whose file the unit added or changed is the unit's own, and the unit fails as today. A test it left
  alone is run once, alone, on the base in a clean worktree. Failing there too, it is pre-existing and charged to the base. Passing there, the unit
  broke it, and the unit fails as today; a unit is never parked behind a fix for a failure its own change caused.
- **One base run, never repeated.** E2e-test tests are not repeated or flake-isolated by the unit-test mechanisms, and a test says so. A setting turns the
  base run off, and the unit then fails as today.
- **A pre-existing failure is recorded and fixed once.** The record keeps the test id, unit, command, first failure line, time and the base run's
  result, and `abk status` lists each test with its fix change. One fix change is written per test id, without a model. Making sure it exists takes
  the state directory's lock and previews first, reporting `exists: <change>` or `would write: <change>`; `abk tick --dry-run` prints the same
  without writing.
- **The unit waits and resumes at e2e-test.** It is parked gated on the fix change through a `Needs:` line and resumes at e2e-test when it merges. Two
  units meeting one failure make one change and two lines. The fix change's own unit does not wait on itself.
- **Feedback stays the unit's.** The feedback saved when a unit fails e2e-test holds only the failures that are the unit's, not the output of untouched
  tests.

## Impact

- agent-build-kit: the e2e-test session and node, a clean base worktree for one run, the classification, a setting, a record and a status line, the
  fix change's writer with its preview, a line in the dry-run tick, the parking and resume, the feedback text, docs and changelog.
- It reads the failed test ids of `acceptance-server-runs-in-the-scratch-environment` group 3 (`E2eResult.failures`), so its first group waits for
  that group to merge. It does not touch the lock wait (`e2e-lock-wait-*`) or the per-test time (`tier2-time-is-recorded-per-test`).
