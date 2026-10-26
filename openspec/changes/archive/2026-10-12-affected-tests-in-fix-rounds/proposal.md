# Proposal

## Why

When tier 1 fails before review, the fixer commits a change and the whole suite runs again, in every round, to find out
whether one failed test now passes. Across recent units 106 parallel runs took about 3.6 hours of wall time, 13 of them
failed ones, at roughly two minutes each. Most of each re-run repeats tests that cannot be affected by the fix.

The pipeline has no way to ask a stack which tests a change affects. The question is stack-specific (a coverage database,
a dependency graph, a package list), so the answer cannot live in the pipeline, but the pipeline can own when a narrowed
run is allowed, and when the full one is mandatory.

## What Changes

- **A toolchain profile can name the tests a change affects:** a new optional hook beside `test_commands`, returning
  commands, or nothing when the stack cannot say.
- **A repo chooses, in its own configuration,** whether fix rounds use it: `off` (the default, today's behaviour),
  `profile` (the profile's hook), or `command` (a template taking the changed files and the failed test identifiers, so
  any stack's own tool plugs in without a profile).
- **The fix loop uses a selected run, then confirms with the full suite.** After a failed check, the next check runs the
  selected tests; if they pass the full suite runs once, as the gate before review; if they fail the unit goes straight
  back to the fixer. A selected run never marks a unit green.
- **The Python profile selects by coverage,** with a fallback that needs no plugin: the failed test identifiers the
  output already carries, run first.
- **Each selected run is measured:** how many tests were selected of the total, the time it is estimated to have saved,
  and whether the confirming full run agreed, recorded as ledger rows.

## Impact

- agent-build-kit: the toolchain profile protocol and the Python profile, the repo configuration, the tier 1 runner and
  the check and fix-check nodes, the usage ledger, and docs. Nothing changes for a repo that leaves the mode `off`.
- A node stack is covered by command mode today; its profile is not yet written and returns nothing.
