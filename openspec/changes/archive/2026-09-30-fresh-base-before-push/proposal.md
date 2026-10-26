# Proposal

## Why

A unit already moves onto its base when a run starts from existing commits — a
resume, a rework — and that move is a plain `rebase --onto`, with an agent
called only if it conflicts. Two gaps remain, both about how old the unit's
idea of its base is.

- **The remote is read once per tick, and a tick runs for a long time.** A tick
  fetches each repo when it starts and then builds units continuously, for an
  hour or more. A unit that starts forty minutes in restacks onto the trunk as
  it was forty minutes ago. A rework does the same. Pull requests merged in
  between are not under it.
- **Nothing looks again before the push.** Between a unit's restack and its
  push are a build, a review and tier 1. The check made before each of those
  steps compares against the unit store, which learns of a merge only when a
  poll reports it, and treats an advanced trunk as fine. So a unit pushes, and
  opens or updates its pull request, on a base that may be behind the remote —
  conflicting on arrival, which someone then has to notice and send back.
- **A base that has gone fails the unit.** A parent's pull request merged two
  minutes before its child finished. The child had been approved, had passed
  tier 1 and had pushed; opening its pull request against the parent's branch,
  which the code host had deleted on merge, failed, and the unit was recorded
  as failed. On its next run it restacked onto the trunk cleanly, with no agent
  call, and opened its pull request. Nothing about it needed a person.

## What Changes

- **A run that starts from existing commits fetches first.** The restack it
  already does is then against the remote as it is now, not as the tick found
  it.
- **A unit checks its base again before it pushes.** It fetches, works out its
  base afresh — asking the forge whether a parent's pull request has merged,
  rather than waiting for a poll — and, if its branch is not on top of that
  base, rebases. A clean rebase re-runs tier 1 and the push proceeds, with no
  agent call and the review's approval kept, as a clean restack on resume
  already keeps it. A rebase that conflicts holds the unit to resume at its
  restack, where the resolver and the review that follows it already are.
- **A pull request that cannot be opened because its base is gone holds the
  unit** to resume at its restack, instead of failing it.

## Impact

- **agent-build-kit** only: the runner's start and its push step, and the
  wiring that gives it a fetch and a fresh base.
- One fetch per run and per push, and a tier 1 re-run when a push finds its
  base moved. No agent call unless a rebase conflicts, which would have needed
  one anyway — later, after a person noticed.
- Fewer pull requests that arrive conflicting, and so fewer reworks whose only
  purpose is to rebase.

## Non-goals

- Rebasing pull requests that are open and idle when the trunk moves. That is
  what `conflicts-trigger-rework` detects; this is about a unit that is about
  to push.
- Re-reviewing after a clean rebase. A rebase that needed no resolution changes
  no line the reviewer read; tier 1 is what checks it against the new base.
