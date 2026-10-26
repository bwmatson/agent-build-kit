# Design

## The test and the code under it

The capper cuts any file past its limit to a marker and the last bytes. A capped file is the marker plus the limit's
worth of tail, which is over the limit, so an idle file is rewritten every pass. The cut becomes idempotent: it keeps
the limit minus the marker's length, and leaves alone a file that already starts with the marker and is within the
limit. The loop that runs it every interval signals after each pass, so a test waits on that signal instead of
polling the file's size. Today the loop is a closure (`enforce`) inside `run_folder` in `pipeline/scratch.py`, out of a test's
reach, so the pass becomes a function the loop calls and the signal is exposed by the folder's watcher, which is a
restructuring of `run_folder` and not only an added event.

The current test (`test_a_live_run_s_file_is_held_to_the_cap_even_while_its_writer_has_it_open`, which waited for a cut that a loaded run had not yet made and so failed a unit that did not touch it) starts the loop, writes through an open handle, and asserts a state the cut leaves for the next pass
to repair: a writer that opened the file with a plain redirect keeps its offset when the file is cut, its next write
leaves a hole of NUL bytes, and the next pass removes it. Reading in between sees the hole. The behaviour is by design
(a lossy view of long output that repairs itself), so the test was wrong. It is replaced by one test that calls the cut
directly between writes of an open handle and asserts the marker, the tail, and that the next call removes the hole,
with no thread and no sleep, and one test that only checks that the watcher runs, by waiting on the signal.

## Guards

A time limit on every test (sixty seconds, enforced from a thread, except a tier-2 test, which has its own, longer limit) makes a hang fail in a minute instead of holding the
run. A guard test scans the test tree and fails on a bare sleep, an unsynchronised thread, or a fixed port, except in
the shared helpers (a wait-for-condition helper, the fake servers) and in files on an allowlist that records today's
uses and may only shrink: a file leaves it when its uses are removed, and nothing may be added.

A time limit on each test does not cover a run that finishes its tests and then does not exit, as when a thread that nothing joins
keeps the interpreter alive, which held a pass for more than half an hour with every test passed. So every command unit-test runs
has a limit on the time it may take, configurable, with a default well over what the suite takes. When it is exceeded the
pipeline asks the process group to abort, so a language runtime that can dump the stacks of its threads does, waits a short
grace, and then ends it. The failure says which command timed out and after how long, and carries the end of its output with any
dump, so the unit's agent is told where it was waiting.

## Isolating a flake

The toolchain profile gains two optional hooks, built beside the red-check hooks (`red_command`, `interpret_red` and
`failure_kind` on the profile base) and reusing the pytest output parsing in `red_check.py` for the failed identifiers.
One reads the identifiers of the failed tests from unit-test's output. The
other builds the command to run just those, serially. A profile without them behaves as now. When a test failure is
found, the failed identifiers are run again, serially, twice. If any fails again, it is a real failure and the unit
fails as it does today. If all pass both times they are a flake. The rerun only classifies: it does not make a failure
a pass without a fix being owed.

A flake is appended to a record in the state directory with the test, the unit, the command, the first failure's output
and the time, and the status command lists each flaky test with the number of times and the change that fixes it.

## One fix change per test

The pipeline writes a change for the flake in the planning repository without a model: a proposal with the test, how it
failed, that it passed alone, its history from the record and the production module it exercises, found from what the
test imports; a design stub that asks whether the test or the code is racy; and one group, with its tests first, that
reproduces the race deterministically, makes the test pass, and runs it under the repeat check. The unit that builds it
decides whether to fix the test or the code, under the determinism guidance.

The change's name comes from the test's identifier. Making sure it exists is one step taken under the state directory's
lock: it looks for an open change for that identifier, creates one only if there is none, and returns its name. Every
unit that meets that flake, at the same time or later and in any change, waits on that one change through a `Needs:`
line; none writes a second. Two units flaking in one tick produce one change and two lines. Only when the earlier change
has been merged and archived and the test flakes again is a successor written, naming the earlier attempt in its
proposal, and any unit still waiting then waits on the successor. A unit that is the fix change itself does not wait on
itself; it relies on the repeat check.

## Waiting

The unit that met the flake is parked as planned with the cause gated, resuming at unit-test when the fix has merged, by
the mechanism that already holds a unit behind a `Needs:` line. When it resumes it is restacked and unit-test runs again.
The check that sends a unit back when unit-test fails on the base no longer applies to a flake.

## Tests that are added or changed

After unit-test passes, the tests a unit added or changed are run again several times (three by default) under the same
parallel load. Any failure fails unit-test with the output. A new test has no excuse to be flaky, so there is no
classification for it.

## What the agents are told

The prompt for writing tests and the reviewer's checklist for tests gain the same rules, in terms that do not name a
language: do not wait on the clock, inject the clock or the sleep, or wait on an event; do not start a thread nothing
joins or signals; bind to a free port, never a fixed one; do not share a temporary path between tests; do not assert a
state that a background actor repairs later; and code that runs on a timer or a thread exposes a step that a test calls
directly. A change that introduces such a use is a required finding with the consequence that the test passes alone and
fails under load.

## Decisions pending

- That the commit of the new change and the added `Needs:` line follow the path the archive step uses: the tick commits
  what it wrote.
- Whether a flake that occurs in a unit's own newly added test should also write a fix change; this design says no: the
  unit fails and its agent fixes the test.
