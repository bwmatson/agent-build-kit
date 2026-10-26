## Why

A replan that regroups gives its unstarted units new ids: `plan-x/2` and `plan-x/3` became `plan-x/4` and `plan-x/5`, and the old two went to
`unplanned`. A unit that had started keeps its id and its stored dependencies too: a replan rebuilds the `depends_on` of an unstarted unit and never
touches a started one's, and `link_needs` resolves `Needs: <change> group N` to the unit that covers the group now but only adds edges. So a started
unit keeps an edge to a replaced unit for good.

Most of those replacements were pure renumbering: the planner model chose the ids, so the same groups got a new id. `unit-ids-come-from-the-groups`
(its own change) makes the program name a unit from its lowest group and keep the id of an unstarted unit with the same groups, which prevents them.
What is left here is a genuine regroup (a join or split changes the group set) and the one-time case of a stored unit whose groups match no plan unit.

It happened. A unit stored a dependency on `tier2-tests-are-tagged-by-runtime/5`; a replan turned that unit `unplanned` (its group is now carried by
`/12`), and the dependent bounced about twelve times in a day and a half, because the step guard read the unplanned parent as one that "went back".
`a-dropped-parent-does-not-hold-its-child` fixes the guard and drops an edge to a unit that builds nothing. That is right when the work is gone; here a live unit carries it, and dropping the edge would let the dependent run without waiting. Two units still depend on the replaced unit today.

The stable identity of the work is `(change, group)`, not the unit id. Ids stay readable (branches, threads, titles, logs and requeue commands carry
them), so for a real regroup the fix is to remember which units carry the groups now and read every reference through that.

## What Changes

- **A replaced unit records its successors** (a real regroup or the legacy case). A new optional field `superseded_by` (unit ids, usually one) is written in the same store write that turns a
  unit `unplanned`, from the plan: every live unit whose groups intersect the replaced unit's `(change, group)` pairs. Nothing carrying them leaves it
  empty and the unit is simply dropped. `retired` units share it.
- **One resolver.** `current_dependencies(unit, graph)` returns a unit's dependencies with each edge to a replaced unit followed through `superseded_by`
  (chains, cycle-safe, bounded). `through_satisfied`, `waiting_on_me`, `satisfied_landed` and the other direct readers of `depends_on` use it, so the
  scheduler, the build guard, the follow pass, the restack and the diagram all read the successor, with no change to the ones that go through
  `through_satisfied`.
- **A tick repoints the stored edge.** `link_needs` rewrites a stored dependency on a replaced unit to its successor, for a started unit too, and logs
  `<unit>: dependency <old> is now <new> (replaced by a replan)`. A join repoints every field that names the unit it takes in.
- **A recorded wait follows the successor** (`waited_on`, the planner's in-flight lines); history notes stay as written.
- **Display.** `abk replan` says `now unplanned, replaced by <unit>`; `abk status`, the graph page and the diagram show it.
- **Backfill.** Units replaced before the field existed get theirs once, idempotently.

## Impact

- agent-build-kit: `units.py`, `unit_store.py`, `events.py`, `diagram.py`, `retirement.py`, `joins.py`, `cycles.py`, `planner.py`, `split/copy.py`,
  `serve/server.py`, `cli/pipeline.py`, the documents, the `abk-pipeline` skill and the changelog.
- No hash ids, no branch renames, no rewriting of history notes, no `Needs:` on other changes (the overlap with four changes is textual; design.md).
- Priority 0: a started unit can bounce on a stale edge indefinitely; fixing the guard alone would let it run ahead of unbuilt work.
