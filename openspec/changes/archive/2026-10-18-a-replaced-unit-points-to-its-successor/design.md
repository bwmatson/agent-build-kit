## Context

Written against agent-build-kit `origin/main` (`f9f53b4c`).

Most past replacements were renumbering by the planner model, which `unit-ids-come-from-the-groups` prevents: the program names a unit from its lowest group and an unstarted unit with the same groups keeps its id. `superseded_by` is for what remains: a join or split that changes the group set, and the one-time case, at the first replan after that release, of a stored unit whose groups match no plan unit.

A unit is `Unit` (the plan's shape) and `StoredUnit` (it plus what happened). A replan (`UnitStore.upsert`, 627) rebuilds the shape of every unit in the
plan and sets an unstarted planned unit of the change that the plan omits to `unplanned` (740-745); a started unit is never demoted. `UnitStore.join`
(821) deletes the unit it takes in and repoints `depends_on` of every unit onto the one that took it. `link_needs` (cli/pipeline.py 2950) runs each tick
after planning (1536) and in `abk replan` (5070).

## The field

`superseded_by: tuple[str, ...] = ()` on `Unit`, beside `promoted_from`: the pure functions in `units.py` read a graph of `Unit`s, so the field has to be
there, and a plan never sets it. It is omitted from the record when empty (`_record`, with `promoted_from`), so a store with no replaced unit is the one
an earlier release writes and reads. A record that holds it is refused by a release that does not know it, as every later field is
(`_tolerate_other_releases`: a valued unknown key is "a newer release wrote it").

### The successors

`successors_of(unit, units)` (pure, `units.py`) is the ids of the units in `units` other than `unit` whose state is not in `BUILDS_NOTHING` or `closed`
and whose `(change, group)` pairs (own and joined, the `_carries` of `unit_store.py`) intersect the pairs `unit` carries, in id order. A `merged` or
`satisfied` unit is included: the work is covered, and readers already treat a finished parent as done. A `closed` unit is left out (its groups are
free). Joined groups of other changes count, as `_orphaned_changes` treats them.

It is computed on the store as it will be after the write that makes the change:

| Write | Units that get a successor set |
|---|---|
| `upsert(change=...)`, after the demotion loop | each `unplanned` or `retired` unit of that change with an empty field |
| `unplan_vanished` | the units it sets `unplanned` (usually none carried) |
| `join` | none: the unit taken in is deleted and the same write repoints references to it |
| `backfill_successors()` (new, each tick before linking) | every `unplanned` or `retired` unit with an empty field |

A non-empty field is never overwritten (chains cover a later replacement). The demotion's history entry carries the note
`replaced by <ids>` (`_with_state` gains an optional note). `upsert` does not carry the field across a rebuild: a
unit in the plan is live, and one revived from `unplanned` must lose it, so the standing-cause requirement's kept fields omit it, and a test pins that. A retired unit is skipped by `upsert` and keeps its field.

## The resolver

`resolve_replaced(unit_id, graph) -> tuple[str, ...]` is the ids that stand in for one id. A unit that is absent, not in `BUILDS_NOTHING`, or has no
successors stands for itself. Otherwise it is the concatenation of the resolution of each successor, depth at most `REPLACED_DEPTH = 8`, a `seen` set
against a cycle (a repeated id contributes nothing; an empty result falls back to the id itself). A dead end stands for itself, and the readers that skip
a unit that builds nothing skip it; there `a-dropped-parent-does-not-hold-its-child` takes over.

`current_dependencies(unit, graph)` is `unit.depends_on` with each entry resolved, de-duplicated, never the unit itself, order kept. It drops nothing
else: a merged or satisfied successor stays, and every reader already treats a finished parent as done (`waiting_on` waits only for a same-repo parent
outside `REVIEWED` and a cross-repo one that has not landed; `base_of` and `depth_of` count only `IN_REVIEW`).

## The readers

| Reader | Verdict |
|---|---|
| `through_satisfied` (units.py 342), the input of `base_of`, `open_parents`, `_builds_on`, `depth_of`, `_parent_went_back`, `followed_dependencies`, `second_open_parents` | CHANGE: start from `current_dependencies` (and use it for a satisfied parent's own list). This one edit moves every reader below |
| `waiting_on_me` (386), so `effective_priority`, promotion, the planner's `waiters` | CHANGE: the dependents map is built from `current_dependencies(other)` |
| `satisfied_landed` (613), so `archive.py` | CHANGE: same |
| `waiting_on`, `blocked`, `ready_units`, `earlier_units`, `wiring.build_upstream_incomplete`, `why_branch_is_changing`, `follow_predecessors`, the merge-base walk (3009), `predecessor` (3151), `pr_body._unmerged`, `restack_lane`, the plan's own checks in `planner.py` | works unchanged, through `through_satisfied`/`followed_dependencies` or on the plan's own units |
| `events._children_of`, `_dependents_of` (801, 827) | CHANGE: the literal `unit.depends_on` beside `through_satisfied` becomes `current_dependencies` |
| `retirement._refusal`, `assess` (79, 99) | CHANGE: `unit_id in current_dependencies(other)`, so a dependent whose edge names a replaced unit counts as stacked on its successor |
| `joins.py` dependents of `onto` (115, 151) | CHANGE: counted by `current_dependencies`; `_repointed` stays (the plan's own edges) |
| `cycles.py` stored graph (98) | CHANGE: edges are `current_dependencies`, so a cycle through a successor is found; the plan's own edges (117) work |
| `planner.in_flight_item`, `_in_flight_line` (783, 812) | CHANGE: an unstarted unit's `depends_on` is `current_dependencies`; a replaced unit's line reads `(unplanned) replaced by <ids>` and still says what it builds |
| `diagram.py` parents (96) and edges (161) | CHANGE: both from `current_dependencies`; the `needs` thick edge compares the resolved id |
| `cli/pipeline.py link_needs` (2973-3004), `wait_reasons` (5573) | CHANGE: the cycle graphs and the open-parent test use `current_dependencies`; the repoint is its own pass |
| `cli/pipeline.py requeue_wait_ended` (1850), `waited_on` | CHANGE: each recorded id is resolved before it is judged (below) |
| `_replan_differences` (5162) | works for the edges (it diffs stored lists); CHANGE the line `now unplanned` to say `replaced by` |
| `serve/server.py` `related(unit.depends_on)` (304), the unit summary | CHANGE: resolved ids, and `replaced_by` on the summary |
| `split/copy.py` (145, 177) | CHANGE: `superseded_by` joins `depends_on` and `needs` in the dangling and moved-edge checks |
| `unit_store.join` (856), `joins` | CHANGE: one helper repoints `depends_on`, `needs`, `waited_on` and `superseded_by` of every unit from the unit taken in to `onto` |

## Rewriting on link

`link_needs` gets a pass before its per-unit loop, for every unit that is neither finished nor in `BUILDS_NOTHING`, started or not. For each stored
`depends_on` entry `d` that is a replaced unit with successors: the live targets of `resolve_replaced(d)` (leaves that build nothing are left out) are
narrowed to the ones the unit's `Needs:` lines resolve to (`wanted[unit]`) when any are, else all: edges follow the groups a dependent declares, and one that declares none depended on the unit as a whole. A split into two therefore gives a planner edge two targets and a `Needs: x group 3` edge
only the target carrying group 3. A target that closes a cycle is refused, logged and reported as the existing check does (`path_between` on the
resolved graph) and the others are kept; with none kept the old edge stays. The entry is replaced in place, de-duplicated, written by
`set_dependencies`, and logged `<unit>: dependency <old> is now <new> (replaced by a replan)`.
The pass is idempotent. `needs` needs no pass: the loop already recomputes it from `wanted` each tick, so it names the live carrier or nothing.

An entry with no successors is the other change's: its drop pass removes a stored edge on a unit that builds nothing when no `Needs:` line declares it.
The rewrite runs first, so the drop pass never sees an edge that has a successor. Built before it, this pass stands alone and an edge with no successor
stays, as today; built after it, the drop pass is edited to run after the rewrite. Its tests set no `superseded_by`, so they pass in either order.

## Other references by unit id

| Where | Verdict |
|---|---|
| `waited_on`, `wait_ended` | RESOLVE at read: `waiting_on` already lists the successor, so `waited_on` is rewritten to it while the wait lasts; when the successor is already reviewed, each recorded id is resolved before the closed test, so the unit is requeued, not failed with a `wait_ended` for a unit that was only replaced. A dead end still counts as closed |
| `predecessor_note`, `feedback`, `guidance`, history notes | text: left as written |
| `gated_requeue`, `needs` | a mode, no id; `needs` is recomputed each tick |
| the planner's in-flight lines | RESOLVE (above) |
| `runs/planned.json` | by change; a refused record's `units` are diagnostics: left |
| `decisions.jsonl`, `usage-ledger.jsonl`, run logs | history: left |
| restack lane records, leases, `landing.json`, reviews, `notifications.json`, unit-graph threads, `e2e-held.json` | keyed by started units (which keep their ids) or by no unit: left |
| serve API | RESOLVE (table) |

## Display

`abk replan` prints `<unit>: now unplanned, replaced by <ids>`. `abk status` prints `  replaced: <unit> by <ids>` only while an unfinished unit's
`depends_on`, `needs` or `waited_on` still names one (normally never: the pass above runs first). The graph data gives a replaced unit `replaced_by`.

## Backfill

`UnitStore.backfill_successors()` runs as a tick step before linking: for every `unplanned` or `retired` unit with an empty field it applies
`successors_of` to the whole store, in one write, and logs `successors recorded: <n> unit(s)` when it wrote any. A unit nothing carries stays empty; one with successors is not rewritten. It also covers a retire whose groups a later plan re-carries; the two units that depend on a replaced
unit today are repointed by the link pass of the same tick, and it also handles the legacy renumbering `unit-ids-come-from-the-groups` leaves.

## Composition

- **unit-ids-come-from-the-groups** (unbuilt): ids follow the groups, so a replan with the same groups replaces nothing and records no successor; a join
  or split, and a legacy unit that matches no plan unit, are replaced as above. The overlap is textual; neither has a `Needs:`.
- **a-dropped-parent-does-not-hold-its-child** (unbuilt): above.
- **a-started-unit-keeps-its-groups** (in main: `abk retire`, the `retired` state): a retired unit is a replaced unit whose field is empty unless its
  groups are carried again; both states are in `BUILDS_NOTHING` and share the resolver.
- **a-standing-cause-survives-replans-and-no-cause-changes** (archived): `upsert` carries runtime fields by listing them; this field is deliberately not
  listed (above), and a test pins that.
- **a-unit-over-its-tier-is-held-and-split** (unbuilt): it closes a superseded unit and repoints its dependents itself; a `closed` unit gets no field.
