# Tasks

Acceptance: none — classification, the base run, the record, the fix change, its preview, the park and the feedback are decided by recorded pytest output, a fake runner, a temporary git repository and planning directory and the fake graph the unit-test flake tests use; the first real e2e-test failure in an untouched test is the live confirmation, and the unit's own e2e-test run is where the fix change is checked.

Priority: 1

## 1. [agent-build-kit] [unit-test] A failed e2e-test test is classified, and the untouched ones are run once on the base

Needs: acceptance-server-runs-in-the-scratch-environment group 3 merged — the failed test ids and their first failure lines come from `E2eResult.failures` and the profile's `parse_test_failures`, and both groups edit `E2eSession.run` and the snapshot

Done when a failed e2e-test run classifies each failed test as the unit's own or untouched, runs the untouched ones once on the base in a clean worktree inside the unit's stack hold, and names each as pre-existing or broken by the unit, with a setting that turns the base run off and a test that pins that e2e-test tests are not repeated.

- [x] 1.1 Test: `tests/pipeline/test_e2e_classify.py` feeds `E2eResult.failures` and a temporary git repository to the classifier and asserts a failure in a file the branch changed is the unit's own with nothing run, one in an untouched file is untouched, a failure in a test file beside a changed `conftest.py` is the unit's own, and a failure with no readable ids, a profile without the hook, and a dev stack run classify nothing.
- [x] 1.2 Test: `tests/pipeline/test_e2e_base_run.py` runs the base step with a fake runner and asserts a test named as failed or errored by the base output is pre-existing, one that passes is broken by the unit, and one the base does not contain or does not name is broken by the unit; that three untouched ids make one command built by `serial_rerun_command` and run once; and that a unit with one test of its own and one pre-existing is not parked and gains no `Needs:` line.
- [x] 1.3 Test: the same file asserts the base run happens in a detached temporary worktree at the ref the unit's e2e-test ran against, that the worktree is removed when the run raises and the unit's own tree is unchanged, and that the stack lock is taken once for the unit's run and the base run together.
- [x] 1.4 Test: `tests/pipeline/test_e2e_not_repeated.py` asserts with the repeat setting at three that a failing e2e-test command runs once on the unit's tree, that no e2e-test command is among the commands unit-test repeats, and that `isolate` is not called for an e2e-test command.
- [x] 1.5 Test: `tests/test_config_e2e_base_runs.py` asserts `limits.e2e_base_runs` defaults to 1, accepts 0, refuses 2 and a negative value, and that at 0 no base run is made and the unit fails as today.
- [x] 1.6 Add the classifier and the base step to `E2eSession` (a method the node calls after a failed run, inside the same stack hold), the clean worktree helper, the verdict model, and `limits.e2e_base_runs`. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 1.7 Document the classification, the base run and the setting in `docs/architecture.md` and `docs/configuration.md` (beside `unit_test_repeat_runs`), and add a changelog entry.

## 2. [agent-build-kit] [unit-test] A pre-existing failure is recorded and gets one fix change, previewed before it is written

Done when each pre-existing failure is recorded and listed by `abk status`, one fix change per test id is written without a model after a preview that reports `exists:` or `would write:`, and `abk tick --dry-run` prints the same lines and writes nothing.

- [x] 2.1 Test: `tests/pipeline/test_untouched_failures_record.py` asserts a pre-existing failure appends an entry with the test, unit, command, first failure line, time and base result, that the same test met by two units counts twice, and that `abk status` lists the test once with its count and fix change.
- [x] 2.2 Test: `tests/pipeline/test_untouched_failures_change.py` asserts the change written for an id has the proposal, design stub and one e2e-test group with its tests first, `Priority: 1` and an acceptance opt-out, is named from the id with the `fix-failing` prefix and the hash cap, passes `abk check` and `abk tags`, and is a different change from the flake fix of the same test.
- [x] 2.3 Test: the same file asserts the ensure step reports `would write: <change>` before it writes and `exists: <change>` when one is open and writes nothing, that two ids are previewed and written independently, and that the step takes the lock so two calls in one tick write one change.
- [x] 2.4 Test: the same file asserts a successor is written, naming the earlier attempt and restating the spec as MODIFIED, only after the earlier change is merged and archived and the test fails again, and that no successor is written while the first is open.
- [x] 2.5 Test: `tests/cli/test_tick_dry_run_preview.py` asserts `abk tick --dry-run` prints `exists: <change>` for a recorded failure with an open change and `would write: <successor>` for one whose change was archived, and that the planning directory, the record and the unit store are byte-identical afterwards and no base run is made.
- [x] 2.6 Test: `tests/pipeline/test_fix_change_priority.py` asserts the change written for a pre-existing failure and the change written for a flaky test each carry `Priority: 1` on their group, and that no other line of the flake's change template changes.
- [x] 2.7 Add `pipeline/untouched_failures.py` with the model, the record and the ensure step with its preview; generalize `flake_change_name`, `_candidates` and `_add_needs`'s reason text by an argument in `pipeline/flakes.py` without changing a flake's name or line; add the status line and the dry-run lines in `cli/pipeline.py`. Change the `Priority` line the flake fix change is written with from 2 to 1 (`_tasks` in `pipeline/flakes.py`).
- [x] 2.8 Document the record, the change and the preview in `docs/architecture.md` and the pipeline skill, and add a changelog entry.

## 3. [agent-build-kit] [unit-test] A unit behind a fix waits on it, resumes at e2e-test, and is not told about tests it did not touch

Done when a unit whose every e2e-test failure is pre-existing is parked gated on the fix changes and resumes at e2e-test when they merge, the fix change's own unit does not wait on itself, and the feedback saved on a failure holds only the unit's own failures.

- [x] 3.1 Test: `tests/graph/test_e2e_waits_for_fix.py` drives the node with a fake runner whose failures are all pre-existing and asserts each group of the unit gains a `Needs:` line on the fix change, the unit is parked as planned with cause gated and a resume requeue, and a note naming the tests, not failed.
- [x] 3.2 Test: the same file asserts two units meeting one failure in one tick make one change and two lines, a later unit gains a line and writes nothing, and the unit of the fix change itself gains no line and fails as today.
- [x] 3.3 Test: the same file asserts a unit with a failure broken by it or of its own is failed as today and never gains a `Needs:` line, and that a base run that passes never parks a unit.
- [x] 3.4 Test: `tests/pipeline/test_e2e_resume.py` asserts a gated unit is released when the fix change's group merges, is restacked, and runs e2e-test again in full, and that the restack's unit-test path is unchanged.
- [x] 3.5 Test: `tests/graph/test_e2e_feedback.py` asserts a mixed failure saves the unit's own output and names the pre-existing tests once as recorded, that an unclassified failure saves the text saved today, that a person's own words stay and no untouched test's output is added to them, and that the rework prompt made from the saved text holds none of an untouched test's output.
- [x] 3.6 Add the park in `graph/nodes.py` `e2e-test` (the hold and resume requeue of `wait_for_fix`, reused), the runner callable that records and ensures the change (beside `build_on_flake`), the feedback text, and the `Needs:` reason for a base failure. Confirm that the resumed thread lands on e2e-test and correct the design where the code says otherwise.
- [x] 3.7 Document the wait, the resume and the feedback in `docs/architecture.md` and the pipeline skill, and add a changelog entry.
