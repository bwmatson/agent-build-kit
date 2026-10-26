# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/` unless they name `tests/` or `docs/`.

- `pipeline/planner.py` `_check_dependencies` (about lines 404-445): every dependency must be in `known` (the store's unit ids) or in the plan.
  The cycle visit builds `index` from the plan's units only and follows a dependency only `if dependency in index`; its comment says a dependency
  outside the plan "is a unit already in flight or merged. It cannot close a cycle here: whatever it waits on is older still". That holds for a
  started or merged unit. It does not hold for a stored unit that has not started: its `depends_on` can point into the plan. `parse_plan`
  (line 85) calls `_check_dependencies(units, known or set())` with ids only, no edges, and raises `PlannerError` on a cycle.
- `cli/pipeline.py` `link_needs` (line 2000): runs every tick after planning and after `abk replan` (line 3370). It reads `group_needs` for every
  `tasks.md`, resolves each `Needs:` to the unit that covers the named group, appends it to the dependent's `depends_on` with
  `store.set_dependencies`, and for the `merged` qualifier fills `merge_before` (`set_merge_before`). There is no cycle check; a target already
  covered is simply linked.
- `pipeline/unit_store.py` `upsert` (line 449): the shape of a re-planned unit, including `depends_on`, comes from the new plan; state, branch and
  pull request come from the store. A unit absent from the plan is marked `unplanned` only if it is `planned`. So a re-planned unit's dependencies
  are overwritten by the plan, which is why `link_needs` runs every tick. A started unit is not proposed by the planner (it is shown as context), so
  its edges are not rewritten by `upsert`. UNVERIFIED: that no path hands a started unit back to `upsert` with new edges; the builder reads the
  call sites and the test below (a started unit's edges after a replan) proves it.
- `pipeline/planner.py` `PROMPT` (about lines 431-526) and `_in_flight_line` (line 560): for an unstarted in-flight unit the planner is shown "unstarted,
  <tier>, est N lines, builds <groups>, depends on <ids or nothing>". The prompt has no instruction about edges back into the new change.
- `cli/pipeline.py` `cmd_tags` (line 3212) validates one change's headings with `check_tags`; `cmd_check` (line 3235) is `openspec.check` and nothing
  else. Neither looks across changes. `group_needs(path)` (`pipeline/work_graph.py` line 518) is the one reader of `Needs:` lines.
- `cli/pipeline.py` `_blocked_lines`, `_ready_queue_lines`, `_nothing_started_reason` (lines 1548, 1557, 1640): a planned unit that waits is `blocked:
  <id> waits on <ids>` when it has work, otherwise it is absent; the reason a pass starts nothing is "queue is full" or "nothing ready to build". A
  planned cycle with no work in it is none of these, so the status is quiet.
- `grep -rn cycle src` finds no other detection. UNVERIFIED: any check in `serve/` or `diagram.py`; the grep found none.

`needs-start-on-the-parents-branch` (planned, unstarted) removes `merge_before` and the `merged` qualifier and rewrites `waiting_on`. This change
never reads `merge_before` or `waiting_on`; it reads `depends_on` and the declared `Needs:` pairs only, so no `Needs:` is needed in either direction.

## The graph the check runs over

One pure function, `find_cycle(edges)`, in a new `pipeline/cycles.py`: it takes a mapping from unit id to the ids it depends on and returns the
first cycle as an ordered list of ids closing on its first (`A -> B -> A`), or none. It is iterative, deterministic (units visited in sorted
order, dependencies in stored order) and has no store, clock or I/O, so every scenario below is a fake graph in a dict.

The graph is every unit that is not finished: a unit that is merged or closed is left out (its work is done, nothing waits on it), and a satisfied
unit is left in, since what depends on it waits on what it was built on. Started units are in the graph: a failed or held unit that waits on a
planned one can sit in a real cycle. `depends_on` is the edge set, whether it came from the planner or from a `Needs:` line (`link_needs` writes
the latter into `depends_on`); `merge_before` is a subset of those ids and adds no edge.

Edges are tagged by origin where the check needs to choose: **fixed** (a stored edge, or an explicit `Needs:` edge) and **advisory** (an edge from
the plan being parsed). The tag lives only for the call; nothing is stored. (The `needs` field `needs-start-on-the-parents-branch` adds would
let a stored edge be told from a planner edge; this change does not wait for it, and rebuilds the same fact from `tasks.md` when it needs it.)

## When a plan is parsed

`plan_all` gains a step after `parse_plan` and before `upsert`: `drop_cycle_edges(plan_units, stored_units, declared_needs)`.

- The base graph is every stored unit's `depends_on` except those of the change being planned that are `planned` (their edges are what this plan is
  replacing), plus the declared `Needs:` edges that point from a unit of another change into a unit of this plan. The latter is the case that was
  missed: the first change was planned while the second's unit had its `Needs:` edge still to be applied. The declared edges come from
  `group_needs` over every `tasks.md`, resolved against the stored units and this plan's units by the group each unit covers, exactly as `link_needs`
  resolves them; one that names a group nothing covers yet adds no edge.
- Every advisory edge of the plan is then added one at a time, in the plan's order (units as listed, dependencies as listed), after the fixed edges.
  An edge whose addition would close a cycle is dropped from the unit, and one log line names it: `<unit>: planner edge to <dep> dropped, it would
  close the cycle <unit> -> <dep> -> ... -> <unit>`. The rest of the plan stands. Adding in a fixed order means the same inputs drop the same edges.
- If a cycle exists with only fixed edges, nothing can be dropped: the plan still stands (the units are real), the cycle is logged as an error line
  naming it, and `abk replan` for that change exits non-zero with it. The status reports it as a deadlock (below) until a person edits a `Needs:` line.
- An in-plan cycle among the plan's own advisory edges still raises `PlannerError` from `_check_dependencies` as today and is retried by the
  planner's existing refusal path; this change does not alter it.
- A dropped edge can strand the order the planner meant (two units that share a file now both stack on their own parents). That is the cost of the
  rule; it is the planner's advisory ordering, and the cycle it would have made orders nothing. UNVERIFIED: that dropping never leaves an `[acceptance]` or `[narrow]` unit
  without a predecessor its own checks require. `_check_acceptance`/`_check_independent` run in `parse_plan` before the drop, and a cross-change
  edge is not one they require, but the builder runs them after the drop too and refuses the plan if one now fails.

## When `link_needs` adds an edge

`link_needs` applies each change's `Needs:` dependencies unit by unit. Before an edge is added to `depends_on`, `find_cycle` runs over the graph with
the edges linked so far in this call. An edge that would close a cycle is not added: the unit keeps its previous dependencies (every other edge
of that unit is still applied), one line names the refused edge and the cycle, and the call returns the refusals so `abk replan` can exit non-zero.
`abk tick` logs the refusal and carries on (a tick never fails for a task-group problem, as for a plan refused for tags); it logs a given refusal
once per pass.

An edge already stored (a state older versions wrote) is not removed by a refusal: `link_needs` is idempotent and leaves what is there alone, so
a deadlock already in the store is reported by the status and is not silently rewritten.

## A `Needs:` cycle before any planning

`abk tags <change>` and `abk tags --all` gain one cross-change check, and `abk check` runs the same after `openspec validate`. The graph is by group:
nodes are `(change, group)` for every group of every `tasks.md`; edges are every `Needs:` line, and the order within a change (group n depends on
group n-1) except where the group is `Independent:`. A cycle there is a problem in each change that has a `Needs:` line on it, printed as
`<change>: Needs: cycle <change> group <n> -> ... `, counted in the "N problem(s)" total and exit 1. It is the one place two valid files are
found to disagree before the planner runs. This finds only what `tasks.md` can show; a planner edge is not in `tasks.md`, which is what the
planning check is for. UNVERIFIED: that the planner always chains a change's groups in order (joins and `Independent:` aside), so the check counts
the within-change order as an edge; a cycle through it is real only for groups that stay separate units, and the builder keeps the check to
`Needs:` plus the within-change order of consecutive groups only.

## A deadlock that already exists

`abk status` and the reason a pass starts nothing run `find_cycle` over the stored graph (units not finished, `depends_on` only). Each cycle is
listed once, from its smallest id: `deadlocked: A -> B -> A (3 planned units wait on each other and cannot start)`; each unit in it is also marked
with that reason in the ready-queue report, and a unit that waits on a deadlocked one is reported as waiting on it. A pass that starts nothing
while a deadlock exists says `nothing can start: deadlocked ...` ahead of "nothing ready to build", and never "queue is full" because of units in
a cycle. A deadlock is derived from the stored graph each time, never stored, so editing the edge out ends it with no migration. Nothing
auto-breaks it: a person replans (the planner edge is dropped by the check above) or edits the `Needs:` line, and `no auto-retry` is unaffected.

## The planner's prompt

The prompt gains one rule, near the in-flight units paragraph: a unit shown as unstarted with "depends on ..." must not be given a dependency, directly
or through other units, on a unit of the change being planned; nothing earlier waits for a unit of this change. `_in_flight_line` already prints
the dependencies; it needs no change. The prompt is a hint: a planner that ignores it is corrected by the drop, and the tests do not depend on the
model's obedience.

## A replan and stored edges

`upsert` overwrites a re-planned, unstarted unit's `depends_on` from the plan, so a planner edge dropped for a cycle disappears from the stored unit
on the replan with nothing further: the new plan simply does not carry it. The test proves it with an edge stored by the old rules. A started unit
(running, in review, failed, held, merged) is not re-planned; its edges are never changed by this check, by `link_needs`'s refusal or by a replan;
if one sits in a cycle it is reported, not edited.

## Docs

`docs/unit-graph.md` gains a "Cycles" section (what is dropped, what is refused, what is reported, the status line); `docs/architecture.md`'s
planning section says the plan's edges are checked against the whole graph and that `Needs:` edges are checked as they are linked; the
`abk-pipeline` skill's status section gains `deadlocked:`; the `abk-authoring` skill's `Needs:` section says a cycle is an error. One changelog bullet.

## Related changes

`needs-start-on-the-parents-branch`: no ordering; this change is stated in `depends_on` and `Needs:` and holds before and after it.
`blocked-units-free-their-slot` and `failed-units-waiting-on-a-prerequisite-free-their-slot`: unaffected; a deadlocked unit that has work is already
"blocked" there and stays so, now with the cycle named. `an-internet-outage-is-not-a-failure`: unrelated.
