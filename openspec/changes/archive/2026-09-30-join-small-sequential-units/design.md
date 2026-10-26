# Design

## The unit today

A `Unit` has an `id` of `<change>/<n>`, a `change`, a `repo`, a `tier` and
`groups` — group numbers within that one change. Its branch is derived from its
id. The planner's prompt tells it to combine consecutive groups in one repo up
to about `min_unit_lines`, never over `max_unit_lines`, and validation checks
that every group of the change is claimed exactly once.

A change is planned once, and again only when its `tasks.md` changes. Units
already in flight are shown to the planner as context; it may depend on them
and may not alter them.

## Group 1: a unit that carries groups from other changes

`Unit` gains `joined`: an ordered tuple of `(change, groups)` for groups taken
from changes other than its own. Empty by default, so every stored unit loads
unchanged and means what it meant.

The unit's identity does not move. Its id, branch and pull request are its
first change's. That matters: a branch name derived from anything that can
change would orphan commits, which is why it is derived from the id at all.

Everything that today reads `unit.change` and `unit.groups` to find *the work*
reads the unit's members instead — its own `(change, groups)` followed by
`joined`:

- **Build and review prompts** name each change directory and its groups, in
  order. The tests-first rule is unchanged: all members' tests, then all
  members' implementation.
- **Scoping to this unit** (what the build may and may not work ahead on)
  treats every member's groups as this unit's own.
- **Ticking tasks** ticks each member's groups in its own `tasks.md`.
- **Archive readiness** is per change, as now, but asks "is every group of this
  change in a unit that has landed" rather than "has every unit of this change
  landed". A change whose only groups were joined into another change's unit
  has no unit of its own and archives when that unit merges.
- **`Needs: <change> group <n>`** resolves to whichever unit holds that group.
- **The pull request title** stays the unit's; the body lists each change with
  its groups and spec path. **The graph** labels the node with every change.
- **Follow-ups deferred by review** are recorded against the change whose group
  they concern; where the reviewer does not say, against the unit's own change.

Nothing in group 1 produces a joined unit. Its tests build one by hand and
drive it through the runner, the archive check and the rendering.

## Group 2: the planner joins

### When

When a change is planned — new, or because its tasks changed — the planner is
shown in-flight units as now, with one more fact for each: whether it is
**unstarted** — `planned`, with no branch, no commits, no pull request and no
step to resume at. Unstarted units are candidates for joining; every other unit
is context only, exactly as today.

This is the pass in which the planner already reads all of that to decide what
depends on what, and the two questions have the same input: "does this touch
what that touches" yields either an edge or, when the pair is small and in a
line, a join. No second pass and no second agent call.

### What it may return

Alongside the new change's own units, the planner may return joins. A join
names the unit that stays and the unit whose groups it takes:

- **a new change's groups onto an existing unstarted unit** — the groups are
  carried by that unit and need no unit of their own;
- **one existing unstarted unit onto another** — of the same change or of
  different ones. The later unit's groups (its own and any it already carries)
  are carried by the earlier, and the later unit is removed.

The unit that stays is always the earlier of the two in the line, so its id,
branch name and position in the graph are the ones that survive.

### A unit that is joined away

It has no branch, no commits and no pull request — that is what unstarted
means — so removing it discards nothing. On the write:

- it is removed from the store;
- every unit that depended on it depends on the unit that took its groups;
- a `Needs` line naming one of its groups resolves to that unit, by the rule
  group 1 adds;
- its change, if it now has no unit of its own, archives when the carrying unit
  lands, also by group 1.

A later re-plan of its change must not bring it back: the planner is shown the
join as part of what is in flight, and validation treats a group already
carried by an unstarted or in-flight unit as claimed.

### The rules, checked mechanically

A join is accepted only if all hold; otherwise the round is refused, as any
malformed graph is:

1. **Same repo, same tier.**
2. **A straight line.** The later unit depends on the earlier (or would, for a
   new change's groups); no other unit depends on the earlier; and the later
   waits on nothing else unfinished. A join never hides a branch in the graph.
3. **Both unstarted**, re-read under each unit's branch lock at the moment of
   writing. If either has started since the plan was made, that join is dropped
   and everything else in the round is written — a new change whose groups were
   to be carried gets planned again next round. No work is disturbed.
4. **No flagged groups.** `[acceptance]`, `[contract]` and `[narrow]` groups
   keep the ordering rules they have and are never joined.
5. **Not opted out.** No joined group, and no group of the unit joined to, is
   marked `Separate:`.
6. **Within the ceiling.** The two estimates together are at or under
   `max_unit_lines`. For two existing units the sum is of their recorded
   estimates; for a new change's groups the planner returns their own estimate,
   so the sum is checked and not only asserted.

### Related

"Touches the same files or modules" is the planner's judgement, as the
dependency between the two already is — it is the same reading of the two
changes that produces the edge. The prompt says: join when you would otherwise
have made the new unit depend on the existing one *because they overlap*; do
not join two units that are merely both small. This part is not mechanically
checkable, which is why rules 1–6 are, and why `Separate:` exists.

### Chains

A unit joined to once may be joined to again while it is still unstarted and
still under the ceiling, so three small related units can become one — in one
round, if the planner returns the joins in order along the line. The ceiling is
what stops it.

### Inside one change

Two unstarted units of the same change are candidates like any others. Groups
of one change are still combined up to `min_unit_lines` when the change is
first planned; this lets a later round finish the job where the first stopped
short of the ceiling.

## What a person sees

- The plan log: `joined <change> group(s) <n> onto <unit> — est <a>+<b>=<c>`,
  and for two existing units, which unit was removed.
- `Separate: <reason>` is validated by `abk tags` like `Needs:` and
  `Acceptance:` — the reason is required.
- The `abk-authoring` skill says when to use it, and that a small related
  requirement may now be its own change without costing its own pull request.

## Testing

Group 1, through the runner, archive and rendering with a hand-built joined
unit: prompts name both changes; both `tasks.md` files are ticked; the joined
change archives when the unit merges and not before; a `Needs` on a joined
group resolves to the unit; a stored unit with no `joined` behaves as before.

Group 2, through `plan_round` with a planner double returning each case: a new
change's groups joined onto an existing unit; two existing units joined, of
different changes and of the same one, with the later removed and its
dependents repointed; each of the six rules violated in turn, refused; a
started, in-review or merged unit named in a join, refused; a unit that starts
between plan and write, that join dropped and the rest written; a chain of
three in one round; a re-plan that does not bring a joined unit back; the log
line.
