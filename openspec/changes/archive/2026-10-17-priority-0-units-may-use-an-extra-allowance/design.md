## Context

Read on the build tool's `origin/main`; paths are under `src/agent_build_kit/`, line numbers approximate.

- `config.py` `ProjectLimitsConfig` (~474) holds `max_concurrent_stacks`, `max_concurrent_restacks` (`ge=1`, default 2) and `max_units_in_progress`; the schema is strict.
  `MOVED_TO_PROJECT_LIMITS = tuple(ProjectLimitsConfig.model_fields)` (~489) lists the names a `limits` or `global_limits` block may no longer hold (`_refuse_moved_settings` says
  `abk config --migrate` moves them); `config_migrate.MOVED` is a separate literal of the same three. `installation.py` (~194-206) exposes them as properties.
- `pipeline/units.py`: `ready_units` (~945) counts `running` and `counted` for each project (`ProjectKey`); a unit "draws on room" when it has never started or was blocked and waits for
  room, and is skipped when `counted + drawn >= max_units_in_progress` or `running + taken >= max_concurrent`. `effective_priority` (~399).
- `cli/pipeline.py`: `_evaluate_round` (~1893) calls `ready_units` then `_within_workers`; `run_round` holds `resumable_units` to `cap` less `taken`; `_pool_size` (~2462) is
  `inst.max_concurrent_stacks` times the live projects and sizes the `ThreadPoolExecutor` (~2323); `_planned_wait`, `sample()`, `_queue_full_line` and `_ready_queue_lines` report it.
- The restack lane (`pipeline/restack_lane.py`, built in `build_restack_lane`, `cli/pipeline.py` ~3403): one `RestackLane` for each project, `max_concurrent_restacks` workers of its own
  apart from the build pool, admission that reads no build count, a per-project record file in the state directory (`record_path`, `RECORD_GLOB`) that `abk status` reads.
- Unbuilt changes in the same functions: `the-whole-moved-base-flow-runs-in-the-restack-lane` group 7 makes the build-slot counts an occupancy (builds in flight, moved-base runs
  running in the lane and stored-running units, once each, for each project), gates every build start (new and resumed) at or above the cap and adds a `slots: 5/4` line;
  `limits-split-into-global-and-project` group 9 rewrites `_queue_full_line` for each full project.

## Decisions

### A second lane, shaped like the restack lane

A restack starts when it is seen, past the build limits, with its own cap and its own workers, and it counts toward occupancy. A priority-0 start has the same shape: a second source of
work over the normal cap, with its own cap (`emergency_extra`), starting as soon as it is ready. It is not a margin on the normal limits and not shared with the restack lane: neither
reads the other's count, neither is delayed by the other, and each adds to the occupancy.

