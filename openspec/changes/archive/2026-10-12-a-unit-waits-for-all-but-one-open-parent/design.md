# Design

## What was checked, and where

Read-only, `git show origin/main:src/agent_build_kit/pipeline/units.py` in the agent-build-kit checkout, and the stored graph at
`runs/units.json` in this repo; paths below are under `src/agent_build_kit/`.

- `pipeline/units.py` `base_of(unit, graph)`: candidates are the `through_satisfied` dependencies that are in the graph, in the unit's own
  repo, and `IN_REVIEW`; with none the base is the trunk, otherwise `branch_name(candidates[-1])`. "Last" means last in the order of
  `depends_on`, not newest by any measure, and not the descendant: for `depends_on = [B, A]` where B builds on A, it picks A.
- `pipeline/units.py` `waiting_on(unit, graph)`: a same-repo parent waits the unit unless its state is in `REVIEWED` (in review, merged or
  satisfied); a cross-repo parent waits unless merged or satisfied with its work landed. It does not look at the unit's own state, and does
  not compare parents with each other.
- `pipeline/units.py` `ready_units`: `if waiting_on(unit, graph): continue`, then the depth cap. Its docstring says "same-repo
  dependencies may be open (it stacks on them)". No other guard on parents exists (grep for it in `ready_units` and `waiting_on` finds
  none).
- `pipeline/units.py` `depth_of`: the longest chain of open ancestors through `through_satisfied`, same repo, `IN_REVIEW`; "a stack is a
  tree, not a line" (siblings share a depth).
- `blocked(unit, graph)` is `state == PLANNED and bool(waiting_on(...))`; `in_progress` counts a planned unit only if `_worked_on(unit)` and
  it is not blocked; `uncounted` and `_handoff` read the same.
- The stored graph (`runs/units.json`, 255 units): no planned unit has two or more in-review same-repo dependencies. Four units are in
  review or running. Nothing is affected on adoption.
- Pending changes read, in this repo's `openspec/changes/`: `failed-units-waiting-on-a-prerequisite-free-their-slot` (tasks all unticked)
  reads `waiting_on` for a failed unit; `needs-start-on-the-parents-branch` (group 3 unticked) removes `merge_before` and rewrites
  `waiting_on`, `through_satisfied`, `base_of` and `unmet_gates`.

UNVERIFIED: that `closed` and `held` states are never members of `REVIEWED`; this change reads `IN_REVIEW` only, as `base_of` and `depth_of`
do, so only an in-review parent can be an open parent, and a parent in any other state is already waited for by `waiting_on` as today.
UNVERIFIED: the name and exact predicate of "a unit that has started" (`_worked_on`, which `in_progress` uses: a recorded branch, a pushed or
approved commit or a pull request); the rule uses whatever `in_progress` uses, so the two cannot disagree.

## Definitions

**Open parent.** A dependency of the unit, looked through satisfied ones with `through_satisfied` (so a satisfied parent is replaced by what
it was built on, and a dependency in `merge_before` is left out, as there), that is in the unit's own repo and `IN_REVIEW`. A merged parent
is on the trunk and a closed one is not a base; neither is open. A satisfied one is looked through, never open itself. A planned, running,
failed or held parent is not open: `waiting_on` already holds the unit for it.

**Related.** Open parent P is related to open parent Q when Q is reachable from P (or P from Q) by following same-repo dependencies, also
through `through_satisfied`, however far and whatever the states between. P's branch then already holds Q's changes, because P was built
on Q, directly or through units between them. The relation is the same for a unit built before or after this change: it reads
`depends_on`, not the branch.

**Unrelated open parents.** The maximal open parents: those that no other open parent of the unit builds on. With one open parent, or a
chain of them, there is exactly one. With a diamond or any siblings there are several.

## The rule

1. `base_of` takes the unit's unrelated open parents. With none, the trunk. With one, its branch. With several, the unit is not ready (rule
   2) and `base_of` returns the base it would have once the others are gone, which is the same deterministic choice below.
2. `waiting_on` adds, for a unit that has never started, every unrelated open parent except the base. The unit is then not ready, and
   becomes ready when it has at most one, which happens when the others merge, close or are satisfied and landed, or when a parent the
   unit would have stacked on is reworked and goes back to planned (then `waiting_on` already names it as today).
3. The base among several is the open parent with the greatest `depth_of`; a tie goes to the one later in plan order (the graph's own
   order). The unit waits for the rest. The reason is the likelihood of order: the shallower, older pull request is the one likely to merge
   first, so waiting on it costs the least; and it is the rule `candidates[-1]` approximated for a tie, so a chain listed in plan order keeps
   today's base.
4. A chain is not a conflict: parent B depends on parent A, child depends on A and B. A is reachable from B, so A is not maximal; the base
   is B whatever order `depends_on` lists them in. This differs from today's `candidates[-1]` only for a child that lists the descendant
   before its ancestor, which today stacks on the ancestor and lacks the descendant's work: the same hazard in another guise, and fixed
   by choosing the maximal element rather than the last.
5. A diamond: child depends on S1 and S2, both depend on root R. S1 and S2 are unrelated (neither is reachable from the other); R is
   reachable from both and is not maximal. The unit waits for the one that is not the base, whichever the rule picks.

Three or more unrelated parents: the unit waits for all but one; `waiting_on` names each. The base never appears in `waiting_on`.

### Cross-repo and satisfied

