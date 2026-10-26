# Proposal

## Why

`waiting_on` (`pipeline/units.py`) has two rules, and which one applies is
decided by the repo alone:

- **Same repo:** the dependency must be through its build and review loop
  (`in_review`, `merged` or `satisfied`), and the dependent stacks on its
  branch.
- **Cross repo:** the dependency must have merged.

There is no way to say "this one must merge first" for a dependency in the
same repo. One case came up straight away. A large change that migrates the
pipeline's own unit lifecycle (`unit-graph`) must not start until a change
still reshaping the runtime, the review step and tier 2 has merged. That
change is `acp-runtime-adapter` group 4.

Stacking on its open pull request would build on a moving target, and every
rework of the earlier unit would ripple into the later one. The only way to
express this today was to hold the later unit by hand and remember to requeue
it.

## What Changes

- **`Needs: <change> group <n> merged — <reason>`.** The word `merged` after
  the group number makes the dependency one that must merge, or be satisfied
  with its work landed, before the dependent may start, in the same repo or
  not.
- **The plan records the kind.** A unit keeps the dependencies that must merge
  beside the ones it may stack on, and `abk tags` validates the qualifier.
- **The scheduler waits for the merge.** `waiting_on` applies the cross-repo
  rule to these dependencies whatever the repos. The dependent then starts on
  the trunk, since a merged dependency is no longer a base (`base_of`).
- **The graph page shows it.** Such an edge is drawn distinctly and labelled
  `merged`, so the page says why a unit is waiting even though its dependency
  is already in review.
- **It is documented with the scheduling rules,** including where it sits once
  the unit lifecycle runs as a graph (below).

## Where it sits, now and after the migration to LangGraph

This is a rule about **which unit may start**: the planner records it and
`ready_units`/`waiting_on` apply it. It is not a step of a unit's run.

The design for the unit lifecycle on LangGraph (agent-build-kit
`docs/unit-graph.md`) keeps exactly that layer outside the graph. Choosing
what starts stays abk code, and a unit's thread is created only once
`ready_units` lets it start. So nothing about this rule moves in the
migration, and the `unit-graph` change needs no part of it:

- the scheduler still decides a thread may start;
- a merge-gated dependency simply keeps that thread from being created;
- `docs/unit-graph.md`'s list of what stays outside the graph gains this rule
  by name.

## Impact

- **agent-build-kit:** the `Needs:` grammar (`work_graph.py`), the dependency
  record the planner keeps (`planner.py`, `joins.py` where Needs are linked,
  `unit_store.py`), `units.waiting_on`, the graph page (`diagram.py`), the
  `abk-authoring` skill, `docs/architecture.md` and `docs/unit-graph.md`.
- **Planning repos:** existing `Needs:` lines keep their meaning. Only a line
  that adds `merged` changes anything.
