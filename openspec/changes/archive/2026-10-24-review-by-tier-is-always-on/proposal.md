# Proposal

## Why

The earlier phases added a review tier and some scaffolding around it: the build-out flag `review.enabled`, and the single ceiling
`max_unit_lines` mapped onto the per-tier ceilings. Both were there so nothing changed under a person's feet, and both now contradict
what has shipped. The documents still say that a person merges every pull request, which stopped being true when auto-land arrived.
This change removes the scaffolding and brings the words in line, once, after everything else has shipped.

The reviewer's `needs_human` and `escalate` outputs are not scaffolding and stay. They answer a different question from the tier: the
tier says how much review a *finished* unit deserves, while these say that the reviewer, mid-review and before there is anything to
merge, cannot settle a problem and a person has to. Folding the second into the first would lose that.

## What Changes

- **`review.enabled` is removed.** Review by tier is always on. A configuration that still sets the key is read, the key is ignored
  and a notice says it is no longer used. Every place that read the flag now behaves as it did with the flag on.
- **`global_limits.max_unit_lines` is removed.** A configuration that still sets it fails to load, with a message naming
  `review.ceilings.full` and `abk config --migrate`, which moves the value. `min_unit_lines` stays.
- **The documents stop saying a human merges every pull request.** They say a person merges anything that was not auto-landed, and
  the build agent never merges. This covers the README, `AGENTS.md`, five documents, the three skills and their mirror, the footer
  of a pull request and the message of the command policy. The documents also say that a reviewer can still hand a unit to a person
  during review. The philosophy and the design document carry a note that they are implemented, and the changelog has one entry for
  each user-visible change.
- **A test fails when a document says the old rule again.**

## Impact

An installation that sets `global_limits.max_unit_lines` must move the value to `review.ceilings.full` before it upgrades, and
`abk config --migrate` does it. A configuration that sets `review.enabled` keeps loading, with a notice. The reviewer's reply and the
holds it causes are unchanged. Behaviour with the default configuration is the same as the previous phase with the flag on.
