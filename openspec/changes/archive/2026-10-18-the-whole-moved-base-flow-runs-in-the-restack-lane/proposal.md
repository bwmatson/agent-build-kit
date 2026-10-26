# Proposal

## Why

The lane that a restack runs in (`a-restack-takes-no-slot-and-runs-when-seen`) took the move and the resolver out of the build workers,
and deliberately left everything after the move in a worker: the re-verify, the review of a resolved move, the push of a rewritten head,
the rework and the port of a conflict the resolver could not settle. Its reason was that running "the whole thread in the lane" is a
build with a different name and unbounded agent work outside the build cap. The cost of that choice is now seen:

- **A unit waits for a worker for nothing but a moved base.** A unit whose resolved move lost some of its own tests was left planned with
  the cause `restack_conflict` ("the unit's next run resolves it in its build session"). The only reason it has to run is that its base
  moved, yet it waits in the ready queue for a build worker while every worker is busy with units that have real work.
- **A conflict rework takes a worker, and spends it badly.** A unit in review whose pull request became conflicting is sent back for a
  conflict rework. For a unit whose thread is parked the event is routed to the `rework` step, not to the move, so the agent is asked to
  resolve a conflict on a branch that was never moved: in the case this was drawn from it answered "I changed nothing: the branch has
  not been moved onto the current base", and the run went on to run tier 1 and a review round on the unmoved branch before the check
  against the base found the move still to be done. One run, one worker, about an hour, for a rebase.
- **The same unit crosses the queue twice.** After the rework the check against the base found the base moved again; the second find
  holds the unit planned with `base_changed`, the lane moved it, could not merge it, and left it planned with `restack_conflict` for a
  worker. Three trips to the build queue for one moved base.

The person who owns the pipeline decided: when the only reason a unit needs to run is that its base moved, every step of that run
belongs in the lane. Ordinary rework and new builds keep the build workers.

## What changes

- **Which runs these are.** A moved-base run is a run of a unit that has commits on its branch and no rework input of its own, whose
  cause is `base_changed`, `restack_conflict` or `restack_deferred` (this includes the unit held by a run that found its base moved
  twice), or that was sent back for a conflict (the conflict rework kind). A unit owed one is found by the scan the lane already runs.
- **The whole run in the lane.** The lane's worker runs the unit from the move through the port, tier 1, the review, the check against
  the base and the push, in the unit's own session and run log, as a build worker would. It holds one of the lane's workers and the unit's
  branch for the run; it takes no build worker from the pool and is never refused or delayed for want of one, but it counts toward slot occupancy: no build
  starts while the occupancy is at or above the cap, and the occupancy may read over it (5/4). A run the process lost, or a usage pause
  interrupted, is resumed by the lane.
- **The lane does not do ordinary rework.** The run stops before a step that is not moved-base work: a rework that answers a reviewer, a
  comment or a failing check, a fix of failing checks, and tier 2. The unit finishes the step it is in, is left planned with the new
  cause `restack_handed_back` and a note, keeps its thread where it stopped, and a build worker takes it from there. The lane never
  continues it.
- **A conflict rework starts with the move.** The event is routed to the move, as the non-thread path already does, and a rework agent is
  called on the conflict only if the move left one.
- **The same guard.** Every agent call of the run asks the usage guard by the decision, thresholds and estimate any agent run uses; a
  refused read defers the run, which the lane resumes when the pause ends; a clean move with no agent is not gated.
- **A stated stop.** Each run is an attempt at the base's tip, counted with the conflict handler's attempts and bounded by
  `global_limits.max_review_rounds`; a unit whose attempts at one tip are spent is held with a reason, not run again.
- **Shown.** The unit reads `restacking onto <base>` for the whole run and `restacks: N running, M waiting` counts the run. The slot gauges and the sample row report the occupancy the run is part of, and `abk status` prints a slots line such as `slots: 5/4, 1 restacking`.

## Impact

- Capabilities: `unit-scheduling` (what the lane runs, which runs are moved-base runs, the lane worker held for the whole run, the hand-back,
  the whole-run status) and `restack-conflicts` (the guard before every agent call of a run, the conflict rework starting with the move,
  the bound and the stop).
- Code: `pipeline/restack_lane.py` (owed runs, the run's work and hand-back), `cli/pipeline.py` (`build_restack_lane`, `resumable_units`,
  `run_round`, `_evaluate_round`, `_build_unit`, `READMITTED_CAUSES`, `cmd_status`), `graph/unit.py` and `graph/nodes.py` (stopping a run
  before an ordinary step, the resolver of `prepare` behind the guard, routing a conflict event to the move), `pipeline/events.py`
  (`on_rework`, `on_conflict` hand a unit to the lane), `pipeline/unit_store.py` (one cause, one flag).
- Depends on `limits-split-into-global-and-project` (the lane for each project, group 8, and the counting for each project, group 7).
- No setting changes meaning and none is added. A unit stored before this change reads as before.
