# Proposal

## Why

Tier 2 is serialized behind one lock file in the state directory. A unit whose tier 2 tests are ready but whose turn has not come waits for the lock up
to a fixed 3600 seconds and then fails with `TimeoutError: tier 2 is busy`, although nothing is wrong with it and its tests never ran. One real tier 2
run now takes 40 to 61 minutes (sixteen tests took 61), so any unit that queues behind a full run times out. A unit failed this way and a person had to
requeue it. The one-hour limit was chosen when a run took minutes, as "long enough for a queue of real runs to drain"; the earlier change
`tier2-tests-have-their-own-time-limit` raised the limit on each test but left this one, which is a different thing: not how long a test may run, but how
long a unit may wait its turn.

The wait is also invisible. A waiting unit looks like a running one, and a person cannot tell who holds the lock, for how long, or whether the holder is
alive.

## What Changes

- **Waiting for the tier 2 lock is never a failure of the unit.** A unit's tier 2 step waits until the lock is free, with no deadline. The fixed
  3600-second limit is removed and no configurable ceiling replaces it (design: why).
- **The wait is visible.** It is logged at a fixed interval with the holder and how long it has held the lock, and recorded as a ledger span
  `waited = tier2_lock` when it ends, so time reports can tell waiting from work.
- **The lock records who holds it.** The holder writes its unit, process and start time into the lock file and clears it on release.
- **`abk status` shows the holder and its age**, and a record whose process is gone is shown as stale.
- **A stale record is ignored, never trusted.** The lock is a kernel `flock`, so a dead holder frees it by itself; the leftover text is reported once
  and overwritten. A lock that is still held by a process other than the recorded one is reported and not broken.
- **Callers that pass a wait keep their limit.** The post-merge verification and its `StackBusy` result, which choose to give up, are unchanged.

## Impact

- agent-build-kit: `pipeline/tier2.py` (`stack_lock`, the removed default timeout), the tier 2 runner in `pipeline/wiring.py`, the span vocabulary in
  `pipeline/spans.py`, the status report, `docs/architecture.md` and the changelog.
- Spec: `test-tiers` (the tier 2 lock) and `unit-scheduling` (the status).
