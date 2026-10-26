# Proposal

## Why

Two changes were planned separately. The second wrote `Needs: <first> group 1 merged` on its group 1, so its first unit depends on the first's
first unit once both are planned. The planner, planning the first change while the second's units were already stored and unstarted, also gave
the first change's unit a dependency on the second's unit, because the two touch the same files. The result was a cycle across two changes:

```
checks-add-setting/1 -> checks-hold-unit/2 -> checks-hold-unit/1 -> checks-add-setting/1
```

None of the three could ever start. Nothing reported it: the queue was not full, the units were planned and waiting, so the status read as
an ordinary wait. It also held up a priority-1 chain whose planner edge pointed behind that cycle. It was found by reading `units.json` by hand,
and fixed by replanning both changes (the planner dropped the edges the second time).

The pipeline has a cycle check, and it did not fire, for two reasons:

- It sees only the plan being parsed. A dependency outside the plan is assumed to be a unit "already in flight or merged ... older still", so it
  cannot close a cycle. That is false for a unit of another change that has been planned but not started: it can depend, through its own planner
  edge or a `Needs:` edge, on a unit of the change being planned now.
- `Needs:` edges are applied after planning, by `link_needs`, one change at a time, with no cycle check, so two valid `tasks.md` files can
  together produce a cycle that neither plan, nor the linking, ever notices.

A cycle schedules nothing and says nothing, which is the worst way for a pipeline to fail.

## What Changes

- **A planner edge never closes a cycle.** After a plan is parsed, its edges are checked against the whole graph of units that are not finished
  (every change's stored units, this plan's units, and the `Needs:` edges `tasks.md` declares toward them). An edge that would close a cycle is
  dropped, the drop is logged naming the cycle, and the plan stands. The planner's edges are advisory ordering; an explicit `Needs:` edge is never
  dropped for a planner edge.
- **An explicit `Needs:` edge that closes a cycle is refused.** `link_needs` leaves the unit with the dependencies it had, names the cycle, and
  `abk replan` exits non-zero. If the cycle is made of explicit edges only, nothing can be dropped, so the plan stands and the change is reported.
- **A cycle in `Needs:` lines alone is a spec error.** `abk tags` and `abk check` find it across changes before anything is planned.
- **A deadlock that exists anyway is reported.** State written by an older version, or a race between two plans, can leave planned units waiting
  on each other. `abk status` lists each cycle once as `deadlocked: A -> B -> A`, and says why those units are not ready, never "queue full" or
  "nothing ready".
- **A replan clears a stale planner edge** from a unit that has not started; a started unit's edges are never changed.
- **The planner is told** that a unit listed as unstarted with its "depends on" must not be made to wait, directly or through others, on the
  change being planned. A hint only: the check above is the guarantee.
- **Written in terms of `depends_on` and `Needs:`,** so it holds before and after `needs-start-on-the-parents-branch` removes `merge_before`.

## Impact

- agent-build-kit: the graph check in `pipeline/planner.py` and a new pure helper for it, `link_needs` in `cli/pipeline.py`, `plan_all` and
  `abk replan`, `abk tags`/`abk check`, the status, the planner prompt, the unit-graph and architecture documents, the pipeline skill, the changelog.
- Spec: `unit-scheduling` (adds six requirements).
