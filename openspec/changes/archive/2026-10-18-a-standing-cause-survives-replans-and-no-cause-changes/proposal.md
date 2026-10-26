## Why

A unit's cause is not stored. `StoredUnit.cause` reads the `cause` of the unit's latest history entry, so any state change that appends an entry with no cause hides the previous cause although the situation it named still holds. A replan does exactly that. `UnitStore.upsert` demotes a planned unit the plan omits to `unplanned` and promotes an `unplanned` one back to `planned` through `_with_state`, which appends `{state, at}` and nothing else. `unplan_vanished` and `join` do the same. A real unit parked on a held tier 2 split (cause `split_held`) was demoted to `unplanned` by a replan: its cause vanished and `in_progress` counted it against `max_units_in_progress` for hours.

The same shape of loss has more victims, all found by auditing every writer of a history entry and every reader of `cause`:

- The conflict move in `pipeline/events.py` that comes back `DEFERRED` writes `in_review` with no cause, erasing the `restack_deferred` cause that `restack` wrote a moment earlier. The restack lane reads that cause (`owed_a_restack`, `owed_a_moved_base_run`) for planned, running and in-review units, so the lane stops owing the restack, and `follow_predecessors` stops skipping the unit.
- `UnitStore.upsert` rebuilds each existing unit from the plan and copies only some fields from the stored record. Thirteen runtime fields come back empty after any replan: `parked_splits`, `parked_sha`, `parked_snapshot`, `parked_attempts`, `service_attempts`, `gated_requeue`, `waited_on`, `wait_ended`, `close_pending`, `step`, `guidance`, `ready_at` and `first_human_activity_at`. A `gated` unit then has no saved requeue to deliver, and a `split_held` unit has no splits to wait on, so `release_split_held` resumes it while the split is still held. No test pins the reset.
- `release_gated` clears `gated_requeue` and only afterwards rewrites the cause, so a crash between the two leaves cause `gated` with nothing to deliver.
- `backoff_ends` measures a backoff from the latest history entry's time, so any entry that merely carries a cause forward would restart the wait.

Every one of these is a reader of a value that a writer lost without meaning to. Fixing each reader to guess from other fields (as the sibling changes `a-dropped-unit-parked-on-a-split-takes-no-place` and `a-started-unit-keeps-its-groups` do for one case each) leaves the rest. The cause should survive as long as the situation does.

## What Changes

- **Two kinds of cause.** A standing cause lasts as long as the situation it names: `split_held`, `gated`, `upstream_went_back`, `base_changed`, `restack_deferred`, `restack_conflict`, `restack_handed_back`, `host_unavailable`, `network_unavailable`, `service_unavailable`, `environment`, `rework`, `usage`, and the holds `dirty_worktree`, `attached`, `needs_human`, `reviewer_hold`, `toolchain`, `depth`, `review_escalated_class`, `review_escalated_disagreement`. An event cause describes a transition that has happened: `requeued`, `released`, `adopted`, `merged`, `auto_landed`, `closed`, `failed`. The two sets are named in code and a test makes them partition `Cause`.
- **The store carries a standing cause across the changes it makes itself.** A sentinel `KEEP` is accepted wherever a cause is: `set_state`, `_record_state`, `_with_state`. It resolves to the unit's current cause when that is standing, and to no cause otherwise, and carries the previous note. `upsert` (demotion and promotion), `unplan_vanished` and `join` pass it. The default stays "no cause", so a caller that records a state change still ends the cause by passing none or another.
- **No second stored field and no migration.** The history stays the single source. A carried entry is marked `carried`, so `StoredUnit.cause_since` can tell a carried entry from a new one, and `backoff_ends` reads it instead of the latest entry's time.
- **A cause change closes the gate in the same write.** `_record_state` clears `gated_requeue` when the resolved cause is not `gated`, like its existing resets of `step`, `held_by` and `moved_base_run`.
- **A replan keeps the runtime fields.** `upsert` carries the thirteen fields over from the stored record.
- **Decision sites stop depending on a cause that can be lost.** `release_gated` and `awaits_release` key on a saved requeue. The deferred conflict move passes `restack_deferred` explicitly. Each other reader of `cause` gets a regression test over a demotion, a promotion and a replan, with no code change where the carry already makes it right.
- **Documents and skills** define the two kinds and the rule, and a changelog bullet says it.

Known gap, out of scope: a reviewer's hold label and its release always return a unit with a pull request to `in_review` (`held`, then `in_review` with cause `released`), so a planned unit's standing cause is lost across a label hold. Whether the unit should return to `planned` is a separate question; the design names the sites.

No new command, no new stored field, no change to the units file's schema.
