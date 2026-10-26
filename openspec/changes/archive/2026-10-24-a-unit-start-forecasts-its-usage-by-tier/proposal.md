# Proposal

## Why

The guard admits a start when the estimate of each window plus a margin is under its threshold, and the estimate counts one flat
allowance for every unit that has spent since the reading (`usage_guard.py:1154-1191`). It never asks what the unit being admitted
will cost. With the review tiers a unit's cost varies a great deal: an `auto` unit is one review round and, mostly, no rework, a
`full` unit is several rounds of review and rework. The ledger shows the shape (`runs/usage-ledger.jsonl`, 162 units reviewed): a
review round costs $0.97 the first time, $0.50 the second and $0.39 the third, a rework $0.48, $0.56 and $0.31, and only 138 of the
162 (85%) went to a second review round and 22 of those 138 (16%) to a third. A flat figure per unit is too high for a unit that
ends after one round and too low for one that goes to three, and on 2026-10-21 it refused a unit before its review at 95% estimated
when usage was 69%.

## What Changes

- **A forecast of a unit's cost by its review tier.** For each step a unit of the tier ran in the recorded history (role, node, round,
  model), the chance that a unit of the tier reaches it times that step's mean recorded cost, summed, then times `points_per_usd` of
  each window (from `usage-is-estimated-from-recorded-cost`). The later rounds are cheaper and less likely, so a second review round
  adds about half of the first, weighted by how seldom it is reached.
- **Tier history with a floor and a prior.** The chances and costs come from the units of the tier (and of its size band when each
  band has enough) that have a final verdict; below a stated minimum the unit is forecast at the flat per-unit allowance as today.
  The chance of a later round is the upper bound at a high quantile, so a thin history is read cautiously.
- **A running unit is counted for what is left.** A unit past the rounds its tier expects is counted at what it spent (the ledger
  already has that) and at the conditional chance of more; a unit whose step is running contributes the remaining expected cost of
  that step, which the ledger cannot show because a call is written when it finishes.
- **Reservations.** A plan call due and a track whose timer fires before a window resets reserve their expected cost, recorded as
  the `plan` and `track_*` rows.
- **A start is refused when forecast plus margin does not fit**, on a reading, a held reading or an estimate, and the reason names the
  role and step that dominate.
- **Shown and checked.** `abk status` prints the forecast beside the estimate; each unit's forecast is recorded when it is admitted
  and `abk report --by tier` shows forecast against actual per review tier.

## Impact

With forecasting off, or without enough history, a start is decided as before. The emergency lane (priority 0) and
`usage_estimate_max_starts` are untouched: neither is an exemption from usage, and neither changes. The guard now reads the unit store
and the verdict record beside the ledger. A forecast record, `usage-forecasts.jsonl`, is written in the state directory.
This change builds on `usage-is-estimated-from-recorded-cost` (`points_per_usd` and its replay) and on `units-are-triaged-by-review-tier`
(the stored tier and the routing by it).
