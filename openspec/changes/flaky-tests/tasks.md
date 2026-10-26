# Tasks

Acceptance: none — the tests use a real repository and faked test runs; tier-1 tests prove each behaviour.

## 1. [agent-build-kit] [unit-test] The capped output is deterministic, and tests cannot grow timing hazards

Done when the output cap is idempotent and driven by a step, the existing test no longer polls, and a guard and a time
limit stop new hazards.

- [x] 1.1 Test: the cut keeps the limit minus the marker's length of tail, leaves a file that begins with the marker
      and is within the limit unchanged, and removes the hole an open writer leaves on the next call.
- [x] 1.2 Test: the loop signals after each pass and a test waits on the signal; replace the polling test
      (`test_a_live_run_s_file_is_held_to_the_cap_even_while_its_writer_has_it_open` in
      `tests/pipeline/test_scratch_folder.py`, which fails under a loaded parallel run) with a
      synchronous test of the cut between writes of an open handle and a test that the watcher runs.
- [x] 1.3 Test: a test that exceeds the time limit fails with the limit named; the guard fails on a bare sleep,
      an unsynchronised thread or a fixed port in a file not on the allowlist, and fails again when a file whose uses are
      gone is still listed.
- [x] 1.4 Test: a unit-test command that does not finish within its limit is asked to abort, ended after the grace if it
      ignores that, and fails unit-test with a message naming the command and the time and the end of its output with any
      stack dump; a command that finishes in time is not signalled; the limit is configurable.
- [x] 1.5 Make the cut idempotent, restructure `run_folder` so the pass is a function and add the signal, replace the test, add the time limit, the limit on a command's run time and the
      guard with the allowlist of today's uses, and a shared wait-for-condition helper.
- [x] 1.6 Document the guard, the command limit and the helper in `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [unit-test] A flake is isolated, recorded, and fixed once by a change every blocked unit waits on

Priority: 2

Done when a flaky test no longer fails a unit, is recorded, and has exactly one fix change that all the units it blocks
wait on.

- [x] 2.1 Test: a failed test that passes two serial reruns is a flake and the unit does not fail; one that fails
      again fails the unit; a profile without the hooks behaves as before; the pytest hooks read the failed
      identifiers from recorded output and build the serial command.
- [x] 2.2 Test: a flake is recorded with its fields and the status command lists it with its count and fix change.
- [x] 2.3 Test: the fix change is written without a model with the proposal, design stub and group described, named
      from the test's identifier, and passes `abk check` and `abk tags`.
- [x] 2.4 Test: two units meeting the same flake in one tick produce one change and two `Needs:` lines; a later unit
      gains the line and writes nothing; after the fix merged and archived a successor is written; the fix change's own
      unit does not wait on itself.
- [x] 2.5 Test: the unit that met the flake is parked gated, resumes at unit-test restacked when the fix merges, and a flake
      on the base no longer sends a unit back as a moved base.
- [x] 2.6 Add the profile hooks (beside `red_command`, `interpret_red` and `failure_kind`, reusing `red_check.py`'s
      pytest parsing) and the rerun, the record and status line, the locked ensure-the-change step and its
      template, the added `Needs:` line, the parking and the base-check exception.
- [x] 2.7 Document the flow in `docs/architecture.md` and the pipeline skill, and add a changelog entry.

## 3. [agent-build-kit] [unit-test] New tests are checked for flakiness, and the agents know the rules

Needs: dry-guidance group 2 merged — both edit the review prompt
Priority: 2

Done when the tests a unit adds are run repeatedly under load before review and the prompts carry the determinism rules.

- [x] 3.1 Test: after unit-test passes, the tests the unit added or changed are run three times under load; a failure in
      any run fails unit-test with its output; tests the unit did not touch are not run again.
- [x] 3.2 Test: the prompt for writing tests and the reviewer's checklist carry the determinism rules, name no language
      or tool, and say that a violation a change introduces is a required finding with its consequence.
- [x] 3.3 Add the repeat check, its setting, and the prompt text.
- [x] 3.4 Document the check and the rules in `docs/architecture.md` and add a changelog entry.
