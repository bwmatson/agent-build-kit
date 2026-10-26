# Proposal

## Why

Every clean move of a unit's branch onto a moved base re-runs the whole local tier 1: at the check just before a push, and after a merge
releases a dependent. In six days of one installation's run logs there were 38 such moves ("moved onto main cleanly; tier 1 again"), each
costing about four minutes (the parallel suite 140 to 180 seconds, the serial pass 55 to 65 seconds, the pre-commit step), about two and a half
hours in all, for a move that did not change the unit's own diff. The same suite already runs in CI on every pull request and gates the merge, so
the local run is a second copy of a check that cannot be skipped later.

The same logs show 15 further holds, "tier 1 failed on main", after the move. Some are one real fault on the base; some are flakes, and a flake
held on a moved base costs a restack round and a wait for the next tick and a free slot.

## What Changes

- **A clean move is checked by what it can affect.** After a move with no conflict and an unchanged diff, tier 1 runs lint on the moved diff as
  today, then only these tests: those the unit added or changed, those the toolchain profile says run the files the move brought in, and those the
  profile says run the files the unit changes. The selection is the profile's existing `affected_test_commands` hook; the framework outside the
  profiles names no ecosystem.
- **Some moves keep the full suite.** A resolved conflict, a changed diff, a move that brought in a file the unit also changed, a profile that cannot
  select (or cannot place a changed file), a selection that cannot run, and a setting that says `full`.
- **A scoped failure is classified before it holds.** The failed tests are rerun alone, as tier 1's flake isolation already does. A test that
  passes alone is a flake: it is recorded and its fix is made as today, but the unit is not held for it, because the move did not cause it. A test
  that fails twice holds the unit as today, with its failure as the feedback. A test the unit added or changed is never excused as a flake.
- **The log says what ran.** `moved base: ran 14 of 5963 tests (own 6, affected 8)`, or why the whole suite ran instead.
- **A setting restores today's behaviour.** `limits.restack_check`: `affected` (default) or `full`.
- **Unchanged:** the full suite in CI and before a merge, tier 1's other runs (the first check, fix rounds, the gate before review), and the
  tier 2 rule for a tier 2 unit's moved base.

## Impact

- agent-build-kit: a setting, the scope rule, the selected run in the tier 1 runner, the moved-base state the graph and the stack restack handler
  pass to it, the flake handling for a scoped run, docs (`docs/architecture.md` steps 6, 7 and 8, `docs/configuration.md`, the `abk-config`
  skill) and a changelog entry.
- It reuses `affected-tests-in-fix-rounds` (the `SelectsAffectedTests` hook, `RepeatsTests.repeat_command`, the selected-run plumbing in
  `build_tier1`) and `flaky-tests` (`isolate`, `FlakeFound`). The Python profile's implementation of the hook is that change's group 2, so the
  second group here waits for it.
