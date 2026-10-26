# Proposal

## Why

`base_of` gives a unit the branch of one open same-repo dependency, the last one it finds, and `waiting_on` and `ready_units` let the unit
start as soon as every same-repo dependency is in review ("it stacks on them"). That is right when the open parents form a chain: the
newest parent's branch already holds the older ones. It is wrong when two open parents are siblings, neither built on the other. The unit
then starts on one parent's branch and the other parent's changes are absent from it. Tier 1 can fail for missing code, or the two pull
requests conflict or duplicate work when they merge. A unit cannot run on two branches, and nothing in `ready_units` or `waiting_on` looks
for the case.

No unit in the stored graph is affected today (checked 2026-10-12: no planned unit has two open same-repo parents), so this is a latent
hazard. The shapes that produce it are ordinary: an `[acceptance]` or `[narrow]` group, which depends on every unit of its change; an
`Independent:` group followed by a later group; and `Needs:` edges to units of other changes. Each makes a unit with several parents that no
one parent's branch holds in full.

The decision is that the unit waits. No branch is made by merging the parents' branches together: that would be a synthetic base nobody
reviewed, with its own conflicts and no pull request to hold them.

## What Changes

- **Open parents and unrelated open parents:** a unit's open parents are its same-repo dependencies, looked through satisfied ones as
  `through_satisfied` does, that are in review. Of two, one is related to the other if it is reachable from it through dependencies; the
  unit's unrelated open parents are the maximal ones, those no other open parent builds on.
- **The unit waits:** with two or more unrelated open parents the unit is not ready. It waits for all but one of them, and is ready once at
  most one remains (the others merged, closed or satisfied and landed). `waiting_on` names the ones to wait for.
- **Which one is kept:** the one with the greatest stack depth is the base, a tie goes to the one later in plan order, and the unit waits
  for the others, which are the ones likely to merge first. When the open parents form a chain, the newest (the descendant) is the base,
  whatever order the dependencies are listed in.
- **Only unstarted units:** a unit that has already started keeps the branch it started on and is not held by this rule.
- **Cross-repo parents:** unchanged; they already wait for a merge.
- **Seen early and seen now:** `abk tags` and `abk check` warn, without failing, when a change's task groups will produce a unit with
  unrelated parents, naming the unit shape; the status line for a waiting unit says why.
- **Not a planning rule:** the planner is told nothing new and plans exactly as before; this is the scheduler's rule on units the plan
  produces.

## Impact

- agent-build-kit: `pipeline/units.py` (`open_parents`, `unrelated_open_parents`, `base_of`, `waiting_on`), the wait reason shown by the
  status and the graph, `abk tags`/`abk check` warnings, `docs/unit-graph.md`, `docs/architecture.md` (scheduling), `docs/cli.md`, the
  `abk-pipeline` and `abk-authoring` skills, the changelog.
- Spec: `unit-scheduling` (adds requirements; modifies none, as no requirement states the rule that same-repo dependencies may be open).
