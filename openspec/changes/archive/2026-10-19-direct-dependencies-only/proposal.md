# Proposal

## Why

Units list redundant ancestors as dependencies: when C needs B and B needs A, C's stored `depends_on` can also name A. In the live store 73 of 352
edges are of that kind (one unit lists 11 of 18, another 8 of 9). The graph page, the web Dependencies list, `abk status` and the pull request body
show them all, so a reader cannot tell the dependency that matters from the ones it implies, and a pull request body tells a reviewer to merge units
that its own parent already requires first. The edges come from the planner's own prompt, which asks an `[acceptance]` unit to depend on every unit
building the change's other groups, from `plan_units`, which gives an acceptance or narrow unit every earlier unit once an `Independent:` group
exists, and from `link_needs`, which appends a `Needs:` target whenever it is not listed directly even when the chain already implies it, on every
tick. Storing only the direct edges removes the clutter at its source. It is safe where the reachability the scheduler reads is kept, and the code
read for this change shows the one place a redundant edge does work that reachability does not: an acceptance or narrow unit's wait on every earlier
unit of its change, including one sent back for rework while its own parent is in review. That one is kept, as a run-time rule.

## What Changes

- **`direct_dependencies`.** One function in `pipeline/units.py` returns the transitive reduction of a unit's stored dependencies over the stored
  graph, same-repo and cross-repo paths alike, in the stored order. A dependency another listed dependency reaches is dropped; a diamond keeps both
  parents.
- **The store keeps the reduced list.** `upsert`, `set_dependencies` and the repointing a join does write the reduced list. The existing store is
  reduced once, at the next tick or replan, through `set_dependencies`, never by editing `runs/units.json`.
- **An acceptance or narrow unit waits at run time.** `waiting_on`, the running-build stop (`upstream_incomplete`) and `follow_predecessors` add, for a
  unit whose flag is `acceptance` or `narrow`, every earlier unit of its change that is not in review, merged or satisfied, computed from the change's
  units and not from stored edges. Every other unit follows the chain: a grandparent sent back reaches the grandchild by the parent's restack and the
  child's following of its predecessor.
- **`Needs:` stays its own field.** `link_needs` tests reachability, so a target the chain already implies is not linked again each tick; the stored
  `needs` names every declared target; a `Needs:` the chain implies draws no edge.
- **A started unit's base does not depend on list order.** It is chosen as an unstarted unit's is, and the predecessor a thread is told about is
  chosen the same way.
- **The planner and `plan_units` name the units an acceptance or narrow unit exercises**, not every unit.
- **Everything shows the same edges.** The graph page draws only direct edges and a merged parent only for a kept edge; the web Dependencies list,
  `abk status` waiting lines, the "Merge ... first" list of the pull request body, the replan "now depends on" lines and the planner's in-flight lines
  use `direct_dependencies`.
- **Documents.** `docs/unit-graph.md`, the `abk-pipeline` and `abk-authoring` skills and the changelog.

## Impact

- agent-build-kit: `pipeline/units.py`, `pipeline/unit_store.py`, `pipeline/events.py` (tests only, and the dependents sets), `pipeline/joins.py`,
  `pipeline/wiring.py`, `pipeline/planner.py`, `pipeline/diagram.py`, `serve/server.py`, `pipeline/pr_body.py`, `cli/pipeline.py`, the tests that
  mirror them, `docs/unit-graph.md`, the two skills and `CHANGELOG.md`.
- Behaviour that changes and is accepted: a grandchild is no longer held by a grandparent that is planned, running, failed, held or closed while its
  parent is in review (a closed ancestor no longer stalls its listed descendants for good), and a restack of a child already moved with its parent is
  no longer repeated; design.md lists each with what is done about it. Behaviour that does not change on the live store: which units are ready, in
  progress, uncounted or failed waiting, and their order.
- `Priority: 3`. No `Needs:` on another change: the code edited here exists on `origin/main`. `limits-split-into-global-and-project` edits
  `plan_units`, the planner prompt and the graph page in other places and does not create anything this change reads.
