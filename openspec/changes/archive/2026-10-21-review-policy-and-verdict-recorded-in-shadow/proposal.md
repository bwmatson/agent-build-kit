# Proposal

## Why

Every unit reaches a person today, in arrival order, and most of them need nothing from that person. The philosophy this work follows
is that every change is verified and a person reviews only what verification cannot vouch for. Getting there needs a decision for
each unit, made by rules and not by a model's opinion, about how much review it deserves, and it needs that decision recorded long
before anything acts on it, so that what acts on it can be calibrated from evidence.

## What Changes

- **A `review:` section in abk.yaml holds the policy.** Protected paths that never land without a person (framework defaults an
  installation extends, and a per-repo list), named classes of change matched on the paths a unit changes, the history needed before a
  class counts as proven, and a build-out flag. The policy is human-owned: no agent can write it.
- **A review tier.** `auto`, `light` or `full`, ordered, and only ever raised.
- **The planner estimates the tier of each unit.** It is recorded on the unit, floored by the group flags and the protected paths. It
  sizes nothing yet.
- **The reviewer classifies the unit,** and names the groups or files behind a classification above the plan's estimate. The existing
  `needs_human` and `escalate` outputs are unchanged.
- **A deterministic verdict** takes the highest of the planner's estimate, the exclusions, the recorded gate results, the reviewer's
  classification and the class's history, says why, and is computed after every review round and recorded, interim until the round that approves
  makes it final, with the paths it changed, its class, and whether its pull request carried the review brief. The reviewer's
  `needs_human` and `escalate` are untouched: they still hold a unit for a person during review.
- **Shadow only.** Nothing in the pipeline reads the verdict to decide anything. A failure to compute it is logged and never stops a unit.

## Impact

No behaviour change. A planner reply gains a field, the review reply gains two, a new state file is written, and a new metric is
recorded. A workspace with the build-out flag off records nothing.
