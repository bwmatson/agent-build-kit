## Why

A unit can be parked on a held tier 2 split and still take one of the places under `max_units_in_progress`, though it has nothing to run until the
split is released. The count (`in_progress`) exempts a unit only when its state is `planned` and its latest history entry carries the cause
`split_held`. That test rests on the wrong thing. The cause is read from the unit's latest history entry, so any later state change that writes no
cause (the planner setting the unit `unplanned` after its group was reshaped, or a replan setting it `planned` again) makes it read as empty and the
exemption lapses. What survives those changes is the record of what the unit is parked on: `parked_splits`, with `parked_sha`. In a real store an
`unplanned` unit parked on the held split `acp`, with no pull request, no pushed commit and a branch only in a local worktree, takes one of five
places for hours: its stored history ends in `unplanned` with no cause, while its `parked_splits` still reads `acp`.

A second flaw sits beside it. A replan (`UnitStore.upsert`) rebuilds each existing unit from the plan and carries over its branch, pull request,
feedback and the like, but not `parked_splits`, `parked_sha`, `parked_snapshot` or `parked_attempts`, so a replan wipes a parked unit's record of what it
waits on while its cause (read from history) still says `split_held`. The release step then finds none of its splits held and resumes it while the
split is still held.

## What Changes

- **The exemption keys on being parked.** A unit in state `planned` or `unplanned` whose `parked_splits` is non-empty does not count toward
  `max_units_in_progress`, whatever work it has, unless its latest cause is one other than `split_held` (it was requeued or interrupted after the park,
  so it is on its way to run). The old test, state `planned` with cause `split_held`, stays as well, because the run still sets that cause on every
  new park. The exemption applies whether or not the cause is set.
- **`abk status` follows.** The queue-full line and the count of units in progress leave such a unit out, and the status lists it, planned or
  unplanned, as parked on its split.
- **A replan keeps what a unit is parked on.** `upsert` carries `parked_splits`, `parked_sha`, `parked_snapshot` and `parked_attempts` over from the
  existing record, so the park survives a replan and a demotion to `unplanned`.
- **Nothing else about unplanned units changes.** An `unplanned` unit with a pull request, a running run or a pushed commit that is not parked on a
  split counts exactly as before.
- **Release does not restart it.** When the split is released a parked `unplanned` unit is left alone, because the plan no longer has it; it stays
  uncounted until the plan carries it again, and `abk status` lists it as an unplanned unit parked on the split. Its branch and worktree are kept.

No new command, and no change to how a planned unit parked on a split is released.
