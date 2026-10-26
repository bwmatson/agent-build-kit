## Context

Code at agent-build-kit `origin/main` (e0d26911):

- **The per-group build.** `tests` (`graph/nodes.py:1294-1320`) writes a group's stubs and tests and leaves the commit to `stub_checks`
  (`1322-1342`), which runs lint, format and types (`clean_command(types=True)`, `pipeline/wiring.py:905-931`) and commits `test: <title>` on a
  pass; `implement` (`1413-1463`) commits `feat: <title>`, then `unpaired` (`1398-1406`) stops the unit when the branch lacks the group's pair, and
  advances `group` and `more_groups`. Routing is `after_tests`/`after_stub_checks` to `implement` and `after_implement` back to `tests` while
  `more_groups` (`2588-2605`). A group's step is `GroupStep` (`pipeline/stack_runner.py:228-234`), made by `group_steps` (`1747-1770`) from the
  parsed `TaskGroup` (`pipeline/work_graph.py:197-227`, flag in `FLAGS` at `106`).
- **Resume.** `resumed` (`nodes.py:1072-1088`) reads the branch's subjects with `group_progress` (`commit_order.py:151-166`): groups walk in the
  unit's order, each taking a `test:` then a `feat:` commit with its title; `after_prepare` (`2557-2585`) goes to `implement` when the tests commit is
  there, else `tests`.
- **The push gate.** `abk gate` (`cmd_gate`, `cli/pipeline.py:5913-5953`) calls `check_branch` (`gate.py:61-145`), which calls `check_structure`
  (`commit_order.py:191-268`) and then, at each tests commit, runs the profile's `clean_command` and `red_command(files)` in a throwaway worktree and
  reads the output with `interpret_red`. It is the command form of the rule "for a person or a hook" (`docs/architecture.md:1218-1219`). Neither it nor
  `check_structure` is given the plan: they know only commit subjects and paths. `check_branch`'s callers are `abk gate` only; the runner's own push
  condition is the approved-SHA check, so the pair count in `implement` is what stopped `asr-streaming-service/10`.
