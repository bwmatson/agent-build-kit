# Proposal

## Why

Every unit in review is shown to a person in arrival order, and the one that needs care waits behind the ones that need nothing. The
verdict already says which is which, but nothing reads it. The same recorded facts are also the evidence a later change needs before
any class of change can land without a person: a track record of units that merged without rework, and of verdicts a person agreed
with. That record has to be accumulated, and measured honestly, before it is trusted. What a reviewer asks to have reworked depends on
what the description tells them, so a rate measured before the brief existed would be calibrated to a baseline that no longer
exists: only units whose pull request carried the brief count.

## What Changes

- **A label per review tier on the pull request,** on both forges, hyphenated names, cosmetic like the state labels.
- **The queue is ordered by tier.** `abk status` and the review tab list units in review with `full` first, then `light`. A card is
  raised only for `light` and `full` units. A unit with no verdict keeps today's behaviour.
- **The review tab shows the unit's tier and why,** beside the brief.
- **The verdict record gains an outcome** derived from the unit's history: merged without rework, merged after N reworks, or
  reverted, with a precise rule for detecting a revert from the repository.
- **Rates per class.** The clean-merge rate, the agreement rate (of the units whose evidence tier was `auto`, the share a person
  accepted as they stood) and the sample counts, computed only over records whose `brief` is true. Records made before the brief are
  kept and excluded.
- **`abk review report`,** a new read-only subcommand, and a line in `abk status`, say per class how many samples there are, the
  rates, and when a class clears the configured gates and so may be added to `review.auto_land.classes` by a person.
- **The verdict's history floor reads real history,** replacing the stub that held every class at `light`.
- **New metrics** for outcomes and agreement.

## Impact

Ordering, labels and notification cards change; no state, hold, size or merge does. A forge gains one read, the commit a merged pull
request produced. A new state file field and a new subcommand appear. The pipeline still never merges anything. With
`review.enabled` false none of it runs and everything behaves as before.
