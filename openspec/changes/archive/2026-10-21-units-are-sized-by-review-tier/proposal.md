# Proposal

## Why

One ceiling, 750 changed lines, sizes every unit, and it is set so that a person can read a diff in one sitting. That holds only when a
person reads it. A unit expected to land on the strength of its gates is not read line by line, so the ceiling makes it several pull
requests where one would do, and each is overhead for everyone. A unit that does need a person's whole attention should stay small.
Sizing a unit by the review it expects keeps the large units large and the pull request a person reads small.

The planner already estimates and records that review tier (the shadow-mode change before this one); nothing uses it. This change
makes the estimate decide the ceiling, behind the build-out flag, and makes sure a plan made under one set of ceilings is noticed when
they change.

## What Changes

- **`review.ceilings`** holds a size ceiling for each review tier, `auto` 5000, `light` 2000, `full` 750, validated so that `auto` is
  at least `light`, `light` at least `full`, and `full` above `global_limits.min_unit_lines`. A repo may override any tier under its own
  `review` block, and a tier it leaves unset follows the global one.
- **`global_limits.max_unit_lines` is deprecated.** While it is read it is the `full` ceiling, with a notice from `abk config` and
  `abk doctor`. Setting it and `ceilings.full` to different values is an error. `min_unit_lines` stays and applies to every tier.
- **The planner is told the ceiling of each tier**, and the plan check holds a unit to the ceiling of the tier it is planned for, after
  the same calibration ratios as today. A single group over its unit's ceiling is still reported as needing its tasks split.
- **A group that expects full review does not share a unit with lower-tier work,** by a rule in the planner's instructions and a
  deterministic check of the plan; a join takes the highest tier of what it joins and is held to that tier's ceiling.
- **A unit's actual size is compared with its tier's ceiling,** where it is logged and listed today.
- **A plan records the sizing configuration it was made under,** and a plan whose recorded configuration is not the current one is
  stale: `abk replan` with no argument lists it, `abk status` counts it and the tick reports it, and none is replanned until a
  person asks.
- **Dormant until `review.enabled`.** With the flag off, every unit is held to the `full` ceiling (which is `max_unit_lines` for an
  installation that sets only that), so no plan, prompt or status line differs from today's.

## Impact

With the flag off, nothing changes except the new keys being accepted and a notice for `max_unit_lines`. With it on, units expected to
auto-land or get light review may be planned far larger than today, and every open change is planned under other ceilings than it was:
those plans are listed as stale and migrated deliberately by a later change, not by the next tick.