- **How e2e (local_stack) tests are treated today, in both modes** (read from the code; nothing in the gate or the red reading names the e2e marker):
  - `check_branch` runs `uv run pytest <the test files the commit touched> -p no:cacheprovider --tb=line -q` (`profiles/python_uv.py:353-358`),
    under the repo's own pytest options. `grep` for the e2e marker (`repo.tests.e2e_marker`, default `local_stack`, `config.py:889`) finds it read
    only by the e2e step, `abk e2e-test` and verify (`cli/e2e_cmd.py`, `pipeline/verify.py`), never by `gate.py`, `red_check.py` or the
    profiles' `interpret_red`.
  - If the repo deselects the marker in its default options, an e2e-only tests commit collects nothing and `interpret_red` rejects it as "no tests
    ran at the tests commit, so nothing was shown to fail" (`red_check.py:125-129`, `NO_TESTS`). If it does not deselect, the tests run, fail on a
    refused connection or a missing key, and the failure is not one of `ACCEPTED`/`ACCEPTED_TYPES` (`red_check.py:60-63`, `81-89`), so it is rejected
    as an unrecognised failure (`150-153`). Either way an e2e-only tests commit is refused by the gate today, stubbed or not.
  - An e2e-only unit that reached its e2e step under the old mode (as `asr-streaming-service/9` did; inferred from the code, that unit's log was not read) was not eased by anything in the gate. The old
    mode is one tests commit for the whole unit, and the runner never calls the gate on the way to its e2e step; the e2e step is reached from the
    pair count's pass (one `feat:` commit exists) and runs the marked tests against the stack (`pipeline/verify.py`, `profiles/python_uv.py:725-760`),
    where they are shown to pass, not red. So the red rule was never applied to e2e tests in a build; it applies only when a person or a hook runs
    `abk gate` on such a branch, where it already refuses them. This change fixes that refusal for the test-only commit only (below).

## Decisions

- **Rule: a group is test-only when it is tagged `[e2e-test]`**, flagged `[acceptance]` or not. It is read from the heading's tier, which `abk tags`
  already validates, so no model call and no reading of task prose. The reason is the sibling change `e2e-groups-hold-tests-and-stand-alone`: it makes
  every e2e group hold only tests and test support (a product fix is made by a separate `[unit-test]` unit, and a guard stops an e2e unit that changes
  product code), so every e2e group is test-only in content. **This change depends on that sibling for the guarantee that an e2e group holds no
  product code.** Alternatives rejected: (1) "every task of the group is a Test task": it depends on prose that `abk tags` does not read (`10.4` in
  the failing group writes test-support code and would not begin `Test:`) and a wrong guess silently makes a group with real implementation skip its
  implement step; (2) "tagged `[e2e-test]` and flagged `[acceptance]`" (this change's first rule): it leaves a plain `[e2e-test]` group, which the
  sibling also makes tests-only, to meet the pair-count stop. A `[unit-test]` or `[integration-test]` group, even one holding only tests (a regression
  test for existing behaviour), is not test-only: it still needs its `feat:` commit; an author who has no implementation to write puts the tests in
  an `[e2e-test]` group or in the group they test.
- **Exposed as `TaskGroup.test_only`, a property** (`tier is E2E_TEST`), carried by `GroupStep` (a `test_only` field set by
  `group_steps`; a group whose heading cannot be read is not test-only, as it has no tier). The gate gets the same fact from the plan, not
  from a commit's content.
- **One tests commit, no implementation commit.** For a test-only group `tests` writes the tests with a finish note that says the group builds no
  implementation, that stubs are not needed (nothing it tests is missing) and that tests needing the live stack are not to be run, and `stub_checks`
  commits `test: <group title>` (body as for any group) after the same static checks. Nothing is required of stubs; the existing rule that a tests
  commit holds tests, stubs and docs and no other code still applies to it (test-support code lives under the tests directories and so is tests).
- **The implement step is skipped.** When `stub_checks` commits the tests commit of a test-only group it also does what `implement` does when a
  pair is done (advance `group` and `more_groups`, clear the guidance after the last group) and routes to `tests` for the next group or on as
  `after_implement` does after the last (`checks`, or `unit_test` when nothing was produced); no agent call is made for it.
- **The count.** After the last group the build counts the groups satisfied on the branch: a group is satisfied by its pair, or, when it is
  test-only, by its lone `test:` commit. A short count stops the unit naming the groups missing, as now, whether the last group was test-only or not;
  that check therefore runs at the end of `stub_checks` for a test-only last group as well as at the end of `implement`. A group that is not
  test-only with no `feat:` commit still stops the unit.
- **Resume reads the branch, with the plan's help.** `group_progress` takes each group's title and whether it is test-only. A test-only group is
  done when its `test:` commit is on the branch (it takes one subject, not two); `tests_made` is never the state of a test-only group, so
  `after_prepare` never routes it to `implement`. Restack, requeue and a kill between groups resume as before, by the subjects in the unit's order,
  and two groups with one title are still told apart by position.
- **The gate learns the plan.** `check_structure` and `check_branch` accept the unit's groups in order, each with its title and test-only flag; with
  none given (a bare `abk gate`, a branch with no unit) no group is test-only and every rule is as today. `abk gate` inside an installation takes
  the groups from the unit named by the `Unit:` trailer the pipeline writes on each commit (`pipeline/wiring.py:836`), through the same
  `group_steps` read the build uses. The paired rule walks the branch's `test:` commits against the groups by position:
  - a `test:` commit that is the commit of a test-only group needs no `feat:` after it, whatever follows (nothing, another group's `test:`, a `fix:`);
  - any other `test:` commit still needs its `feat:` of the same title directly after it, so a lone `test:` commit of an ordinary group, and a
    `test:` followed by a `feat:` of another title, are refused as now;
  - `two tests commits in a row` does not apply to a test-only commit followed by tests;
  - `the branch has no implementation commit` does not apply to a unit whose groups are all test-only (a non-empty plan); any other unit needs one.
- **The answer to "do we need to ease the first-commit-fails rule for e2e units?": for a test-only group's commit, yes; for nothing else.** The
  rule exists so the tests are seen to fail before the code that passes them (`commit_order.py` header). A test-only group has no later code
  commit to pass them, and its live-stack tests cannot be run in the builder's session, where a run either collects nothing or fails on the
  connection, neither of which is evidence about the tests. So at the commit of a test-only group the gate still runs the clean command (lint,
  format and, in a stubbed build, types) and does not run the red command or read a red result. For every other tests commit the rule is unchanged,
  including a group tagged `unit-test` or `integration-test` that holds only tests: it is never test-only (the rule above), so it keeps its red run
  and its `feat:` commit. The cached result of a test-only commit is kept under a mode of its own, so a pass recorded with no red run is never
  reused for a commit judged with one.
- **Depends on `e2e-groups-hold-tests-and-stand-alone`.** That change guarantees an e2e group holds no product code (its guard stops an e2e unit that
  changes product code, and product fixes are made by separate `[unit-test]` units). That guarantee is what lets every `[e2e-test]` group skip its
  implementation commit and its red run here; an e2e group that built product code is out of this change's scope.
- **Setting and rename.** Governed by `builders.per_group_commits`, which group 12 of the parent change renames to
  `builders.stubbed_tdd_commits`; the rename carries through every place this change names it.

## Risks

- **A group wrongly tagged `[e2e-test]` skips its implementation.** The tag is reviewed with the plan; a group tagged by mistake would produce a
  tests commit and no code, which review and the e2e step (the tests would fail against the missing code) catch.
- **Until the sibling's guard is built, an e2e unit may change product code.** This change accepts that risk: such a unit is reviewed, and what the
  reviewer sees is a commit list with a lone `test:` commit and no `feat:` commit, with product files in the diff of a commit that claims to hold tests.
  Once the guard of `e2e-groups-hold-tests-and-stand-alone` is built, an e2e unit that changes product code is stopped before review.
- **A gate run without the plan is stricter.** A bare `abk gate` refuses a lone `test:` commit; the message names the missing `feat:` and says the
  plan decides.
- **An e2e group that needs a small fix to an earlier group's code.** It is a rework of the unit (a `fix:` commit after the last commit),
  as `abk-authoring` already says gaps found by the e2e run are handled; it is not a reason for the group to be built as a pair.
