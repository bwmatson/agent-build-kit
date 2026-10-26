# Design

## Context

`global_limits.max_unit_lines` (750) and `min_unit_lines` (400) are checked together by `LimitsConfig._ceiling_above_floor`. The
ceiling is read in `pipeline/planner.py` (`_check_ceiling`, the join check's `ceiling=`, the prompt's `max_lines` and the calibration
text's largest-raw-estimate figures) and in `pipeline/unit_size.py` and `pipeline/wiring.py` (`over_ceiling`, the log line when a
pull request lands over it). `_check_ceiling` multiplies a unit's estimate by its kind's calibration ratio and refuses a plan with a
unit over the ceiling, reporting a single group over it as `GroupTooLarge`. A plan is recorded in `runs/planned.json` under a hash of
`tasks.md`'s specification, and a change is planned again only when that hash moves. The review section, the planner's expected
review tier on each unit and the `ReviewTier` enum exist from the shadow-mode change.

## Decisions

- **Ceilings live in the `review` section.** `review.ceilings` is added to the section the shadow-mode change created, with the
  per-repo override in the repo's `review` block (`ceilings: {auto: 3000}`), validated by the same frozen models, so an unknown tier is
  refused. `ceiling_buffer` and `split_rounds` are not here: they arrive with hold and split, which is the only code that reads them.
- **Validation is in two places.** The workspace validator checks the global ceilings (`auto >= light >= full > min_unit_lines`) and
  checks the merged ceilings of every repo, so an override that breaks the order, or puts `full` at or under the floor, fails loading
  naming the repo, the tier and both values. It extends `_ceiling_above_floor`'s rule and does not replace it: `max_unit_lines` above
  `min_unit_lines` is still required while the deprecated key is read.
- **One resolver.** `ceilings_in_effect(workspace, repo)` returns the three ceilings for a repo, the way `e2e_unit_scope(repo,
  limits)` resolves a per-repo setting against the global one: a repo's own value for a tier, else the global one. A second helper
  returns the ceiling for one tier, and is the only function the planner, the join check and the size comparison call, so there is one
  place that knows the flag.
- **The flag decides what a tier means.** With `review.enabled` false the helper returns the `full` ceiling for every tier, so a unit of
  any expected tier is held to what `max_unit_lines` held it to. The `full` ceiling in effect is `ceilings.full` when the key is set and
  `max_unit_lines` otherwise, and when both are set they are equal (below), so "`max_unit_lines` alone governs" is true of every
  installation that has not set `ceilings`. With the flag on, each tier has its own ceiling. A plan, a prompt and a status line made with
  the flag off read exactly as before, which a test pins by comparing them with the text before this change.
- **`max_unit_lines` is deprecated through the machinery the root `limits` alias uses.** `deprecations(path)` returns it, as
  `global_limits.max_unit_lines`, when the file or its overlay sets it, `deprecation_notice` names `review.ceilings.full` as its
  replacement, and `abk config` and `abk doctor` print it. The notice offers `abk config --migrate`. That command is added by the
  `limits-split-into-global-and-project` change (a text edit that renames `limits` and moves three settings, then a command that
  shows the change, asks and writes once with a backup); this change teaches it one more move, `max_unit_lines` to
  `review.ceilings.full`, using the same text-edit machinery, so the whole file is migrated by one command a person runs. abk never
  edits abk.yaml on its own. Set together with a different `ceilings.full` it is an
  error naming both values; set to the same value it is read without error and still noticed. The deprecated key is read for one
  release and removed with the build-out flag by the last change of this work.
- **The planner plans to the plain ceilings.** `ceiling_buffer`, when it arrives, is the verdict's. The prompt states each tier's
  ceiling (and a repo's override where there is one) beside the existing max-lines rule, and the calibration text's "largest raw
  estimate" is computed from the ceiling of the kind's tier, so a ratio is explained in the terms it is applied in.
- **A unit is checked against the ceiling of its own expected tier.** `_check_ceiling` takes the ceiling from the tier the plan gives
  the unit, after calibration. A unit with no tier takes `full`, which is the old ceiling: a plan made before tiers existed, or a reply
  that omitted the tier and was given its floor, is never sized more loosely than the estimate allows. A single group over its unit's
  ceiling is `GroupTooLarge`, saying which tier's ceiling it was over, so a group the planner called `auto` but which is over 5000 is
  reported as needing its tasks split, as one over 750 is today.
- **Full-review work stays apart.** A group's *floor* is `full` when it is flagged `contract`, `narrow` or `acceptance` or its task
  text names a protected path (the shadow-mode change computes it). The deterministic rule is: a unit that holds a group whose floor is
  `full` holds only groups whose floor is `full`, in the plan and in any join. It is checked beside `_check_groups` and refuses the plan
  naming the unit and the groups, as the planner already refuses rather than repairs. A group the model expects to need full review
  for a reason the floor cannot see is covered by the prompt only; the verdict and hold-and-split are what catch the estimate being
  wrong. The planner's reply gains no per-group tiers.
- **A join takes the highest tier.** Joining a group or a unit onto another yields a unit whose tier is the higher of the two (a joined
  group counts at its floor), and the join is refused when the combined estimate, after calibration, is over that tier's ceiling, or
  when it would put a floor-`full` group with a group whose floor is lower. The refusal names the tier and the ceiling, as it names
  the ceiling today.
- **Actual size follows the tier.** The log line and `abk status` entry for a unit whose pull request landed over the ceiling use the
  unit's expected tier's ceiling. The buffer is not applied: the line is a warning, and it never blocked anything.
- **Plans record the sizing they were made under.** The record in `planned.json` gains `sizing`, a digest of the `review` section
  (flag, ceilings, per-repo blocks), `min_unit_lines` and `max_unit_lines`, written whenever a plan is recorded, and the empty string
  when `review.enabled` is false. A record is *stale* when its `sizing` differs from the current digest, an absent field reading as the
  empty string. So an upgrade with the flag off marks nothing stale, turning the flag on marks every recorded plan stale, and so does a
  later change of a ceiling or of the floor.
- **The digest is beside the hash, not inside it.** Folding the configuration into the hash of `tasks.md` would make the next tick plan
  every open change again, one model call each, the moment a ceiling changed. A stale plan is instead reported and left, and the
  migration change decides how to replan them. `plan_all` therefore still skips a change whose `hash` is current and whose plan
  worked, stale or not; `abk replan CHANGE` plans it and records the current digest; and `has_work` is not made true by a stale plan,
  so an idle installation stays idle. The tick prints one line naming the stale changes and how to plan them.
- **Staleness is shown where plans are listed.** `abk replan` with no argument adds `stale` to a change's line with the reason, `abk
  status` prints the count of stale plans, and the tick's line is the same text.

## Risks

- **An optimistic estimate.** A unit planned `auto` that the verdict later sends to `full` is far larger than a person should read. This
  change does not handle it; hold-and-split does, and per-tier sizing is not switched on by default until it has landed.
- **A model that ignores the separation rule.** The deterministic check is limited to floors, so a unit of floor-`light` groups the
  model expected to need full review is sized at the ceiling the model's tier gives it, and is caught at review.
- **Per-repo overrides that disagree with the planner's text.** The prompt lists a repo's override beside the global ceilings; a repo
  with none is not listed, so the common case adds one line.
- **The planner prompt grows.** The ceilings add about three lines and a line per overriding repo; the calibration section keeps its
  own size bound, and the flag-off prompt is unchanged.
