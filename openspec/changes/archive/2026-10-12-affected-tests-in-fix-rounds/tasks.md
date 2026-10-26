# Tasks

Acceptance: none — the tests use faked test runs and a real repository; tier-1 tests prove each behaviour.

## 1. [agent-build-kit] [tier1] A profile or a command names the tests a fix round runs, and the full suite confirms

Needs: flaky-tests group 1 merged — both change the tier 1 command runner and the failure text it returns
Needs: flaky-tests group 2 merged — the failed-test identifiers the command template and the profile fallback read

Done when, with the mode on, a fix round runs the selected tests, a pass is confirmed by one full run, a failure goes back
to the fixer, and with the mode off nothing differs.

- [x] 1.1 Test: mode `off` runs the full tests in every check as today; `profile` with a profile that returns nothing
      runs the full suite and logs one line saying why; `command` with no template is rejected when the configuration loads.
- [x] 1.2 Test: the template's `{changed_files}` and `{failed_ids}` are each expanded to separate quoted arguments, and
      the command runs in the project directory under the tier 1 command time limit.
- [x] 1.3 Test: after a failed check and a fix, the check runs lint in full and the selected tests; when they fail the
      unit returns to the fixer and the full suite does not run; when they pass the full suite runs once.
- [x] 1.4 Test: a selected pass followed by a full failure counts as a disagreement and returns the unit to the fixer
      with the full output; a selected pass followed by a full pass is the unit's green; a selected pass alone never is,
      and the check cache records only full results.
- [x] 1.5 Test: the first check, the check of a unit that has not failed, the `tier1` node, and the gate before review
      and push run in full; a selected command that cannot run falls back to the full suite and records why.
- [x] 1.6 Add the optional profile hook, the repo's `checks.affected` configuration, and the selected-then-full flow in
      the tier 1 runner and the `checks` and `fix_checks` nodes.
- [x] 1.7 Document the hook and the configuration in `docs/toolchain-profiles.md` and `docs/configuration.md`, and add a
      changelog entry.

## 2. [agent-build-kit] [tier1] The Python profile selects by coverage, falls back to the failed tests, and each run is measured

Done when the Python profile returns affected tests, a repo can turn the mode on, and every selected run leaves a record.

- [x] 2.1 Test: with the plugin's seed data present, the profile's command selects tests by changed source and adds the
      plugin to the isolated environment; with no seed data or no plugin it returns the failed identifiers first and
      alone; with no identifiers it returns nothing so the full suite runs.
- [x] 2.2 Test: the first full run in a unit records the seed data in the unit's worktree, and a rebuilt worktree falls
      back without failing.
- [x] 2.3 Test: each selected run writes one ledger line with the selected and total counts, the estimated seconds saved
      (never negative, absent without a full run to compare with) and the outcome of the confirming run; an unwritable
      ledger does not fail the run.
- [x] 2.4 Add the Python implementation, the recording on the first full run, and the ledger line.
- [x] 2.5 Document the Python selection, its fallback and the ledger line in `docs/toolchain-profiles.md` and
      `docs/architecture.md`, and add a changelog entry.
