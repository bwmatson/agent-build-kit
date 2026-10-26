# Proposal

## Why

`Needs: <change> group <n>` adds a dependency. `Needs: <change> group <n> merged` adds one more
thing: the dependent also waits for the parent's pull request to merge and then starts on the trunk,
not on the parent's branch. The second form exists for a parent that is "still reshaping what this
group builds on". In practice a dependent can start on the parent's reviewed branch: the parent has
been through its build and review loop, and if review changes it, the dependent follows it the way
any stacked unit does (it goes back to planned, then restacks). The merge gate only adds idle time:
a dependent sits for the length of a human review of a pull request it could have been built on.

It also costs the framework a second kind of edge: `merge_before` on the unit, a thick edge in the
graph, a `gated` requeue path, a `merged` qualifier in the grammar with its own rejection rule, and
an exception in `base_of` and `through_satisfied` for an edge that is not a base. Thirty-five
`Needs: ... merged` lines exist today in twenty-one open changes; most of them say the dependent
edits the same file as the parent, which is a reason to order them, not to wait for a merge.

## What Changes

- **A `Needs:` line is only a dependency.** The dependent is held until the parent is through its
  build and review loop (in review, merged or satisfied) and starts on the parent's branch, as an
  ordinary same-repo dependency does. A parent sent back for rework or failed holds it, as for any
  dependency.
- **A cross-repo parent still has to merge.** It cannot be stacked on; this is the rule that
  already applies to a cross-repo dependency, now stated for `Needs:` too.
- **The `merged` qualifier goes.** It is accepted as a no-op with a warning from `abk tags` and
  `abk check`, so no open change stops planning; the same change rewrites the existing lines.
- **The graph keeps the thick edge for `Needs:` lines**, which tells them from the planner's own
  inferred edges, and labels it `needs` (`==>|needs|`) instead of `merged`.
- **Started units** (failed, held, running, in review) that gain a `Needs:` dependency follow the
  ordinary dependency rules instead of a merge gate; see the design for how.
- **A stored `merge_before` is dropped.** The field leaves the unit; a store that still carries it
  loads, and the next write omits it.

## Impact

- agent-build-kit: `pipeline/work_graph.py`, `pipeline/units.py`, `pipeline/unit_store.py`,
  `pipeline/diagram.py`, `pipeline/flakes.py`, `cli/pipeline.py` (`link_needs`, requeue, the gate
  release), `serve/server.py`, the docs and two skills.
- Planning repo: 21 open changes have their `Needs: ... merged` lines rewritten (last task).
- Behaviour change for open work: dependents of a `merged` parent now start when the parent is in
  review, not when it has merged. Those dependents stack on the parent's branch.
- Capability `unit-scheduling`: two requirements removed and replaced, one removed outright, one
  modified.
