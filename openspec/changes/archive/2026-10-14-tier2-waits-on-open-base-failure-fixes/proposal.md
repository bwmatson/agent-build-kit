# Proposal

## Why

`tier2-failures-in-untouched-tests-are-fixed-once` makes a test that fails on the base a recorded failure with one fix change, and parks the
unit that met it behind that change. Only that unit waits. Every other unit that reaches a full tier 2 run while the fix is open runs the whole live-stack
marker, spends 40 to 66 minutes, meets the same test and fails the same way, or is parked after the hour is spent. The fix change is already
the thing everyone is waiting for; the pipeline just does not make the rest wait for it before they pay.

## What Changes

- **A gate before a full tier 2 run.** When a unit is about to run tier 2, the run is full-scope, and the record of base failures holds one whose fix change is still open, the
  unit gets a `Needs:` line on that change, through `wait_on_preexisting`, and is parked as the unit that met the failure is. No test runs and
  the stack lock is not taken.
- **Only full-scope runs are held.** `tier2-runs-on-a-schedule` makes a unit run only the tier 2 tests it added or changed by default
  (`tier2_unit_scope`, `own`, set per repo with a `limits` default); such a run never executes a test it did not touch, so an open fix elsewhere has nothing to say to it and it is
  not held. The gate holds the runs that execute the whole marker: `full` scope for the repo, a run through a dev stack script and a run
  that could not be narrowed (and the scheduled run of `tier2-runs-on-a-schedule`, which that change makes full by the same function). It asks the scope function that change adds, so the unit that runs no test is not held either.
- **Nothing scans other units.** A unit not yet at tier 2 meets the gate on arrival.
- **Who is exempt.** A unit of the fix change itself, and a unit that already waits on it. A unit is exempt only from the records its own change
  fixes.
- **Per repo.** A record blocks the units of the repo whose suite holds the failing test.
- **Only base failures count.** The gate reads the record the base-run classification writes. A unit's own failure and a flake write none.
- **Unchanged:** a run in flight finishes and is classified as today; an abandoned fix change is handled by the rule for a closed prerequisite;
  `limits.tier2_base_runs: 0` means no record and so no gate.
- **Shown.** The wait shows as any `Needs:` wait does, and the status line of each pre-existing failure says how many units wait on its fix.

## Impact

- agent-build-kit: the `tier2` node (a check before `run_tier2`, which asks the run's scope), a function in `pipeline/untouched_failures.py` that finds the open fix
  changes a unit is held by, a runner callable beside `build_on_preexisting`, the status line, docs and changelog.
- It builds on the merged code of `tier2-failures-in-untouched-tests-are-fixed-once` (the record, `wait_on_preexisting`, the park); nothing in
  that change is modified. It needs group 1 of `tier2-runs-on-a-schedule`, which adds the scope function and `limits.tier2_unit_scope` the gate reads,
  and is Priority 1 as it is. It does not touch the lock wait, the base run or the classification, and it does not stop a run already started.
