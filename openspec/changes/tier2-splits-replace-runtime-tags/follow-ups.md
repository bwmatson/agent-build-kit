## From `tier2-splits-replace-runtime-tags/1`

- `_e2e_splits_declared_well` repeats the loop in `_e2e_runtime_lists` that gathers the top-level setting plus each repo's own. The duplication goes away when group 9 deletes the runtime lists; if it does not, extract one helper that yields (setting, value) for the top level and each repo.
- Group 11 should fold this changelog bullet into its own, so the change ends up as one bullet, and document `tests.e2e_splits` in docs/configuration.md and the abk-config skill. This unit adds neither.
- src/agent_build_kit/config.py:613 — Two near-identical models were added: `E2eSplitEntry` (`marker`, `hold`) and `E2eSplit` (`name`, `marker`, `hold`). Task 1.3 asked for one `SplitConfig`.
- src/agent_build_kit/config.py:1106 — A `marker` is only checked for being non-empty, so text like `runtime_acp or slow` or ` ` loads.
- src/agent_build_kit/config.py:608 — `REST_SPLIT` sits above `E2eSplitEntry`, about 40 lines from `BASE_GROUP` (line 650). Task 1.3 asked for it beside `BASE_GROUP`.
- tests/config/test_e2e_splits_config.py:65 — The last assertion in `test_config_show_prints_both_splits` checks split order through `names(config(TWO))`. That has nothing to do with `--show`, and `test_two_splits_are_given_in_declaration_order_then_rest_with_their_markers` already covers it.

## From `tier2-splits-replace-runtime-tags/2`

- src/agent_build_kit/pipeline/wiring.py:2406 — This belongs to group 6 and does not block this unit. When every split is held, `scope()` returns early with an OWN scope and no runs, before `_park` gets to list anything. `run` then reports `ok=True`, `ran_no_tests=True` and `parked=[]`, and `test_with_every_split_held_nothing_runs_and_no_expression_is_built` pins that outcome.
- src/agent_build_kit/pipeline/wiring.py:2425 — This belongs to group 8 and does not block this unit. `E2eSession.runtimes()` still builds the groups a run executes from `known_runtime_names(active().runtimes)` rather than from `self._splits`, and `_groups` still falls back to `BASE_GROUP` rather than `rest`.

## From `tier2-splits-replace-runtime-tags/4`

- Some test names and parameters in tests/pipeline/test_e2e_gate_wiring.py and test_e2e_blocked_wiring.py still use the old 'blocked' wording: `blocked_in_config`, `blocked_in_file`, and `test_the_runner_reports_the_blocks_of_the_configuration_and_the_file`. The same goes for `Run.blocked` in tests/graph/test_e2e_runtime_park.py and `E2eSession(blocked=...)`. They could be renamed to 'held' when group 6 rewires E2eSession to held splits.

## From `tier2-splits-replace-runtime-tags/3`

- Two small wrappers now place an e2e-test listing in a project directory under the verify env: `_run_in` in cli/e2e_cmd.py, which forwards the caller's kwargs, and `E2eSession._lister`, which drops them because `wiring._run` adds capture and text itself. If a third caller appears, fold them into one helper in pipeline/wiring that always forwards the kwargs.

## From `tier2-splits-replace-runtime-tags/9`

- Record in the change's follow-ups (under 9.5, or in groups 6 and 8) that `BASE_GROUP` and `known_runtime_names` in config.py go away once wiring.py and untouched_failures.py stop using them. The builder could not edit the change's files. This is the open part of optional point 1.3 from round 1.

## From `tier2-splits-replace-runtime-tags/6`

- Three tests carried over from the base still say 'blocked': test_the_groups_a_run_executes_leave_out_the_blocked_runtimes, test_the_groups_a_run_executes_are_every_one_when_nothing_is_blocked and test_a_call_limited_to_a_group_that_is_still_blocked_parks_it_without_running_or_locking. The same goes for the group-based `only` parameter of E2eSession.run. Rename them to 'held' and 'split' when task group 7 moves resume onto splits.

## From `tier2-splits-replace-runtime-tags/7`

- src/agent_build_kit/graph/unit.py:280 — This comment still says a unit is "parked for a blocked runtime". `awaits_release` now checks `Cause.SPLIT_HELD`, so the wording is stale.
- tests/cli/test_runtime_blocked_unit_not_started.py:1 — This file was edited to use `Cause.SPLIT_HELD` and `parked_splits`, but its file name, docstring and test names still say runtime (`test_a_unit_parked_for_a_runtime_reads_as_blocked`). `tests/e2e_park_fakes.py:1` ("park blocked runtimes") and `tests/pipeline/test_e2e_blocked_wiring.py:1` have the same leftover wording.
- CHANGELOG.md:110 — The unreleased parking bullet still says the unit waits on "a blocked runtime's tests" and that a status is never posted for "a runtime's tests unrun". This branch renames that behaviour to splits, and the new sentence was added to the splits bullet at line 71. The parking story is now told in two bullets with two vocabularies.
- CHANGELOG.md:72 — The added sentence says a unit parked "before this release" with `runtime_blocked`/`parked_runtimes`. Both names are also under Unreleased, so no release ever wrote them. Only an install running unreleased code can hold them.

## From `tier2-splits-replace-runtime-tags/5`

- When the top-level splits are still written under the old `e2e_splits` key, the message refusing a hold at a repo that follows them still names `tests.e2e_splits`. It could name the key the file actually uses.

## From `tier2-splits-replace-runtime-tags/11`

- src/agent_build_kit/skills/abk-config/SKILL.md:292 — The skill's E2e-test splits section still names the key `tests.e2e_splits`. After the test-kinds rename that is now on main, the key is spelled `tests.e2e_splits`; `e2e_splits` still loads, but with a notice.