`emergency_extra` lives in `project_limits` beside `max_concurrent_restacks`, `Annotated[int, Field(ge=0)] = 1`. It keeps the name (it is not `max_concurrent_*`, because it bounds a
count of units, not threads, and 0 is a valid value that turns the lane off, which `max_concurrent_restacks`'s `ge=1` does not allow). It is not a quota and not a reservation: holding a place or a worker back from other units would starve them.

### The rule

For a ready planned unit that **draws on room** (never started, or blocked and now waiting for room) with effective priority 0 (`effective_priority(unit, graph, excluded) == 0`, so a
prerequisite of a priority-0 unit qualifies, and a waiter that the round leaves out lends nothing), after the usage guard, depth cap, dependencies, leases, backoff and held splits:

- if it fits the normal limits (the project's count below `max_units_in_progress` and its running count below the cap) it starts normally and is not in the lane;
- otherwise it starts in the lane if the project's **lane use** is below `emergency_extra`. The lane use is the number of priority-0 units currently using the lane: started past the normal
  limits and not finished. Neither the occupancy nor the restack lane's count is read, so lane runs never delay it.

A unit in the lane stays in it until it finishes (merged, closed or dropped); it does not move to a normal place when one frees, so the use is stable and a second priority-0 unit finds the
cap used until the first is done. It is a stored fact, not a count read from the limits (a count would blur with restack runs and with units that stay after others finish): a small
record in the state directory for each project, written (`atomic_write_text`) when the lane starts the unit, before its build is submitted, read by `abk status`, and pruned each tick of
units that are not in progress or are gone. The same helper `emergency_start(unit, graph, excluded)` in `pipeline/units.py` decides, for `ready_units` and `_within_workers`, so the two
places cannot disagree. Both the place check and the worker check are skipped for such a start; nothing else is.

### Occupancy and the ordinary queue

A unit in the lane is a build in flight, in progress and (once started) stored running, so it is counted by every figure that counts those: the project's count of units in progress and its
occupancy. Nothing is added to the formula; the lane's units are simply not exempt from it. Today's counts are builds in flight and stored `running`; when the restack-lane change (group 7)
lands the occupancy also holds the moved-base runs, and the priority-0 units add to that same figure, so with four builds, one restack run and one priority-0 unit it reads 6/4.
The consequence is the point: while the occupancy is at or above the cap, or the count at or above `max_units_in_progress`, no ordinary never-started unit starts. The priority-0 unit takes
room above the limits and makes none, so the normal queue stays closed until the figures fall below the normal limits again.

### A unit that is finishing is never held back

Units already in progress need no place and nothing here changes their rules: a rework, a review round, a restack, a unit finishing its review. A resume is held to the free workers
(`run_round`: `cap` less what is taken, and with the lane change `cap` less the occupancy); the priority-0 units in the lane are left out of that figure, so a resume is judged on the
occupancy without them. A priority-0 unit therefore never takes a worker from a unit that is finishing. The one thing that waits is a never-started ordinary unit (above).

### The pool has the thread

`_pool_size` is `inst.max_concurrent_stacks` times the live projects today, and the executor (~2323) runs the builds; the restack lane runs on its own workers, apart from that pool. It becomes
`(max_concurrent_stacks + emergency_extra)` times the live projects, plus nothing for the lane (it brings its own). The size is a ceiling on threads; `_evaluate_round` decides what starts. With
the old size a fifth build submitted at a cap of four would wait inside the executor and read as running with no thread. A resume stays held to the cap less the workers in use
excluding the lane (above), so the extra thread is used only by the lane and a pool larger than the cap starts nothing that would not start without it.

### Other rules

A blocked started unit counts nothing, as now; one that was blocked and no longer is draws on room like a new unit; a blocked priority-0 unit is not ready and uses nothing; a paused priority-0
unit with a branch is already started and waits for a normal worker. Both limits and the lane cap are read per project (`ProjectKey`).

### Display and gauges

The wording is in the status requirement. `_queue_full_line` says a priority-0 unit may still start while the lane use is below the cap; `emergency room N/M` is the lane record's count; the
ready queue marks a unit that is in the real evaluation's result and not in the same one with `emergency_extra` 0. `sample()` keeps `limit` and `cap` as the normal figures (`running` may exceed
`cap`, `free_workers` is `max(0, cap - occupancy)`) and one gauge, `abk.slots.emergency_used`, sums the lane use. `_planned_wait` gives a priority-0 unit that finds the cap used `queue_full`.

### Configuration

`emergency_extra` was never in the old `limits` block, so `MOVED_TO_PROJECT_LIMITS` becomes the literal three names and `config_migrate` is left alone; the key in `global_limits` or `limits`
is the strict schema's unknown-key error naming the block. The doctor already loads the configuration, so a bad value is its configuration failure; no other check is added.

### Needs

- No `Needs:` on any other change. The restack-lane change group 7 (occupancy) and `limits-split-into-global-and-project` group 9 (the queue-full line) edit the same slot-count lines and
  status wording; the overlap is textual, and whichever merges second resolves it in its rebase. This change is not held behind their unbuilt groups: its purpose is to stop urgent work
  waiting on the queue. Until the lane change lands there is no lane-run occupancy and the rule is written against today's counts (builds in flight and stored running); once it lands, the
  priority-0 units are part of the same occupancy figure with no further change.
- Also none for `a-unit-in-a-held-split-is-not-started` or `a-dropped-unit-parked-on-a-split-takes-no-place`: they edit code before the lines changed here.

### Alternatives rejected

A margin shared with lane runs (a lane run would delay urgent work), a quota counted from the limits, a reserved worker, any priority using the lane, and the lane's units holding back resumes.
