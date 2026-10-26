# Proposal

## Why

Per-tier ceilings let a unit expected to land on its gates be large. The planner's estimate can be wrong, and the verdict has the last
word: a unit planned `auto` at 4000 lines that the reviewer and the rules say deserves `full` review is five times what a person should
be asked to read. Handing it over as it stands defeats the ceiling, and landing it quietly to avoid that would defeat the verdict. The
unit has to go back and be made smaller, with the part that needs the person's attention separated from the part that does not.

## What Changes

- **Two settings.** `review.ceiling_buffer` (default 0.2) is the allowance over a tier's ceiling that only the verdict uses, and
  `review.split_rounds` (default 2, at most 2) is how many times one unit's lineage may be split.
- **A size step in the verdict.** A unit whose changed lines exceed the ceiling of the tier it earned by more than the buffer gets the
  outcome hold-and-split, carrying the reviewer's `drivers`; with no drivers, because the diff outgrew the tier it was planned for, the
  re-plan is asked only to bring each unit under its ceiling.
- **A hold cause for it.** The unit is held as too big for its tier, which is not a failure and does not use review rounds.
- **The held unit is superseded.** It is closed with a cause naming the units that replace it, its groups stop counting as taken, its
  pull request is closed with a comment naming them, what depended on it depends on them, and its branch is kept under a ref.
- **The planner gets pins.** The driver groups go in a unit of their own at the tier the unit earned, within that tier's ceiling, and
  the rest stay at the tier they were planned for, chained in order by dependencies. A deterministic check refuses a plan that ignores
  the pins, and the pieces get ids that cannot collide with the unit they replace.
- **Built work is reused when it can be.** A branch built per group has each group's commit pair cherry-picked onto the piece that
  holds the group; a branch built any other way is rebuilt, and its old branch is kept for reference.
- **Rounds are counted and bounded.** A failed or invalid re-plan uses a round, and when rounds run out, or a single group is over its
  ceiling, the unit is held for a person with the reason.
- **Per-tier sizing is turned on by default** in the last group, by making `review.enabled` default to true.

## Impact

With `review.enabled` false nothing changes. With it on, a unit can be closed and replaced by smaller units mid-flight: its pull
request is closed with a note and new ones are opened. The planner is asked for one more kind of plan, a split, and a split costs a
model call per round and the rebuild of what could not be reused. A person sees only units that ran out of rounds or cannot be split.
