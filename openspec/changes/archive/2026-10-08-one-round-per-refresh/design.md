# Design

## The round

`run_round(inst, store, *, building, started, only, submit)` in `cli/pipeline.py`:

1. `_refresh` (fetch, poll);
2. `convert_in_flight`, `plan_all`, `link_needs`;
3. `verify_ready` and `archive_ready_changes`, with verification gated on the live-stack
   lock (step below);
4. `reclaim_stranded(building)`, skipping every unit in `building` or `started` this pass
   and any unit whose branch lock is held;
5. the usage guard: if it refuses, record the pause and return without submitting;
6. `resumable_units` (the units whose thread an event resumed or a killed run left partway,
   which the tick starts today) followed by `_evaluate`, and, if `submit`, return the units to
   start (the caller submits them); the cap is applied to runs in flight (`building` plus any
   run another process holds), so a resumed unit waiting to start does not count against it.

Each of 1–4 is wrapped as `_refresh` already is: an exception is logged with its type and
the round goes on to the next step. The tick calls the round once and submits; `_schedule`
calls it after each wait for a completion or the refresh interval, in place of the
`_refresh`, readmission and evaluation block it has today. `_sent_back` readmission stays in
the loop between steps 4 and 6, since it needs the loop's `started` set.

## Verification and archive in a round

`verify_ready` deploys and runs the change's live-stack tests, which uses the same stack a
unit's tier 2 run uses, serialised by the live-stack lock. A round takes that lock without
waiting; if it is held (a tier 2 run, or an earlier round's verification), verification is
skipped and logged and the change is picked up next round. Archive runs only for a change
whose verification passed (as now) and whose units are all merged or finished, so it never
touches a unit that is building.

## Resumed units and the cap

`_evaluate` treats every `running` unit as holding a slot, so a unit whose thread an event
resumed (marked running by the delivery, with no run yet) blocks a slot until a tick starts it.
The round passes `building` as the set of runs actually in flight; a running unit that is
neither in it nor held by a live process (the same check reclaim uses) is counted as resumable
work, started first, and not counted against the cap. A unit just handed to the pool is in
`building` and counts.

## Reclaim

`reclaim_stranded` returns to `planned` a unit marked running that no process holds and no
thread can resume. In a pass, a unit handed to the pool has not yet taken its branch lock, so
the round passes the in-flight set and a started-this-pass set and excludes them.

## The guard

Re-asked every round with the existing decision function; a refusal records the pause with
the same marker and count as a tick does and stops submission for the rest of the pass,
which the loop already treats as `stopping` once a pause marker exists.

## Cost and cadence

The refresh interval is unchanged (five minutes). A round with nothing new reads each
change's hash and the unit store and calls the code host as the refresh does today; planning
makes a model call only for a new or edited change.

## Out of scope

Starting a second tick or a long-lived daemon in place of the timer, running steps on
their own threads, and the model used for planning.
