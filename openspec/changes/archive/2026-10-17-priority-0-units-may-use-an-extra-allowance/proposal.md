## Why

Sometimes one unit must start now, past a full queue. Today a person does it by hand: back up `abk.yaml`, raise `max_concurrent_stacks` and `max_units_in_progress`, run
`abk tick --only <unit>`, then put the limits back so nothing else flows in. The queue is usually full because places are held by units doing nothing (two paused, one failed
and not waiting) beside running work, so even a ready priority-1 unit cannot start. `Priority: 0` (the emergency lane) already starts first, but by decision it bypasses no
limit, so it does not remove the hand edit.

## What Changes

- **Priority 0 starts as soon as it is ready, in its own lane, like a restack.** A ready unit that has never started and whose effective priority is 0 (a prerequisite of a priority-0
  unit has it) starts at the next tick even when the limit on units in progress and the worker cap are full, as a moved-base run starts without a free build worker. The lane has its own
  cap, `project_limits.emergency_extra` (an integer of 0 or more, default 1): the number of priority-0 units that may be started past the normal limits at once in a project, counted
  as the units using the lane (started past the limits and not finished). 0 turns the lane off and restores today's behaviour. The name stays: it sits beside `max_concurrent_restacks` and
  keeps the key the earlier draft named.
- **Independent of the restack lane.** A priority-0 start is not blocked by lane runs and uses none of the lane's cap, and lane runs are not blocked by it. Both count toward occupancy
  (which may read 5/4 or 6/4), each with its own cap.
- **Ordinary starts wait.** A priority-0 unit in its lane counts toward occupancy, so while occupancy is at or above the normal limits no ordinary never-started unit starts: the unit
  takes extra room and makes none.
- **It never holds back a unit that is finishing.** A rework, a resume, a review loop, a restack or a unit finishing its review runs as today; a resume is not held for a worker
  that a priority-0 unit uses. The build pool has a thread for the lane in addition to the normal cap.
- **Nothing else changes.** A priority-0 unit that fits inside the normal limits starts normally and does not use the lane cap; the usage guard, the depth cap, dependencies, leases,
  backoff and held splits apply; units already started are unaffected; priority 1 and below get no lane.
- **Said where a person looks.** `abk status` prints `emergency room 1/1 used by <unit>` (the lane cap in use) and says in the queue-full line that a priority-0 unit may still start; the ready queue marks it.
- **Text.** The configuration and architecture documents, the `abk-config`, `abk-pipeline` and `abk-authoring` skills, and the changelog.

## Impact

- Capabilities: `emergency-allowance` (new: the setting and its validation), `unit-scheduling` (added: the lane, the pool, the display; modified: the priority-0 requirement, which said it
  bypasses no limit).
- agent-build-kit: `config.py`, `installation.py`, `pipeline/units.py` (`ready_units`, one helper), `cli/pipeline.py` (`_evaluate_round`, `_within_workers`, `run_round`, `_pool_size`,
  `_planned_wait`, `sample`, the status functions), a small state record of the lane's units, the documents, three skills and the changelog.
- Compatible: an `abk.yaml` without the key loads and gets the default 1, which changes behaviour only when a priority-0 unit is ready at a full queue; set it to 0 to keep the old behaviour exactly.
- Not in this change: a quota of priority-0 units beyond the lane cap, any other priority using the lane, a reserved worker, a setting per repo, any change to the restack lane's admission or cap.
- Priority 1: set by the person who asked, so it builds with the other urgent work; nothing is blocked without it.
