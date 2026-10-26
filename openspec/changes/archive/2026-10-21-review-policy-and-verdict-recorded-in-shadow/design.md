# Design

## Context

Where a unit's review is decided today: the review reply (`REVIEW_PROMPT` and `parse_verdict`), the unit's approval record
(`record_approval`), and a person at `in_review`. There is no per-unit notion of how much review a change needs, no stored verdict, and
no policy section in abk.yaml.

## Decisions

- **The policy lives in abk.yaml, not a file of its own.** It is validated with the rest (`Frozen` models refuse unknown keys), read
  by `abk doctor`, and sits in the planning repo that `hooks/policy.py` already fences from build agents and from a track's `propose`.
  A test pins that fence, since the philosophy's rule that no agent edits the policy depends on it.
- **Keys arrive with the phase that uses them.** This change adds `enabled`, `protected_paths`, `protected_defaults`, `classes` and
  `auto_land.min_samples` / `auto_land.min_clean_rate`. Per-tier `ceilings` come with sizing, `ceiling_buffer` and `split_rounds`
  with hold and split, `auto_land.classes`, `audit` and `demotion` with auto-land. Unknown keys are refused, so a key cannot appear
  before the code that reads it.
- **`enabled` is a build-out flag.** Off, nothing is recorded and nothing changes. It is removed in the last change of this work.
- **Framework defaults live in code.** The never-auto-land globs (migrations, CI and deploy configuration, container definitions,
  secrets and key material, ownership files) are a list in one module with tests, so they version with the tool. An installation adds
  to them; `protected_defaults: false` replaces them. A repo's own list is added to the global one for that repo and never narrows it.
- **Classes are named path sets.** A unit belongs to the first listed class whose globs match every path it changed, and otherwise to
  `repo/test-kind` (its repo and its `unit-test` or `e2e-test` kind). The first class that will be allowed to auto-land,
  documentation or test-only changes, is a property of the paths, which the repo-and-kind key cannot express. A unit that changed no
  path is in its `repo/test-kind` class.
- **The planner's estimate is recorded and floored.** A group flagged `contract`, `narrow` or `acceptance` is `full`, and so is a group
  whose task text names a path the protected list matches. The planner's reply may be higher than the floor and never lower; a reply
  below it is refused with the unit, the group and the floor named, as the planner already refuses what it cannot accept. A unit takes
  the highest estimate of the groups it builds. A reply that omits the field takes the floor. A unit planned before this change has no
  estimate, and the verdict treats that as no floor from the plan.
- **The reviewer's classification is an input.** The reply gains `classification` (`auto`, `light` or `full`) and `drivers` (the groups
  or files behind a classification above the plan's estimate). A missing or unparseable classification is `full` in the record, since
  missing evidence is not green. `parse_verdict` still never raises. The classification criteria are text in the review prompt, in
  version control and changed only by review: what crosses a boundary another system depends on, what is hard to undo, what the tests
  do not exercise.
- **The verdict is a pure function.** Its inputs are facts already stored: the planned estimate, the changed paths, the flags of the
  groups the unit builds, the recorded results of red-first, unit-test and e2e-test gates, the reviewer's classification and drivers,
  and the class's history. It returns a tier and a reason. It makes no model call. Floors only raise the tier, and the highest wins.
  With no history the class has too few samples and is held at `light`, so an `auto` verdict needs a track record, which the
  calibration phase produces. The record carries two tiers: the **evidence tier** (everything but history) and the **tier** (with
  history), so the calibration can compare what the evidence alone said with what the track record allowed.
- **Computed after every review round, recorded in `runs/verdicts.json`.** One entry per unit, replaced each round: unit id, change,
  round, whether it is final (only the round that approves is), class, the planned estimate (or none), the classification and
  drivers, the evidence tier, the tier, the reason, the paths changed, the changed-line count, and `brief` (whether the pull request
  carried the review brief; false until that change lands). Running it after every round, not only at approval, is what lets a later
  change act early: a unit that will earn a higher tier and is too big for it is found at the first round that shows it, before
  more rework rounds are spent on a unit that will be split. Each round's verdict is computed from what exists then, so a rework
  that removes a risky path lowers the next round's tier; the rule that tiers only ratchet up is about the rules inside one
  verdict, not across rounds. Calibration counts only final entries with `brief` true, and a later change adds the outcome to each.
- **A gate that runs after review is pending, not missing.** The e2e-test runs after review and before the push, so no round before
  the last has its result. For an interim verdict, pending counts as met; for the final one it is a missing result and the floor is
  `full`. Red-first and unit-test results exist before the first review round, since checks run before review.
- **Escalation to a person is untouched.** `needs_human` and `escalate` keep working as they do: they hold the unit before anything
  is approved or pushed, whatever the classification says. A held unit has an interim entry and no final one. The classification and
  the escalation answer different questions, how much review a finished unit deserves and whether the reviewer can resolve a
  problem at all, and neither overrides the other.
- **Shadow is a property of the call site.** The verdict is computed and recorded after each round's reply is weighed, inside a
  guard that logs and swallows any error, and nothing reads it back to decide.
- **Metrics.** `abk.verdict` counts verdicts by tier, planned estimate and class; a planner-accuracy reading compares each estimate
  with the evidence tier.

## Risks

- **Prompt drift.** The classification criteria are policy and live in the prompt; the prompt test pins them.
- **A planner that always estimates `full`.** The accuracy metric shows it; nothing here depends on the estimate being low.
- **A glob that matches too much or too little.** `abk doctor` reports a protected or class glob that matches nothing in any repo.
