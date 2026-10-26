# Tasks

Acceptance: none — the graph check, the linking and the reports are pure over a unit graph and a fake plan; tier-1 tests prove each case and nothing a consumer drives changes.

Priority: 2

## 1. [agent-build-kit] [tier1] A dependency that would close a cycle is dropped or refused

Done when `find_cycle` names a cycle in any dependency graph and no false one in a chain or a diamond, a plan's planner edge that would close a cycle with a stored unit is dropped and logged, an explicit `Needs:` edge that would close one is refused and named, and a replan clears a stale planner edge from an unstarted unit and leaves a started unit's edges alone. Estimate: about 520 changed lines.

- [x] 1.1 Test: `find_cycle` on a plain dict returns `A -> B -> A` for a two-unit cycle, the three-unit cycle `A -> B -> C -> A` across three changes, a self edge, and a cycle reached from a unit outside it; it returns none for a chain, a diamond (`D -> B, C; B, C -> A`), two units sharing a parent and an empty graph; it is deterministic (the same cycle for the same input in any key order).
- [x] 1.2 Test: the exact case. Change `checks-hold-unit` is stored with unit 2 depending on unit 1, and its `tasks.md` has `Needs: checks-add-setting group 1`; the planner for `checks-add-setting` returns unit 1 with an edge to `checks-hold-unit/2`. `drop_cycle_edges` drops that edge, one log line names `checks-add-setting/1 -> checks-hold-unit/2 -> checks-hold-unit/1 -> checks-add-setting/1`, and the plan's unit 1 has no dependency and is ready after `link_needs`.
- [x] 1.3 Test: a planner edge that closes a cycle only through a stored unit's own planner edge (no `Needs:` involved) is dropped the same way, and a planner edge to a stored unit that closes no cycle is kept; edges are tried in the plan's order, so the same input drops the same edge twice.
- [x] 1.4 Test: a cycle among the declared `Needs:` edges alone, with no planner edge in it, drops nothing: the plan still stands and is returned unchanged, the cycle is returned as an error, `abk replan` for that change exits non-zero printing it, and a tick logs it and does not fail.
- [x] 1.5 Test: `link_needs` with a `Needs:` line whose edge would close a cycle with stored edges leaves that unit's `depends_on` exactly as it was, still links every other `Needs:` of the same unit, and logs one line naming the refused edge and the cycle; a `Needs:` that closes no cycle (a chain across three changes, a diamond) is linked as today.
- [x] 1.6 Test: a longer cycle across three changes, each unit's edge being a `Needs:` line or a stored planner edge, is found by whichever of `drop_cycle_edges` and `link_needs` completes it, and a cycle already in the store when `link_needs` runs is left alone (nothing is removed) and not refused.
- [x] 1.7 Test: a replan of a change whose unstarted unit stores an old planner edge that closed a cycle replaces the stored `depends_on` with the plan's, so the stale edge is gone; the unit's state, branch and history are the same. A started unit (running, in review, failed, held and merged) of the same change keeps its `depends_on`, and a refused `Needs:` or a drop never edits it.
- [x] 1.8 Add `pipeline/cycles.py` with `find_cycle(edges)` and `drop_cycle_edges(plan_units, stored_units, declared_needs)` (fixed and advisory edges, finished units left out), pure over its arguments.
- [x] 1.9 In `plan_all`, resolve the declared `Needs:` pairs with `group_needs` the way `link_needs` does and call `drop_cycle_edges` after `parse_plan` and before `upsert`, re-running the acceptance and independence checks on the result; log each drop and return the fixed-edge cycle in `PlanResult`.
- [x] 1.10 In `link_needs`, check each edge with `find_cycle` before adding it, return the refusals and log them once per pass, and make `abk replan` print them and exit non-zero; leave a stored edge alone.

## 2. [agent-build-kit] [tier1] A cycle is reported before planning, in the status, and avoided by the planner

Done when `abk tags` and `abk check` name a `Needs:` cycle across changes, `abk status` and the reason a pass starts nothing list a stored deadlock once per cycle and never as a full queue or idle, and the planner is told not to close one. Estimate: about 420 changed lines.

- [x] 2.1 Test: `abk tags --all` over two changes whose `Needs:` lines form a cycle (`checks-add-setting` group 2 needs `checks-hold-unit` group 1, which needs `checks-add-setting` group 2) prints the cycle under each change, counts it as a problem and exits 1; a change whose `Needs:` lines form a chain or a diamond is clean; `abk tags <change>` for one of the two names the same cycle; `abk check` prints it after the OpenSpec output and exits non-zero.
- [x] 2.2 Test: `Needs:` on a group of the change's own, an `Independent:` group (no within-change edge) and a `Needs:` naming a change that does not exist add no cycle and no new message, so the existing checks' output is unchanged.
- [x] 2.3 Test: `abk status` with a stored graph `A/1 -> B/2 -> A/1` of planned units prints `deadlocked: A/1 -> B/2 -> A/1` once, not once per unit, and a graph with two separate cycles prints two lines; with no cycle it prints nothing new.
- [x] 2.4 Test: with a deadlock, a pass that starts nothing says `nothing can start: deadlocked: ...` and not "queue is full" or "nothing ready to build"; the ready-queue report gives each unit in the cycle that reason, and a unit waiting on one of them is reported as waiting on it; units outside the cycle start as usual.
- [x] 2.5 Test: removing one edge of the stored cycle ends the report on the next status with nothing stored or migrated, and a chain of planned units with no cycle is never reported as deadlocked.
- [x] 2.6 Test: the planner prompt contains the rule that a unit shown as unstarted must not be made to depend, directly or through others, on a unit of the change being planned, beside the in-flight units paragraph; and a plan that ignores it is still corrected by group 1's drop (the prompt is not what the tests rely on).
- [x] 2.7 Add the cross-change `Needs:` cycle check to `abk tags` (all and one change) and to `abk check`, built on `find_cycle` over `(change, group)` nodes, the `Needs:` lines and the order of consecutive groups that are not `Independent:`.
- [x] 2.8 Add `deadlocks(units)` over the stored graph, print `deadlocked:` lines in `abk status`, put the cycle first in `_nothing_started_reason` and give each unit in it the reason in the ready-queue report.
- [x] 2.9 Add the rule to `PROMPT` in `pipeline/planner.py` and leave `_in_flight_line` as it is.
- [x] 2.10 Document it: a "Cycles" section in `docs/unit-graph.md`, the planning paragraph of `docs/architecture.md`, the status section of the `abk-pipeline` skill (`deadlocked:`), the `Needs:` section of the `abk-authoring` skill (a cycle is an error, `abk tags` finds it), and add one bullet under `## Unreleased` as `AGENTS.md`'s Changelog section says, folding group 1 into it.
