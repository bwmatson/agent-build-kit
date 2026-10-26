# Proposal

## Why

Unit size is bounded from below and not from above. `limits.min_unit_lines`
(500) is used twice — the planner is told to group consecutive same-repo task
groups "until the estimate reaches about" it, and `units.py` flushes a unit once
its accumulated estimate crosses it. Nothing stops a unit from being far larger:
a single task group with a large estimate becomes one unit however large.

That matters because review is this pipeline's bottleneck, in two senses. A
person reviews every PR before it merges, and several are queued at any time. And
the automated review loop is where units fail: the units that ran out of rounds
were the ones reviewing the widest surfaces, where each round could still find
something new.

The evidence is close to hand. One unit in this workspace landed 54 files and
just over 5000 changed lines, and needed four review rounds to converge — a third
of a day's agent time in one unit. A ceiling on what the planner puts in one unit
is the cheapest lever on that.

## What Changes

- **`limits.max_unit_lines`, default 1000**, configurable per installation, and
  required to exceed `min_unit_lines` — a floor above the ceiling is a
  configuration that cannot be satisfied, so it fails at load rather than
  producing strange plans.
- **The planner respects it.** It is told the ceiling, and a plan whose unit
  exceeds it is rejected with that reason and re-asked, the way a malformed plan
  already is.
- **The packer respects it.** Groups are never combined past the ceiling, so the
  deterministic half agrees with the instruction the planner was given.
- **A task group too large to plan is reported as a spec problem.** When one
  group's own estimate exceeds the ceiling, no grouping helps — the change's
  tasks need splitting — and that is said, rather than a unit over the ceiling
  being emitted silently.

## Out of scope, deliberately

**Nothing is measured or enforced at push time.** The ceiling shapes plans; it
does not police branches. A unit whose estimate came in under the ceiling and
whose diff lands over it is not stopped, not held and not flagged — the work goes
to review as it does today.

That is a real gap, and worth stating rather than discovering: the unit mentioned
above was estimated at 520 lines and landed at 5032, so a planning cap would not
have caught it. What a planning cap does catch is the shape of the plan: groups
combined into one oversized unit, and changes whose task groups are authored too
coarsely to build one at a time.

If unbounded landed size turns out to matter, measuring it is a separate change
with its own decision to make about what happens when a branch exceeds the
ceiling. This change does not prejudge that.

## Impact

- **agent-build-kit**: the planner and its prompt, the packer, the configuration
  and its validation.
- Installations get a default they can raise or lower. A workspace that wants
  today's behaviour sets it high deliberately, which is different from not having
  asked.