Cross-repo parents are not open parents (a stack cannot span repos) and keep today's wait for a merge, whatever their relation to a same-repo
parent. A satisfied parent is looked through by `through_satisfied` before anything is compared, so it never counts as a parent and its own
open predecessor does, in its place; a satisfied parent that has landed adds nothing.

### A started unit

A unit that has started is on the branch it started on. It is not made to wait: `waiting_on` does not add parents to it, so a rework, a
resume, a restack and a push proceed, no unit is blocked retroactively, `in_progress` does not change its answer for it, and nothing
requeues or moves it. A started unit whose second parent appears later, by a replan or a `Needs:` line, is the same: nothing new happens
to it, and whatever the pending `needs-start-on-the-parents-branch` does for a `Needs:` added to a started unit (it uses the ordinary
dependency rules) is judged by its own rules. This rule never takes a started unit off its branch; it affects readiness of units not yet
started only.

## Reporting

The reason for a wait is one more entry of `waiting_on`, so every consumer reads it where it reads waits today. The status and the
ready-queue report give each waiting unit the line "waiting for <parent> to merge (second open parent)", naming the parent that must merge,
not the base. A unit that waits this way is `blocked` (a planned unit that waits on units), draws as blocked in the graph, is counted and
uncounted by `in_progress` and `uncounted` as any blocked unit is, and `abk status`'s waiting list names it. The `abk tags` line for the
same change carries the shape and the warning below.

UNVERIFIED: the exact functions that format a wait for the status and the graph (this change adds the text to whichever builds the
existing "waiting on" line; if more than one does, the builder finds each by searching for the callers of `waiting_on`). The tests assert
the text through the public status and graph outputs.

## Early warning

`abk tags <change>`, `abk tags --all` and `abk check` print a warning, and still exit as before, when a change's task groups will produce a
unit with unrelated parents. The check works on groups, not units, so it can warn for a case the planner then joins away; the wording says
the unit "can" have unrelated parents. It builds the group graph from what the planner does with the headings: group n depends on group
n-1 unless it is `Independent:` (the next group then depends on the last group before it), an `[acceptance]` or `[narrow]` group depends on
every earlier group, and a `Needs: <change> group <n>` line adds an edge to that group of another change. Only edges between groups of the
same repo count. It reports a group when two or more of its same-repo parents are neither reachable from the other, as the unit-level
definition. The shapes are named in the warning: acceptance or narrow group after an independent group, an independent group followed by a
later group in the same repo, and a `Needs:` line to another change's group in the same repo as its predecessor.

The warning has the form of the other tag warnings (the `Needs: ... merged` one prints `<path>:line N: warning: group G: ...`): the path
and line of the group heading, the group, the shape and the parents. It is not a problem count and does not change an exit code. An
`[acceptance]` group is always `tier2` and often alone in its repo, so the common clean case (a single chain, no `Independent:`) stays
quiet. UNVERIFIED: whether the pending cycle-detection change's group graph builder (it builds (change, group) nodes for `Needs:` cycles)
is present when this lands; if so the check uses it, if not it builds its own small one. Neither orders the two changes: no `Needs:`.

## Interactions

- `blocked-units-free-their-slot` (merged): a planned unit that waits this way is blocked and, if it has work, frees its place like any
  other. A never-started one does not count anyway.
- `failed-units-waiting-on-a-prerequisite-free-their-slot` (pending, nothing ticked): a failed unit has started, so this rule adds no wait
  to it, and its rule reads `waiting_on`, which is unchanged for it. A unit can also be both started and waiting through its other
  dependencies; whichever `waiting_on` names then, that change applies to it. Stated only in terms of `waiting_on`; no `Needs:`.
- `needs-start-on-the-parents-branch` (pending, group 1 ticked, groups 2 and 3 not): it makes a same-repo `Needs:` start on the parent's branch, which
  makes the hazard reachable through `Needs:` edges and not just groups. This change is written only in terms of `depends_on`,
  `through_satisfied`, `waiting_on` and `base_of`, so it holds before and after that change's removal of `merge_before` and its
  `waiting_on` rewrite, and its tests build graphs from those alone. If both land, the extra parent waits are added after that change's
  waits; the two edit `waiting_on` and `base_of` in different places, a textual merge to look at, not a reason for order. No `Needs:`.
- `planned-dependencies-never-close-a-cycle`: a cycle has no maximal element; this rule is only asked for graphs without cycles, and
  `through_satisfied` and the reachability walk keep a `seen` set so a stored cycle ends the walk instead of looping.
- The depth and concurrency caps and `max_units_in_progress` are read after readiness as they are today; a unit not ready is not weighed
  by them.

## Rejected: a synthetic base

Merging the parents' branches into a combined base would let the unit start at once. It makes a branch no one reviewed, conflicts between
parents that nothing reports until they surface in the child, and a base that moves whenever either parent is amended. The decision is
to wait.

## Docs

`docs/unit-graph.md` gains a short "Open parents" section (the definition, the wait, the base). `docs/architecture.md` scheduling
paragraph ("`ready_units` picks planned units whose dependencies allow: a same-repo dependency may be `in_review`") gets the exception.
`docs/cli.md` `abk tags` entry names the warning. The `abk-pipeline` skill (why a unit is not ready) and the `abk-authoring` skill (the
`Independent:` and `Needs:` sections: what the warning means and the way out) are updated. One changelog bullet under `## Unreleased`.
