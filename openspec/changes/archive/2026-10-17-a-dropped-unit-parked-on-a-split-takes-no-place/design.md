## Context

`in_progress(unit, graph)` in `pipeline/units.py` returns false for a planned unit whose `cause` is `split_held`. `StoredUnit.cause` is not a stored
field: it is the `cause` of the unit's latest history entry. A park writes it (`park_for_split` in `graph/nodes.py` calls `hold(..., cause=SPLIT_HELD)`
and then `set_parked`), and every later state change that passes no cause replaces it with nothing: `_with_state` (used when a replan or the
planner demotes a unit to `unplanned`, or promotes it back to `planned`) appends a history entry with state and time only. Checked against a live
store: a planned unit whose latest entry is the park reads `split_held` and is already uncounted; an `unplanned` unit whose latest entry is the
demotion reads no cause, falls through to "has a branch and is not blocked", and counts, though its `parked_splits` still names `acp` and its
`parked_sha` is set.

`parked_splits`, `parked_sha` and `parked_snapshot` are stored fields. They are set only by `set_parked` in the park, and cleared only by
`set_parked(unit_id)` in the e2e step of a run that resumed the unit (and did not park again). A requeue or release does not clear them: the
resumed run reads them to run only the parked split on the commit it passed on. So a unit that is `planned` or `unplanned` and has `parked_splits`
is one that was parked and has not run its e2e step since; while a resumed unit is `running` it keeps them until that step, but a running unit is
counted by state before the exemption is reached.

`UnitStore.upsert` builds each existing unit's record anew and copies a list of fields from the old one. `parked_splits`, `parked_sha`,
`parked_snapshot` and `parked_attempts` are not in that list, so any replan that includes the unit resets them to empty. `release_split_held` picks
planned units with cause `split_held` and reads `_holds_of_parked` over `parked_splits`; with them wiped no split is held, so it would resume the
unit while the split is still held.

## Decisions

- **Key the exemption on `parked_splits`, with the old test kept.** A unit is parked on a split when its state is `planned` or `unplanned` and
  `parked_splits` is non-empty. It is exempt then, whatever its cause field says, with one limit: not when its latest cause is another one than
  `split_held` (for example `requeued`, `host_unavailable`, `service_unavailable`), because those are written after the park by a release, a
  requeue or an interruption of the resumed run, and the unit is then on its way to run, not waiting for the split. The old test (state `planned`,
  cause `split_held`) stays a sufficient condition because the run still sets it for every new park, and a record with the cause but wiped splits
  (before the carry fix below reaches it) is still parked.
- **One helper.** A `parked_on_split(unit)` function in `pipeline/units.py` states the rule once; `in_progress` and `_split_wait_lines` in
  `cli/pipeline.py` both call it, so the count and the status cannot disagree. `release_split_held` and `_releasable_split_units` stay as they are
  (planned units with cause `split_held`), so an `unplanned` unit is never resumed by a release, and a replanned unit with parked splits and no cause is
  started by the ordinary round, which resumes it with only its parked split.
- **Carry the park across a replan.** `upsert` adds the four parked fields to the fields it takes from the existing record. The park is work in
  progress, not shape, like the feedback the same block already keeps. This also fixes the premature release above. Demotion by `_with_state` keeps
  them already (it copies the unit); the test pins that.
- **Status.** `_split_wait_lines` lists a planned or unplanned unit that is parked, as "unplanned, parked on tier 2 split <name>" for the unplanned
  one, with the hold's reason or "released, left alone: the plan no longer has it". It is shown so a person sees why a branch and worktree remain.
- **Do not count, do not clean.** Nothing deletes the branch or worktree. A person leaves the unit; its record is harmless.

## Needs

No `Needs:`. The change `a-unit-in-a-held-split-is-not-started` states that `in_progress` is false for a parked planned unit but edits only the
round's exclusion and the wait reasons, and `the-whole-moved-base-flow-runs-in-the-restack-lane` has a test that reads the count without editing
`in_progress` or `_worked_on`. The overlap with both is textual (the architecture paragraph on units in progress), so the code does not depend on
either. The planner may join this change's group with a neighbour's.

## Follow-up not in this change

A way to retire a started unit the plan dropped is a separate change, to be drafted later: an `abk` command that ends such a unit as satisfied or
closed and, after confirmation, removes its branch and worktree. Until then a person leaves it.
