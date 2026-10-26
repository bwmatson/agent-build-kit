# Proposal

## Why

The poller sends a unit back for rework on three signals: a review that
transitions to changes-requested, a new comment or review, and a check that has
newly failed. A branch that cannot be merged is none of them, and nothing else
notices either:

- **Mergeability is never fetched.** The poll asks the host for
  `number, headRefName, baseRefName, state, isDraft, mergedAt, labels, comments,
  statusCheckRollup, reviewDecision, reviews`. There is no mergeability in that
  list, so a conflicted branch registers as silence — the same way an
  inline-comment-only review used to, which is why `reviews` was added.
- **Restacks fire only for the dependents of a merge.** When a unit merges, the
  units that declare it as a dependency are rebased onto the new trunk. A unit
  whose dependencies all merged long ago is named by no later merge event, so
  nothing rebases it however far the trunk moves on.

Together those leave a real hole. A unit in this workspace declared one
dependency, which merged in the morning; five further units merged during the
day; its branch went from mergeable to conflicting somewhere in there, and it sat
in the review queue — reported as awaiting review, in a state a person cannot act
on — until someone opened it and found the conflict. Nothing in the pipeline was
going to dispatch a fix, because none of the three triggers had fired.

The cost is a reviewer's attention, which is the resource this pipeline has least
of: a pull request in the queue that cannot be merged is worse than one that is
not there.

## What Changes

- **The poll asks whether a pull request can still be merged**, alongside the
  checks and reviews it already reads.
- **Becoming unmergeable is a fourth rework trigger.** A branch that transitions
  into conflict is sent back, rebased onto its current base, and re-reviewed —
  the same path a failing check takes.
- **Only on the transition, and only when the host is sure.** A branch that is
  already known to be conflicted is not news and must not be re-dispatched every
  poll; and a host that has not finished computing mergeability — which it reports
  briefly after every push — is not a conflict, so an unknown answer is ignored
  and asked again next poll rather than treated as a problem.
- **A unit that cannot be merged says so where the queue is read.** `abk status`
  lists what is awaiting review; an entry a person cannot merge is marked as
  such, so the queue reflects what is actionable.

## Impact

- **agent-build-kit**: the fields the forge polls, the poller's trigger list, and
  one line of `abk status`.
- One more rework per affected unit, which is the point: the alternative is a
  human noticing.
- No change to how a merge's dependents are restacked; this is the case that
  mechanism does not cover.
