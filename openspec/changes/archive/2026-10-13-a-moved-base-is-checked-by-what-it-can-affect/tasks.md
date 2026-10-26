# Tasks

Acceptance: none — a change to which tests tier 1 runs after a move; its scenarios are decided by a fake profile, a real temporary git repository with a moved base, a fake runner and the fake graph the tier 1 flake tests use, and nothing a consumer drives changes shape. The first live confirmation is the unit's own moved-base log line.

Priority: 2

## 1. [agent-build-kit] [tier1] A clean move is scoped by a rule, with a setting and a log line

Done when a moved base is classified as scoped or full by the stated rule, `limits.restack_check` selects between them, both paths that re-run tier 1 after a clean move carry the old base to the runner, and the log says which it was and why, with the selected run itself still the full suite until group 2.

- [x] 1.1 Test: `tests/test_config_restack_check.py` asserts `limits.restack_check` defaults to `affected`, accepts `full`, and refuses any other value and an unquoted boolean when the configuration loads.
- [x] 1.2 Test: `tests/pipeline/test_moved_base_scope.py` builds a temporary git repository with a branch and a moved base and asserts the rule: disjoint files are scoped; an incoming file the unit also changes is full with that reason; a unit that produced nothing is full; `full` in the setting is full whatever the files; the old base is the one the restack computed, and a move with no old base is full.
- [x] 1.3 Test: `tests/graph/test_verify_base_scope.py` drives `verify_base` and the `tier1` node with a fake runner and asserts a clean move passes the old base to `run_tier1`, a resolved or conflicting move goes to `rebase` and never reaches it, the `moved base: ...` line is logged with the reason when full, and a tier 2 unit still runs tier 2 after its tier 1.
- [x] 1.4 Test: `tests/pipeline/test_events_restack_scope.py` asserts the merge handler's clean move passes its `old_base` to the tier 1 callable, and that a changed diff or a resolution is still planned for review without running tier 1.
- [x] 1.5 Add `limits.restack_check`, the scope rule as a pure function over the own files, the incoming files and the setting, the `moved_from` field on the unit's run state set by `verify_base`, and the argument on `run_tier1` and the merge handler's tier 1 call. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 1.6 Document the rule and the setting in `docs/architecture.md` steps 6 and 8 (step 7 says tier 2 is unchanged) and `docs/configuration.md`, add the key to the `abk-config` skill's limits block, and add a changelog entry.

## 2. [agent-build-kit] [tier1] A scoped move runs the unit's own tests and the tests the profile names

Needs: affected-tests-in-fix-rounds group 2 — the Python profile's implementation of `affected_test_commands`, which this selection asks, and the seed data its first full run records

Done when a scoped moved base runs lint, the unit's own added and changed tests and the profile's affected tests for the unit's files together with the files the move brought in, falls back to the full suite whenever a profile cannot say, and the log shows the counts.

- [x] 2.1 Test: `tests/pipeline/test_moved_base_selection.py` uses a fake profile and asserts the commands run are lint, the repeat-style command for the unit's own test ids, and the commands the profile returns for the union of the unit's files and the incoming files, in that order, and that a clean move over disjoint files does not run the full test commands.
- [x] 2.2 Test: the same file asserts a move over a file the unit's code imports adds the tests that import it, using a fake profile that maps files to tests, and that the incoming files and the unit's files are passed as one list with no failed ids.
- [x] 2.3 Test: the same file asserts a semantic conflict with no textual overlap is caught: a temporary repository whose base changes a function's signature in one module and whose unit calls it from another, with a fake profile that selects the tests that import a changed module, fails the selected run and the unit is not pushed.
- [x] 2.4 Test: the same file asserts the full suite runs, with the reason in the log, for a profile returning nothing, for one returning nothing for a single project of several, for a command that cannot start, and for a profile without the hook.
- [x] 2.5 Test: the same file asserts the `moved base: ran 14 of 5963 tests (own 6, affected 8)` line from fake runner summaries, the line without `of <total>` when no earlier full count is on the state, and that an empty selection is a pass with zero tests that is logged as such, never silently.
- [x] 2.6 Test: `tests/profiles/test_python_uv_moved_base.py` asserts the Python profile returns nothing for a changed file it cannot place (a lock file, a configuration file, a shared test helper), so the full suite runs.
- [x] 2.7 Add the moved-base branch to `build_tier1` reusing `touched_tests`, `RepeatsTests.repeat_command`, `SelectsAffectedTests.affected_test_commands` and `parse_test_summary`; make the profile return nothing for a file it cannot place if group 2 of `affected-tests-in-fix-rounds` did not already; keep the last full run's test count on the run state. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 2.8 Document the selected run, the log line and the fallbacks in `docs/architecture.md` and `docs/toolchain-profiles.md`, and fold the entry into the group 1 changelog bullet.

## 3. [agent-build-kit] [tier1] A failure in a scoped run is isolated, and a flake does not hold the unit

Done when a failed scoped test is rerun alone, a flake is recorded without holding the unit, a repeated failure and a failure in a test the unit added hold it as today, and a full run keeps its flake rule.

- [x] 3.1 Test: `tests/pipeline/test_moved_base_flake.py` asserts a scoped test that fails and passes alone raises the flake, is recorded with its fix change, and the unit gains no `Needs:` line and is not parked, in the graph's `tier1` node and in the merge handler alike.
- [x] 3.2 Test: the same file asserts a test that fails again alone holds the unit as today (`rebase` with the output as feedback in the graph, an error from the merge handler), and a scoped test the unit added or changed that passes alone is held as a real failure.
- [x] 3.3 Test: the same file asserts the repeat of the unit's added tests runs on a scoped run over the same ids as on a full run, that a tier 2 command is never isolated or repeated, and that a full run on a moved base under `limits.restack_check: full` still parks the unit on its flake's fix as before.
- [x] 3.4 Test: `tests/pipeline/test_on_flake_wait.py` asserts `on_flake` with `wait` false records and ensures the one fix change and adds no `Needs:` line, that two units meeting the flake make one change, and that `wait` true behaves as today.
- [x] 3.5 Add the `wait` argument to `on_flake` and `wait_on_fix`, the classification of a scoped failure by the unit's own tests, and its handling in the `tier1` node and the merge handler. Confirm the places design.md marks UNVERIFIED and correct the design where the code says otherwise.
- [x] 3.6 Document the isolation and the no-hold rule in `docs/architecture.md` step 8 and the pipeline skill, and fold the entry into the changelog bullet.
