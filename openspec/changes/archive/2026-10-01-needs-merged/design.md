# Design

## Grammar

`NEEDS_LINE` today is `Needs: <change> group <n>` followed by anything. The
qualifier is a single word straight after the group number, before the reason:

    Needs: acp-runtime-adapter group 4 merged — it is still reshaping what this wraps

Any other word there is not a qualifier and is read as the start of the
reason, as now. `abk tags` reports a `merged` qualifier on a group that names
its own change, since groups of one change are ordered already.

## Recording it

`link_needs` turns each `Needs:` into a `depends_on` entry on the dependent
unit. It also records the merge-gated ones in a second tuple on the stored
unit, `merge_before`, which is a subset of `depends_on`. The default is empty,
so every stored unit loads unchanged. Re-planning recomputes it from
`tasks.md` like the rest of a unit's dependencies.

## Waiting

In `waiting_on`, a dependency in `merge_before` takes the branch the
cross-repo case takes today: it waits until the dependency is `merged`, or
`satisfied` with its work landed (`satisfied_landed`). Everything else is
unchanged. `base_of` needs no change: a merged dependency is no longer a base,
so the dependent's base is the trunk, or whatever else it stacks on.

## Showing it

`diagram.py` draws a `merge_before` edge as a thick arrow labelled `merged`
(`==>|merged|`), distinct from the solid same-repo and dashed cross-repo
edges. The legend gains a line for it.

## After the migration to LangGraph

Nothing moves. `docs/unit-graph.md` puts choosing what starts outside the graph,
and threads are created by the scheduler once `ready_units` allows. This
change adds one line to that document's table of what stays outside the
graph, naming merge-gated dependencies, so the `unit-graph` change builds
with the rule in place and does not have to carry it.
